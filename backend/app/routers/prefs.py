"""个人偏好：深浅色、主题色。只读写**自己的**。

值只认一小撮字母：颜色表在前端（每一档的对比度是在那边算过、测过的），
这里不再抄一份 —— 前端读到认不出的值就退回默认，所以挡住乱七八糟的字符就够了。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.errors import AppError
from app.models import Member, MemberPref, now_utc

router = APIRouter(prefix="/api/prefs", tags=["prefs"])

#: 有哪几项。多一项偏好就在这儿加一个键（前端 src/prefs.ts 同步加）
PREF_KEYS = ("scheme", "theme_color")
_VALUE = re.compile(r"^[a-z0-9-]{1,32}$")


def _mine(session: Session, me: Member) -> dict[str, str]:
    rows = session.exec(select(MemberPref).where(MemberPref.member_id == me.id)).all()
    return {r.key: r.value for r in rows}


@router.get("", response_model=dict[str, str])
def get_prefs(session: Session = Depends(get_session), me: Member = Depends(current_member)):
    """只返存过的那几项。没存过的前端用默认 —— 也靠「没有」认出这个人还没对过表"""
    return _mine(session, me)


@router.patch("", response_model=dict[str, str])
def set_prefs(
    body: dict[str, str],
    session: Session = Depends(get_session),
    me: Member = Depends(current_member),
):
    for key, value in body.items():
        # fullmatch：match 配 $ 的话，"dark\n" 这种带换行的也会放进来
        if key not in PREF_KEYS or not _VALUE.fullmatch(value):
            raise AppError("pref_invalid", f"bad pref {key}={value!r}", key=key)
    # upsert：两台手机同时第一次存同一项，先查后插的写法两边都查到「没有」、都去插，
    # 后提交的那个撞主键 → 裸 500
    for key, value in body.items():
        session.execute(
            sqlite_insert(MemberPref)
            .values(member_id=me.id, key=key, value=value, updated_at=now_utc())
            .on_conflict_do_update(
                index_elements=["member_id", "key"], set_={"value": value, "updated_at": now_utc()}
            )
        )
    session.commit()
    return _mine(session, me)
