from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select

from app.auth import current_member
from app.db import get_session
from app.errors import not_found
from app.models import Member, Statement, today_jst
from app.routers.entries import to_entry_out
from app.schemas import BalancesOut, CarryIn, ConfirmIn, EntryOut, StatementOut
from app.services import bill as bill_svc
from app.services import monthly as monthly_svc
from app.services import ledger as ledger_svc

router = APIRouter(prefix="/api", tags=["bill"])


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
    """固定费。不传 statement_id ＝ 当前草稿，没录的就是空的（上期金额不预填，也不给参考值）。

    传了就是翻一张出过的账单：只列那张单子上真有的几项。
    """
    st = None
    if statement_id is not None:
        st = session.get(Statement, statement_id)
        if st is None:
            raise not_found("statement")
    return monthly_svc.monthly_rows(session, st)


@router.post("/monthly/carry")
def carry_monthly(
    body: Optional[CarryIn] = None,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
) -> dict:
    """把「和上期一样」的固定费按上期金额记进当前草稿。

    **由人点，不再挂在页面挂载上**：固定费面板上的「按上期记上」，或者出账对话框里
    那个勾。打开账单页就记钱的话，「看一眼」和「记了几笔」分不开。
    会记哪几项、多少钱，面板先从 /monthly 的 carry_amount 看到。

    只动明确开了那个开关的项；已经录过的、以及**本期手动删掉的**一律不碰。

    返回 `{"created": [...], "failed": [...]}`。两份都要给出去：
    自动记的钱必须让人看见（这是那个开关唯一的出口），而搬不过来的那几项
    同样必须让人看见 —— 否则「自动记账已经停了」这件事没有任何人会知道。
    """
    # **不带清单就什么都不记。** 今天之前的前端是打开账单页就调这个接口、不带 body ——
    # 手机上缓存着旧版 PWA 的，一打开账单页照样会替人记钱，而这正是改成「人点才记」
    # 要去掉的事。现在的前端永远带着按钮上列出来的那几项
    if body is None or body.category_ids is None:
        return {"created": [], "failed": []}
    return monthly_svc.carry_same_as_last(session, actor_id=member.id, only=set(body.category_ids))


@router.get("/statements", response_model=list[StatementOut])
def list_statements(session: Session = Depends(get_session), _: Member = Depends(current_member)):
    """出过的账单，新的在前。带上金额和结清状态 —— 列表页每行都要显示。"""
    rows = list(session.exec(select(Statement).order_by(Statement.cut_at.desc())))
    # 批量拿金额和结清状态。逐张调的话 60 张就是 120 次查询，
    # 而这个接口每次打开账单页都要调
    totals = bill_svc.list_totals(session)
    settled = bill_svc.list_settled(session, rows)
    return [
        StatementOut(
            **st.model_dump(),
            total_expense=totals.get(st.id, 0),
            settled=settled.get(st.id, False),
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
        raise not_found("statement")
    return bill_svc.build_bill(session, st)


@router.post("/bill/confirm", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def confirm_transfer(
    body: ConfirmIn,
    session: Session = Depends(get_session),
    member: Member = Depends(current_member),
):
    """账单上点「确认已完成」。和直接 POST 一笔转账的区别：先核对「此刻还差多少」，
    对不上（有人刚记过、或者对话框被连点）就 409，不重复记（见 bill.confirm_transfer）"""
    st = None
    if body.statement_id is not None:
        st = session.get(Statement, body.statement_id)
        if st is None:
            raise not_found("statement")
    entry = bill_svc.confirm_transfer(
        session,
        statement=st,
        from_id=body.from_id,
        to_id=body.to_id,
        amount=body.amount,
        expect_left=body.expect_left,
        on=body.date or today_jst(),
        actor_id=member.id,
    )
    return to_entry_out(session, entry)


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
