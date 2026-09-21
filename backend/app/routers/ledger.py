from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.models import Member, Statement
from app.schemas import BalancesOut, StatementOut
from app.services import bill as bill_svc
from app.services import ledger as ledger_svc

router = APIRouter(prefix="/api", tags=["ledger"])


@router.get("/balances", response_model=BalancesOut)
def get_balances(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """每个人的余额。正数＝别人欠他。合计恒为 0。"""
    return BalancesOut(balances={str(k): v for k, v in ledger_svc.balances(session).items()})


@router.get("/bill")
def current_bill(session: Session = Depends(get_session), _: Member = Depends(current_member)) -> dict:
    """当前这张**还没出**的草稿账单：上次出账之后记的所有账。"""
    return bill_svc.build_bill(session, None)


@router.get("/monthly")
def monthly(
    statement_id: int | None = None,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
) -> dict:
    """固定费。不传 statement_id ＝ 当前草稿，没录的给上次金额当灰色参考（不是预填值）。

    传了就是翻一张出过的账单：只列那张单子上真有的几项。
    """
    st = None
    if statement_id is not None:
        st = session.get(Statement, statement_id)
        if st is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "账单不存在")
    return bill_svc.monthly_rows(session, st)


@router.post("/monthly/carry")
def carry_monthly(
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> dict:
    """把「和上期一样」的固定费按上期金额记进当前草稿。

    只动明确开了那个开关的项；已经录过的、以及**本期手动删掉的**一律不碰。

    返回 `{"created": [...], "failed": [...]}`。两份都要给出去：
    自动记的钱必须让人看见（这是那个开关唯一的出口），而搬不过来的那几项
    同样必须让人看见 —— 否则「自动记账已经停了」这件事没有任何人会知道。
    """
    return bill_svc.carry_same_as_last(session, actor_id=member.id)


@router.get("/statements", response_model=list[StatementOut])
def list_statements(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """出过的账单，新的在前。带上金额和结清状态 —— 列表页每行都要显示。"""
    rows = list(session.exec(select(Statement).order_by(Statement.cut_at.desc())))
    return [
        StatementOut(
            **st.model_dump(),
            total_expense=bill_svc.build_total_expense(session, st),
            settled=bool(bill_svc.settlement_progress(session, st)["settled"]),
        )
        for st in rows
    ]


@router.get("/statements/{statement_id}/bill")
def statement_bill(
    statement_id: int,
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
) -> dict:
    """某张出过的账单。**实时重算**，并附上「出账后有没有被改过」。

    不返回冻结快照本身：当初那张在 `snapshot_json` 里留着（用于举证），
    但页面上要看的是现在的真实情况，两者不一致时由 `edited_after_cut` 点出来。
    """
    st = session.get(Statement, statement_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账单不存在")
    return bill_svc.build_bill(session, st)


@router.post("/statements", response_model=StatementOut, status_code=status.HTTP_201_CREATED)
def cut_statement(
    include_monthly: bool = True,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    """出账单：把这一刻之前所有没出账的账目归到一张单子上，冻结快照。

    **不锁定**任何东西 —— 余额全局累计，事后改了也不会算错钱，
    只是下一张账单会把「这张出账后被改过」标出来。
    """
    st = bill_svc.cut_statement(session, actor_id=member.id, include_monthly=include_monthly)
    return st
