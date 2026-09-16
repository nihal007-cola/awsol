#!/usr/bin/env python3
"""awsol user management.

Run from the awsol backend venv:

    python user_admin.py add
    python user_admin.py delete
    python user_admin.py list
"""
import os
import sys
import getpass
import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# Load DATABASE_URL from the awsol .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Check ~/awsol/.env", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DATABASE_URL, future=True)

VALID_ROLES = ("admin", "manager", "viewer")


def prompt_add():
    print("── Add user ──")
    email = input("Email: ").strip().lower()
    if not email or "@" not in email:
        print("ERROR: invalid email")
        return
    role = input(f"Role {VALID_ROLES}: ").strip().lower()
    if role not in VALID_ROLES:
        print(f"ERROR: role must be one of {VALID_ROLES}")
        return
    full_name = input("Full name (optional): ").strip() or email.split("@")[0]
    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm: ")
    if pw1 != pw2:
        print("ERROR: passwords do not match")
        return
    if len(pw1) < 8:
        print("ERROR: password must be at least 8 characters")
        return

    pw_hash = bcrypt.hashpw(pw1.encode(), bcrypt.gensalt()).decode()

    with engine.begin() as c:
        try:
            c.execute(text("""
                INSERT INTO users (email, password_hash, full_name, role, is_active)
                VALUES (:e, :h, :n, :r, true)
            """), {"e": email, "h": pw_hash, "n": full_name, "r": role})
            print(f"✓ Added {email} ({role})")
        except IntegrityError:
            print(f"ERROR: user {email} already exists")


def prompt_delete():
    with engine.begin() as c:
        rows = c.execute(text("""
            SELECT id, email, full_name, role, is_active
            FROM users
            ORDER BY id
        """)).all()

    if not rows:
        print("No users.")
        return

    print("── Users ──")
    for i, r in enumerate(rows, 1):
        active = "" if r.is_active else " [inactive]"
        print(f"  {i}. [{r.role}] {r.email}  ({r.full_name}){active}")

    try:
        choice = int(input("Delete which #? (0 to cancel): ").strip())
    except ValueError:
        print("Cancelled.")
        return

    if choice <= 0 or choice > len(rows):
        print("Cancelled.")
        return

    target = rows[choice - 1]
    confirm = input(f"Delete {target.email}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :id"), {"id": target.id})
    print(f"✓ Deleted {target.email}")


def list_users():
    with engine.begin() as c:
        rows = c.execute(text("""
            SELECT id, email, full_name, role, is_active, created_at, last_login
            FROM users ORDER BY id
        """)).all()
    if not rows:
        print("No users.")
        return
    for r in rows:
        active = "active" if r.is_active else "inactive"
        last = r.last_login.isoformat() if r.last_login else "never"
        print(f"{r.id:>3}  {r.role:<8}  {r.email:<30}  {active:<8}  last_login={last}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python user_admin.py {add|delete|list}")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "add":
        prompt_add()
    elif cmd == "delete":
        prompt_delete()
    elif cmd == "list":
        list_users()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
