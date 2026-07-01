import bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
import os

SECRET_KEY = os.getenv("SECRET_KEY", "ritual-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    pw = password[:72].encode("utf-8")
    hashed = bcrypt.hashpw(pw, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain[:72].encode("utf-8")
    return bcrypt.checkpw(pw, hashed.encode("utf-8"))


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_user_id_from_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload.get("sub"))
    except JWTError:
        return None


def get_current_user_id(request: Request):
    token = request.cookies.get("ritual_token")
    if not token:
        return None
    return get_user_id_from_token(token)


def require_auth(request: Request) -> int:
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user_id