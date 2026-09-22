"""备份。

两个动作：看现在什么情况、现在就备一份。

**没有「上次备份成功」这个字段** —— 目录本身就是记录，状态每次现场探。
存一条结论的话它会过期：目录早被删了、盘早拔了，它还在说「一切正常」，
而这个功能当初要治的毛病正是「面板上写着的和实际发生的不是一回事」。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth import current_member
from app.db import get_session
from app.models import Member
from app.services import backup as backup_svc

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
def backup_status(
    session: Session = Depends(get_session), _: Member = Depends(current_member)
) -> dict[str, Any]:
    return backup_svc.status(session)


@router.post("")
def make_backup(
    session: Session = Depends(get_session), _: Member = Depends(current_member)
) -> dict[str, Any]:
    return backup_svc.run(session)
