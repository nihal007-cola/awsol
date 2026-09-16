from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt
import bcrypt
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, EmailStr

from slowapi import Limiter
from slowapi.util import get_remote_address

from .database import get_db
from .models import User

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
security = HTTPBearer()

login_limiter = Limiter(key_func=get_remote_address)

from dotenv import load_dotenv as _ld
_ld(Path(__file__).resolve().parent.parent.parent / ".env")
JWT_SECRET = os.environ["JWT_SECRET"]  # fail fast if missing
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24  # 24 hours

# Pydantic models
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


def require_role(*allowed_roles: str):
    """Dependency factory: raises 403 unless current_user.role is in allowed_roles."""
    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return current_user
    return _checker


@router.post("/login", response_model=LoginResponse)
@login_limiter.limit("10/minute")
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    
    # Update last_login
    user.last_login = datetime.utcnow()
    db.commit()
    
    token = create_jwt(user.id, user.email, user.role)
    return LoginResponse(
        access_token=token,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active
    )

# ==============================================================
# PASSWORD RESET FLOW
# ==============================================================

import secrets
from .mailer import send_email
from .models import PasswordResetOTP

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
RESET_TOKEN_EXPIRY_MINUTES = 10


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(otp: str) -> str:
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt()).decode()


def _check_otp(otp: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(otp.encode(), hashed.encode())
    except Exception:
        return False


def _create_reset_jwt(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "purpose": "password_reset",
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@router.post("/forgot-password")
@login_limiter.limit("5/minute")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """Send a 6-digit OTP to the email IF the user exists.

    Always returns 200 with the same message — do not leak which emails
    are registered.
    """
    email = body.email.lower()
    generic = {"success": True, "message": "If that email is registered, an OTP has been sent."}

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        return generic

    # Invalidate any prior unused OTPs for this email.
    now = datetime.utcnow()
    db.query(PasswordResetOTP).filter(
        PasswordResetOTP.email == email,
        PasswordResetOTP.used_at.is_(None),
    ).update({"used_at": now})

    otp = _generate_otp()
    row = PasswordResetOTP(
        email=email,
        otp_hash=_hash_otp(otp),
        expires_at=now + timedelta(minutes=OTP_EXPIRY_MINUTES),
        attempts=0,
    )
    db.add(row)
    db.commit()

    body_text = (
        f"Hello {user.full_name or user.email},\n\n"
        f"Your awsol password reset code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in {OTP_EXPIRY_MINUTES} minutes.\n"
        f"If you did not request a password reset, ignore this email.\n\n"
        f"— Sneha Creations ERP"
    )
    send_email(email, "awsol password reset code", body_text)
    return generic


@router.post("/verify-otp")
def verify_otp(
    body: VerifyOTPRequest,
    db: Session = Depends(get_db),
):
    """Verify the OTP. On success return a short-lived reset token."""
    email = body.email.lower()
    otp = (body.otp or "").strip()

    now = datetime.utcnow()
    row = (
        db.query(PasswordResetOTP)
        .filter(
            PasswordResetOTP.email == email,
            PasswordResetOTP.used_at.is_(None),
        )
        .order_by(PasswordResetOTP.id.desc())
        .first()
    )

    if not row:
        raise HTTPException(status_code=400, detail="No active OTP for this email")
    if row.expires_at < now:
        raise HTTPException(status_code=400, detail="OTP expired")
    if (row.attempts or 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts")
    if not _check_otp(otp, row.otp_hash):
        row.attempts = (row.attempts or 0) + 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP")

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="User not available")

    row.used_at = now
    db.commit()

    reset_token = _create_reset_jwt(user.id, user.email)
    return {"success": True, "reset_token": reset_token}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Consume a reset token and update the user's password."""
    try:
        payload = jwt.decode(body.reset_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset token")

    if len(body.new_password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="User not available")

    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()

    return {"success": True, "message": "Password updated. You can now log in."}
