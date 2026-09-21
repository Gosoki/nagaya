"""账单回归 —— 按「点出账单那一刻」切。

核心性质：
  * 没出账的账目合起来就是当前草稿账单
  * 出账＝划线 + 冻结快照，**不锁定**任何东西
  * 事后改了已出账的账，钱不会算错（差额进下一张的「上期结转」），但改动要能看见
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import Session, select

from app.models import EntryKind, Statement
from app.services import settings as settings_svc
from app.services.bill import BillError, build_bill, cut_statement
from app.services.ledger import balances, create_entry, update_entry

SEP = dt.date(2026, 9, 10)
OCT = dt.date(2026, 10, 10)


def row_of(bill: dict, member_id: int) -> dict:
    return next(r for r in bill["members"] if r["member_id"] == member_id)


def test_draft_bill_is_everything_not_yet_billed(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, title="家賃")
    bill = build_bill(session, None)

    assert bill["is_draft"] is True
    assert bill["statement_id"] is None
    assert bill["total_expense"] == 120_000
    assert row_of(bill, a.id)["closing"] == 80_000
    assert sum(r["closing"] for r in bill["members"]) == 0


def test_cut_draws_the_line_at_that_moment(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)

    assert st.snapshot_json["total_expense"] == 9_000
    assert build_bill(session, None)["entry_count"] == 0     # 草稿清空了

    # 出账之后再记的，自动进下一张草稿
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT,
                 amount=5_000, payer_id=a.id)
    assert build_bill(session, None)["total_expense"] == 5_000
    assert build_bill(session, st)["total_expense"] == 9_000  # 那张不变


def test_cutting_nothing_is_refused(session: Session, members) -> None:
    with pytest.raises(BillError) as exc:
        cut_statement(session, actor_id=members[0].id)
    assert exc.value.code == "nothing_to_cut"


def test_previous_statement_carries_forward(session: Session, members) -> None:
    """赊账：上一张没结清的，原样变成下一张的「上期结转」。"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    cut_statement(session, actor_id=a.id)

    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=dt.date(2026, 10, 15),
                 amount=20_000, payer_id=b.id, to_member_id=a.id)      # 只还了一部分
    draft = build_bill(session, None)
    assert row_of(draft, b.id)["opening"] == -40_000
    assert row_of(draft, b.id)["transferred_out"] == 20_000
    assert row_of(draft, b.id)["closing"] == -20_000                    # 还欠 20000


def test_transfer_plan_zeroes_everyone(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    bill = build_bill(session, None)
    assert len(bill["transfers"]) == 2                       # 3 个人最多 2 笔
    assert all(t["to_id"] == a.id for t in bill["transfers"])
    assert sum(t["amount"] for t in bill["transfers"]) == 80_000


def test_income_and_prepayment_show_up(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP,
                 amount=30_000, payer_id=b.id, to_member_id=a.id)       # 提前入账
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.income, on=SEP,
                 amount=-3_000, payer_id=a.id, title="キャッシュバック")

    bill = build_bill(session, None)
    assert bill["total_income"] == -3_000
    assert row_of(bill, b.id)["transferred_out"] == 30_000
    assert sum(r["closing"] for r in bill["members"]) == 0


def test_editing_after_cut_is_allowed_and_visible(session: Session, members) -> None:
    """**不锁定，但要可见。**

    钱不会算错（余额全局累计），可要是下一张账单上冒出个「上期结转」没人解释得清，
    那就是另一种伤害。所以出账后被改过的账单必须自己说出来。
    """
    a, *_ = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    assert build_bill(session, st)["edited_after_cut"] is None

    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 13_000})

    flagged = build_bill(session, st)["edited_after_cut"]
    assert flagged is not None
    assert flagged["count"] == 1
    assert flagged["frozen_total"] == 9_000        # 当初发出去的那张
    assert flagged["live_total"] == 13_000         # 现在的真实情况
    assert sum(balances(session).values()) == 0    # 钱照样是平的


def test_snapshot_is_never_overwritten(session: Session, members) -> None:
    """快照存在的唯一理由就是「证明当初发给室友的那张长什么样」。"""
    a, *_ = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 13_000})
    session.refresh(st)
    assert st.snapshot_json["total_expense"] == 9_000


def test_covers_annotation(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=12_000, payer_id=a.id, title="水道",
                 period_start=dt.date(2026, 7, 1), period_end=dt.date(2026, 8, 31))
    bill = build_bill(session, None)
    assert [c["title"] for c in bill["covers"]] == ["水道"]


def test_pairwise_mode(session: Session, members) -> None:
    a, b, c = members
    settings_svc.set_(session, "simplify_debts", False)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=9_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=b.id)
    bill = build_bill(session, None)
    assert bill["simplified"] is False
    assert all(t["amount"] > 0 for t in bill["transfers"])


def test_statements_are_ordered_and_labelled(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    first = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT, amount=2_000, payer_id=a.id)
    second = cut_statement(session, actor_id=a.id)

    rows = list(session.exec(select(Statement).order_by(Statement.cut_at)))
    assert [r.id for r in rows] == [first.id, second.id]
    assert first.covers_from == SEP and first.covers_to == SEP
    assert second.covers_from == OCT
    assert "出账" in first.label
