from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import timedelta
import duckdb

from app.database import get_db
from app.utils.auth import (
    verify_password, get_password_hash, create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES, get_current_user
)
from app.utils.templates import TemplateResponse

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: duckdb.DuckDBPyConnection = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if current_user:
        return RedirectResponse("/", status_code=303)
    return TemplateResponse("auth/login.html", {"request": request, "error": None})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    user = db.execute("SELECT id, username, password_hash, role, full_name FROM users WHERE username = ?", [username]).fetchone()
    if not user or not verify_password(password, user[2]):
        return TemplateResponse("auth/login.html", {
            "request": request,
            "error": "用户名或密码错误"
        })
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user[1], "role": user[3], "user_id": user[0]},
        expires_delta=access_token_expires
    )
    
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: duckdb.DuckDBPyConnection = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if current_user:
        return RedirectResponse("/", status_code=303)
    return TemplateResponse("auth/register.html", {"request": request, "error": None})


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("consumer"),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    if password != confirm_password:
        return TemplateResponse("auth/register.html", {
            "request": request,
            "error": "两次输入的密码不一致"
        })
    
    if len(password) < 6:
        return TemplateResponse("auth/register.html", {
            "request": request,
            "error": "密码长度至少6位"
        })
    
    existing = db.execute("SELECT id FROM users WHERE username = ? OR email = ?", [username, email]).fetchone()
    if existing:
        return TemplateResponse("auth/register.html", {
            "request": request,
            "error": "用户名或邮箱已被注册"
        })
    
    if role not in ["consumer", "farmer"]:
        role = "consumer"
    
    hashed_password = get_password_hash(password)
    
    db.execute("""
        INSERT INTO users (username, email, password_hash, full_name, role)
        VALUES (?, ?, ?, ?, ?)
    """, [username, email, hashed_password, full_name, role])
    
    return RedirectResponse("/auth/login", status_code=303)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("access_token")
    return response
