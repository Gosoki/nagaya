"""登录 —— 每人一个账号，token 90 天（手机登一次管仨月）。

密钥优先读环境变量；没有就在 data/ 下生成一份并持久化 —— 否则每次重启
所有人都被踢下线，手机上尤其烦人。
"""

from __future__ import annotations

import datetime as dt
import hmac
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
from app.services.ledger import LedgerError

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
    # 抛 LedgerError 而不是裸 ValueError：裸的那个没人接，一路冒到 FastAPI 顶上变成
    # 500「Internal Server Error」。这是个中日文界面的 App，拿一句中文当密码
    # （25 个汉字就是 75 字节）是最自然的写法，不该以「服务器坏了」收场。
    # 走 {code,message,detail} 这条线，文案才留在前端 —— 后端不返界面文案
    if len(raw.encode()) > MAX_PASSWORD_BYTES:
        raise LedgerError(
            "password_too_long",
            f"password exceeds {MAX_PASSWORD_BYTES} bytes",
            limit=MAX_PASSWORD_BYTES,
        )
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    if not hashed or len(raw.encode()) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def session_tag(member: Member) -> str:
    """把「这个人现在的密码」压成一个短指纹，写进 token 当版本号。

    改了密码，旧 token 就该当场作废 —— 手机丢了、或者被人瞄到密码时，
    改密码是唯一的自救动作，而它原来不断任何已经发出去的 session
    （token 管 90 天）。

    **不给 Member 加字段**：`create_all` 不会给已有的表补列，实测老库打开就是
    `no such column`，而现在还没到切 Alembic 那一步（SPEC D18：录真账之前再切）。
    密码哈希本来就随密码变，拿它当版本号刚好，一个字节的 schema 都不用动。

    过一道 HMAC 而不是直接截哈希：token 的 payload 是 base64，谁拿到 token
    谁就读得到。虽然那个人本来就是他自己，但没必要顺手把密码哈希的指纹也发出去。
    """
    return hmac.new(SECRET.encode(), member.password_hash.encode(), "sha256").hexdigest()[:16]


def make_token(member: Member) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {
            "sub": str(member.id),
            "pw": session_tag(member),
            "iat": now,
            "exp": now + dt.timedelta(days=TOKEN_DAYS),
        },
        SECRET,
        algorithm=ALGORITHM,
    )


def current_member(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Member:
    # 这一屏的 401 **故意不走 code 那条线**：前端在读 body 之前就按状态码短路了
    # （client.ts 看到 401 直接清 token 跳登录页），给它配个码也没人会读到。
    # 其它路由错都已经改成 {code,message,detail} 了，见 app/errors.py
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
    # 密码换过了 —— 这张 token 是改之前发的。**没有 pw 的老 token 也一并作废**：
    # 宽容一次就等于永远留着那个洞，而代价只是大家重登一次
    if not hmac.compare_digest(payload.get("pw", ""), session_tag(member)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "密码改过了，请重新登录")
    return member


def authenticate(session: Session, name: str, password: str) -> Member | None:
    member = session.exec(select(Member).where(Member.name == name)).first()
    if member is None or not verify_password(password, member.password_hash):
        return None
    return member
