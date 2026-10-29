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


@router.get("/alert")
def backup_alert(
    session: Session = Depends(get_session), _: Member = Depends(current_member)
) -> dict[str, str | None]:
    """平时要不要亮红点。备份的状态原来只在「更多 → 设置 → 备份」最底下那一块看得见，
    而平时没人会去看 —— 目录没挂上、盘满了，备份能一声不吭地停好几周。
    前端开 App、切回前台各问一次。哪些算「出问题」见 backup_svc.alert。
    要登录：/api/health 不带这个（Docker 每 30 秒探一次活，不能每次都去打开备份文件）"""
    return {"alert": backup_svc.alert(session)}


@router.post("")
def make_backup(
    session: Session = Depends(get_session), _: Member = Depends(current_member)
) -> dict[str, Any]:
    return backup_svc.run(session)
