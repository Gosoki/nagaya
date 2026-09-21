from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Member, Period
from app.schemas import BalancesOut, PeriodOut
from app.services import ledger as ledger_svc

router = APIRouter(prefix="/api", tags=["ledger"])


@router.get("/balances", response_model=BalancesOut)
def get_balances(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """每个人的余额。正数＝别人欠他。合计恒为 0。"""
    return BalancesOut(balances={str(k): v for k, v in ledger_svc.balances(session).items()})


@router.get("/periods", response_model=list[PeriodOut])
def list_periods(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    return list(session.exec(select(Period).order_by(Period.start_date.desc())))
