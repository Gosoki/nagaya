"""登录 —— 每人一个账号，token 90 天（手机登一次管仨月）。

密钥优先读环境变量；没有就在 data/ 下生成一份并持久化 —— 否则每次重启
所有人都被踢下线，手机上尤其烦人。
"""

from __future__ import annotations

import datetime as dt
import os
import secrets
from pathlib import Path

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.db import DB_PATH, get_session
from app.models import Member

ALGORITHM = "HS256"
TOKEN_DAYS = 90
#: bcrypt 只认前 72 字节，超长密码会被悄悄截断，不如直接拒绝
MAX_PASSWORD_BYTES = 72

_bearer = HTTPBearer(auto_error=False)


def _load_secret() -> str:
    env = os.getenv("NAGAYA_SECRET")
    if env:
        return env
    path = Path(DB_PATH).parent / ".secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return value


SECRET = _load_secret()


def hash_password(raw: str) -> str:
    if len(raw.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"密码不能超过 {MAX_PASSWORD_BYTES} 字节")
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    if not hashed or len(raw.encode()) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(member_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": str(member_id), "iat": now, "exp": now + dt.timedelta(days=TOKEN_DAYS)},
        SECRET,
        algorithm=ALGORITHM,
    )


def current_member(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Member:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(creds.credentials, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录信息无效") from None

    member = session.get(Member, int(payload["sub"]))
    if member is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在")
    return member


def authenticate(session: Session, name: str, password: str) -> Member | None:
    member = session.exec(select(Member).where(Member.name == name)).first()
    if member is None or not verify_password(password, member.password_hash):
        return None
    return member
