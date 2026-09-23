from __future__ import annotations

import hashlib
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


#: 节流表最多记这么多条。先清过期的；还超就从最久没动静的清起 ——
#: 原来只清「过期的」，一直换着名字刷的话一条都清不掉
MAX_TRACKED = 1000


def _note_fail(key: tuple[str, str], now: float) -> None:
    n, _ = _fails.get(key, (0, 0.0))
    _fails[key] = (n + 1, now)
    if len(_fails) > MAX_TRACKED:                # 防有人换着名字刷，把内存撑大
        for k, (_, t) in list(_fails.items()):
            if now - t > MAX_WAIT:
                del _fails[k]
        if len(_fails) > MAX_TRACKED:
            for k, _ in sorted(_fails.items(), key=lambda kv: kv[1][1])[: len(_fails) - MAX_TRACKED]:
                del _fails[k]


def to_member_out(m: Member, viewer: int | None = None) -> MemberOut:
    """`viewer` 给了、又不是本人：登录名留空。

    个人设置里写着「登录名只有自己看得到」—— 原来接口却把每个人的登录名发给所有人，
    那是一对凭据的一半。建人的那一次不给 viewer：新室友的登录名是加人的那位亲手敲的，
    还得由他转告
    """
    data = m.model_dump()
    blob = data.pop("avatar", None)
    if viewer is not None and viewer != m.id:
        data["name"] = ""
    return MemberOut(
        **data,
        is_active=m.is_active(),
        # 地址里带版本号和内容指纹：换一次头像地址就变，旧的那张可以放心长缓存。
        # 光靠版本号不够 —— 恢复一份旧备份会把号码退回去，之后再换的头像会撞上
        # 别的手机早就缓存过的那个地址，一直显示恢复之前的照片
        avatar=f"/api/members/{m.id}/avatar?v={m.avatar_version}-{hashlib.sha1(blob).hexdigest()[:8]}"
        if blob else None,
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
