from fastapi import FastAPI, Request, HTTPException, Depends, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .database import Base, engine, SessionLocal
from .auth import router as auth_router
from .models import User, Chat, Message
from fastapi.staticfiles import StaticFiles

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Bridgegram")
app.add_middleware(SessionMiddleware, secret_key="SUPER_SECRET_KEY_CHANGE_ME")

templates = Jinja2Templates(directory="app/templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Не авторизован")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# auth router: /auth/send-code, /auth/login, /auth/register...
app.include_router(auth_router)

@app.get("/chats", response_class=HTMLResponse)
def chat_list(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)

    return templates.TemplateResponse(
        "chat_list.html",
        {
            "request": request,
            "chats": current_user.chats,
            "user": current_user,
            "my_username": current_user.username,   # ✅ добавили
        }
    )

@app.get("/search-user")
def search_user(username: str, db: Session = Depends(get_db)):
    username = username.strip()
    if not username.startswith("@"):
        username = "@" + username

    user = db.query(User).filter(User.username == username).first()
    if user:
        return {"username": user.username}
    return {"detail": "Пользователь не найден"}


@app.post("/create-chat")
def create_chat(
    request: Request,
    data: dict = Body(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    username = (data.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Укажите username")

    if not username.startswith("@"):
        username = "@" + username

    other_user = db.query(User).filter(User.username == username).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if other_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя создать чат с собой")

    # если уже есть чат
    for chat in current_user.chats:
        if other_user in chat.participants:
            return {"message": "Чат уже существует"}

    chat = Chat(name=f"{current_user.username} и {other_user.username}")
    chat.participants.extend([current_user, other_user])

    db.add(chat)
    db.commit()
    db.refresh(chat)

    return {"message": "Чат создан"}


@app.get("/chat/{chat_id}", response_class=HTMLResponse)
def open_chat(request: Request, chat_id: int, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    if current_user not in chat.participants:
        raise HTTPException(status_code=403, detail="Нет доступа")

    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "chat": chat, "user": current_user},
    )


@app.post("/chat/{chat_id}/send-message")
def send_message(
    request: Request,
    chat_id: int,
    data: dict = Body(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Сообщение пустое")

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat or current_user not in chat.participants:
        raise HTTPException(status_code=403, detail="Нет доступа")

    message = Message(chat_id=chat.id, user_id=current_user.id, text=text)
    db.add(message)
    db.commit()
    db.refresh(message)

    return {"user": current_user.username, "text": message.text}


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from fastapi import Query

@app.get("/chat/{chat_id}/messages")
def get_new_messages(
    request: Request,
    chat_id: int,
    after_id: int = Query(0),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat or current_user not in chat.participants:
        raise HTTPException(status_code=403, detail="Нет доступа")

    msgs = (
        db.query(Message)
        .filter(Message.chat_id == chat_id, Message.id > after_id)
        .order_by(Message.id.asc())
        .all()
    )

    return {
        "messages": [
            {
                "id": m.id,
                "user": m.user.username if m.user else "unknown",
                "text": m.text,
                "is_me": (m.user_id == current_user.id),
            }
            for m in msgs
        ]
    }
