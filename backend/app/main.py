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
import jwt

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sneha Creations ERP", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

FRONTEND_DIR = "/home/nawnitnihal/awsv3/frontend"
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")

@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/login")
async def login():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/static/index.html")
async def serve_index(request: Request):
    token = request.query_params.get("token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    if not token:
        return RedirectResponse(url="/login", status_code=302)
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except:
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/static/js/{filename}")
async def serve_js(filename: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "js", filename))

@app.get("/static/css/{filename}")
async def serve_css(filename: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "css", filename))

@app.get("/static/assets/{path:path}")
async def serve_assets(path: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "assets", path))

from fastapi.staticfiles import StaticFiles
import os

# Serve the frontend directory
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../../frontend")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../../frontend/index.html"))
from fastapi.responses import RedirectResponse

@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url="/static/assets/images/favicon.ico")
