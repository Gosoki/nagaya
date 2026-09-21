from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Member, Period
from app.schemas import BalancesOut, PeriodOut
from app.services import bill as bill_svc
from app.services import ledger as ledger_svc

router = APIRouter(prefix="/api", tags=["ledger"])


@router.get("/balances", response_model=BalancesOut)
def get_balances(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """每个人的余额。正数＝别人欠他。合计恒为 0。"""
    return BalancesOut(balances={str(k): v for k, v in ledger_svc.balances(session).items()})


@router.get("/periods", response_model=list[PeriodOut])
def list_periods(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    return list(session.exec(select(Period).order_by(Period.start_date.desc())))


def _get_period(session: Session, period_id: int) -> Period:
    period = session.get(Period, period_id)
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账期不存在")
    return period


@router.get("/periods/{period_id}/bill")
def get_bill(
    period_id: int,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
) -> dict:
    """月度账单：期初结转 + 本期发生 + 本期已收付 + 转账方案。"""
    return bill_svc.build_bill(session, _get_period(session, period_id))


@router.post("/periods/{period_id}/close")
def close_period(
    period_id: int,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> dict:
    """关账。允许带着未结清余额关 —— 那就是赊账，差额结转下一期。"""
    period = bill_svc.close_period(session, _get_period(session, period_id), actor_id=member.id)
    return {"id": period.id, "label": period.label, "status": period.status.value}


@router.post("/periods/{period_id}/reopen")
def reopen_period(
    period_id: int,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> dict:
    period = bill_svc.reopen_period(session, _get_period(session, period_id), actor_id=member.id)
    return {"id": period.id, "label": period.label, "status": period.status.value}
