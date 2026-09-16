from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from .database import engine, Base
from .routers import (
    master_inventory, master_data, buyer_order, bom, rm_order, grn, issue_rm, reports, utils, google_sheets,
    costing_approval, rm_inspection, internal_fg_order, fg_inspection, fg_inventory
)
from . import auth
from .config import settings
import os
from pathlib import Path
import jwt

Base.metadata.create_all(bind=engine)

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(title="Sneha Creations ERP", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(master_inventory.router)  # Specific routes first
app.include_router(master_data.router)
app.include_router(buyer_order.router)
app.include_router(bom.router)
app.include_router(rm_order.router)
app.include_router(grn.router)
app.include_router(issue_rm.router)
app.include_router(reports.router)
app.include_router(utils.router)
app.include_router(google_sheets.router)
app.include_router(costing_approval.router)
app.include_router(rm_inspection.router)
app.include_router(internal_fg_order.router)
app.include_router(fg_inspection.router)
app.include_router(fg_inventory.router)

# ---------------------------------------------------------------------------
# Frontend serving (single source of truth for paths)
# ---------------------------------------------------------------------------
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if not FRONTEND_DIR.is_dir():
    raise RuntimeError(f"Frontend directory not found: {FRONTEND_DIR}")


# Static assets: /static/* -> frontend/*
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_login():
    return FileResponse(str(FRONTEND_DIR / "login.html"))


@app.get("/login")
async def serve_login_alias():
    return FileResponse(str(FRONTEND_DIR / "login.html"))


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/static/assets/images/favicon.ico")
