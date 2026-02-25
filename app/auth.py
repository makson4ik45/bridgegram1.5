import os
import random
import re
import traceback
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from .database import SessionLocal
from .models import User, AuthCode

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------- DB ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Utils ----------
USERNAME_REGEX = r"^@[a-zA-Z0-9_]{4,31}$"

def generate_code() -> str:
    return str(random.randint(100000, 999999))

def code_expires(minutes: int = 5) -> datetime:
    return datetime.utcnow() + timedelta(minutes=minutes)

def is_valid_username(username: str) -> bool:
    return re.match(USERNAME_REGEX, username) is not None

def send_email_code(to_email: str, code: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    email_from = os.getenv("EMAIL_FROM", "Bridgegram <onboarding@resend.dev>")

    # для логов Render (безопасно: не печатаем ключ)
    print("RESEND_API_KEY set:", bool(api_key), "EMAIL_FROM:", email_from)

    if not api_key:
        raise RuntimeError("RESEND_API_KEY не задан в переменных окружения")

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": email_from,
            "to": [to_email],
            "subject": "Bridgegram — код входа",
            "text": (
                f"Ваш код для входа в Bridgegram: {code}\n\n"
                f"Код действует 5 минут.\n\n"
                f"Если это были не вы — просто проигнорируйте письмо."
            ),
        },
        timeout=15,
    )

    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")

# ---------- Schemas ----------
class SendCodeSchema(BaseModel):
    email: EmailStr

class LoginSchema(BaseModel):
    email: EmailStr
    code: str

class RegisterSchema(BaseModel):
    email: EmailStr
    username: str
    code: str

# ---------- Routes ----------
@router.post("/send-code")
def send_code(data: SendCodeSchema, db: Session = Depends(get_db)):
    email = data.email
    code = generate_code()

    # удаляем старые коды
    db.query(AuthCode).filter(AuthCode.email == email).delete()

    db.add(AuthCode(email=email, code=code, expires_at=code_expires(5)))
    db.commit()

    try:
        send_email_code(email, code)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    return {"message": "Код отправлен на почту"}

@router.post("/login")
def login(data: LoginSchema, request: Request, db: Session = Depends(get_db)):
    record = db.query(AuthCode).filter(
        AuthCode.email == data.email,
        AuthCode.code == data.code,
        AuthCode.expires_at > datetime.utcnow()
    ).first()

    if not record:
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")

    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        return {"need_register": True}

    db.delete(record)
    db.commit()

    request.session["user_id"] = user.id
    return {"id": user.id, "username": user.username}

@router.post("/register")
def register(data: RegisterSchema, request: Request, db: Session = Depends(get_db)):
    if not is_valid_username(data.username):
        raise HTTPException(status_code=400, detail="Username должен начинаться с @ и быть 4–31 символ")

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username занят")

    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Аккаунт с таким email уже существует")

    record = db.query(AuthCode).filter(
        AuthCode.email == data.email,
        AuthCode.code == data.code,
        AuthCode.expires_at > datetime.utcnow()
    ).first()

    if not record:
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")

    user = User(email=data.email, username=data.username)

    db.add(user)
    db.delete(record)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    return {"message": "Аккаунт создан", "username": user.username}

@router.get("/check-username")
def check_username(username: str, db: Session = Depends(get_db)):
    return {"available": db.query(User).filter(User.username == username).first() is None}