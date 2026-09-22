from __future__ import annotations

import base64
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.auth import authenticate, current_member, make_token
from app.db import get_session
from app.errors import AppError
from app.models import Member
from app.schemas import LoginIn, LoginOut, MemberOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------- 登录节流
#
# 原来登录不限次数：局域网里谁都能对着 /api/auth/login 一秒试几十个密码。
# **按「这台机器 + 这个登录名」记**，不只按登录名：只按登录名的话，
# 任何人故意输错五次就能把室友锁在门外。
# 前 FREE_TRIES 次随便错；之后每错一次要等的时间翻倍，封顶 MAX_WAIT 秒。
# 放在进程内存里：重启就清零 —— 三个人的规模，不值得为它建表。

FREE_TRIES = 5
BASE_WAIT = 30
MAX_WAIT = 15 * 60
_fails: dict[tuple[str, str], tuple[int, float]] = {}
#: 「查还能不能试 → 记一次失败」必须是一步：并发发 30 个错密码的话，
#: 先查后记的写法 30 个都查到「还没到 5 次」，全部真的验了密码
_lock = threading.Lock()


def _wait_left(key: tuple[str, str], now: float) -> int:
    n, last = _fails.get(key, (0, 0.0))
    if n < FREE_TRIES:
        return 0
    wait = min(BASE_WAIT * 2 ** (n - FREE_TRIES), MAX_WAIT)
    return max(0, int(last + wait - now + 0.999))


def _note_fail(key: tuple[str, str], now: float) -> None:
    n, _ = _fails.get(key, (0, 0.0))
    _fails[key] = (n + 1, now)
    if len(_fails) > 1000:                       # 防有人换着名字刷，把内存撑大
        for k, (_, t) in list(_fails.items()):
            if now - t > MAX_WAIT:
                del _fails[k]


def to_member_out(m: Member) -> MemberOut:
    data = m.model_dump()
    blob = data.pop("avatar", None)
    return MemberOut(
        **data,
        is_active=m.is_active(),
        avatar=f"data:image/webp;base64,{base64.b64encode(blob).decode()}" if blob else None,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, session: Session = Depends(get_session)) -> LoginOut:
    key = (request.client.host if request.client else "?", body.name.strip().lower())
    now = time.monotonic()
    with _lock:
        wait = _wait_left(key, now)
        if wait:
            # 在验密码**之前**就挡：挡在之后的话，攻击者照样拿到了「这次对不对」
            raise AppError("too_many_logins", f"retry in {wait}s", status=429, seconds=wait)
        # **先记成失败再去验**：验对了再撤掉。这样同一时刻最多放 FREE_TRIES 个进去
        _note_fail(key, now)
    member = authenticate(session, body.name, body.password)
    if member is None:
        # 同样不配码：登录页是按 e.status === 401 显示「用户名或密码不对」的
        # （别的状态码要原样说出来 —— 断网时说成密码错会让人一遍遍改密码）
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码不对")
    with _lock:
        _fails.pop(key, None)
    return LoginOut(token=make_token(member), member=to_member_out(member))


@router.get("/me", response_model=MemberOut)
def me(member: Member = Depends(current_member)) -> MemberOut:
    return to_member_out(member)
