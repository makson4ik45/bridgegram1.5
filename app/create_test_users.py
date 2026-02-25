from app.database import SessionLocal, Base, engine
from app.models import User

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Список тестовых пользователей
test_users = [
    "+79160000001",
    "+79160000002",
    "+79160000003",
]

for phone in test_users:
    # Проверяем, есть ли уже такой пользователь
    if not db.query(User).filter(User.phone == phone).first():
        user = User(phone=phone, is_verified=1)  # сразу отмечаем как верифицированного
        db.add(user)

db.commit()
db.close()

print("Тестовые пользователи созданы!")