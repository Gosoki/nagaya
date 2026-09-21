"""月度账单回归 —— SPEC F6：期初结转 / 赊账结转 / 关账锁定。"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import Session, select

from app.models import EntryKind, PeriodStatus
from app.services import settings as settings_svc
from app.services.bill import build_bill, close_period, reopen_period
from app.services.ledger import LedgerError, balances, create_entry, get_or_create_period

SEP = dt.date(2026, 9, 10)
OCT = dt.date(2026, 10, 10)


def row_of(bill: dict, member_id: int) -> dict:
    return next(r for r in bill["members"] if r["member_id"] == member_id)


def test_bill_breaks_down_the_period(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, title="家賃")
    period = get_or_create_period(session, SEP)
    bill = build_bill(session, period)

    assert bill["total_expense"] == 120_000
    assert bill["period"]["label"] == "2026-09"
    assert row_of(bill, a.id) == {
        "member_id": a.id, "opening": 0, "owed": 40_000, "paid": 120_000,
        "transferred_out": 0, "transferred_in": 0, "closing": 80_000,
    }
    assert row_of(bill, b.id)["closing"] == -40_000
    assert sum(r["closing"] for r in bill["members"]) == 0


def test_transfer_plan_zeroes_everyone(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    bill = build_bill(session, get_or_create_period(session, SEP))
    assert len(bill["transfers"]) == 2                    # 3 个人最多 2 笔
    assert all(t["to_id"] == a.id for t in bill["transfers"])
    assert sum(t["amount"] for t in bill["transfers"]) == 80_000


def test_settlement_shows_as_transferred_not_as_expense(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=dt.date(2026, 10, 15),
                 amount=40_000, payer_id=b.id, to_member_id=a.id)

    bill = build_bill(session, get_or_create_period(session, SEP))
    assert bill["total_expense"] == 120_000               # 转账不算支出
    assert row_of(bill, b.id)["transferred_out"] == 40_000
    assert row_of(bill, b.id)["closing"] == 0             # B 结清了
    assert row_of(bill, a.id)["closing"] == 40_000


def test_partial_payment_carries_forward(session: Session, members) -> None:
    """赊账：B 这个月先给 20000，差额自动结转 —— 不需要额外机制。"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=dt.date(2026, 10, 15),
                 amount=20_000, payer_id=b.id, to_member_id=a.id)

    sep_bill = build_bill(session, get_or_create_period(session, SEP))
    assert row_of(sep_bill, b.id)["closing"] == -20_000   # 还欠 20000

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT,
                 amount=30_000, payer_id=a.id)
    oct_bill = build_bill(session, get_or_create_period(session, OCT))
    assert row_of(oct_bill, b.id)["opening"] == -20_000   # 上期结转过来了
    assert row_of(oct_bill, b.id)["closing"] == -30_000   # 结转 20000 + 本期 10000


def test_prepayment_shows_as_credit(session: Session, members) -> None:
    """提前入账（D3）：先转了钱，账单上体现为已预付。"""
    a, b, c = members
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP,
                 amount=30_000, payer_id=b.id, to_member_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    bill = build_bill(session, get_or_create_period(session, SEP))
    assert row_of(bill, b.id)["transferred_out"] == 30_000
    assert row_of(bill, b.id)["closing"] == -10_000       # 应担 40000 − 已预付 30000


def test_water_bill_annotation_surfaces(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=12_000, payer_id=a.id, title="水道",
                 period_start=dt.date(2026, 7, 1), period_end=dt.date(2026, 8, 31))
    bill = build_bill(session, get_or_create_period(session, SEP))
    assert len(bill["covers"]) == 1
    assert bill["covers"][0]["period_start"] == "2026-07-01"


def test_pairwise_mode_keeps_original_creditors(session: Session, members) -> None:
    a, b, c = members
    settings_svc.set_(session, "simplify_debts", False)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP,
                 amount=3_000, payer_id=b.id)
    bill = build_bill(session, get_or_create_period(session, SEP))
    assert bill["simplified"] is False
    assert all(t["amount"] > 0 for t in bill["transfers"])


def test_close_freezes_snapshot_and_locks_entries(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    period = get_or_create_period(session, SEP)
    close_period(session, period, actor_id=a.id)

    assert period.status == PeriodStatus.closed
    assert period.snapshot_json["total_expense"] == 9_000
    assert period.closed_at is not None

    with pytest.raises(LedgerError) as exc:
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=1_000, payer_id=a.id)
    assert exc.value.code == "period_closed"


def test_can_close_with_outstanding_balance(session: Session, members) -> None:
    """赊账也能关账 —— 差额结转，不是非要结清才准关。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    period = close_period(session, get_or_create_period(session, SEP), actor_id=a.id)
    assert period.status == PeriodStatus.closed
    assert sum(balances(session).values()) == 0


def test_reopen_keeps_snapshot(session: Session, members) -> None:
    """解锁后快照留着 —— 要能查出当初那张账单长什么样。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    period = get_or_create_period(session, SEP)
    close_period(session, period, actor_id=a.id)
    snapshot = period.snapshot_json
    reopen_period(session, period, actor_id=a.id)

    assert period.status == PeriodStatus.open
    assert period.snapshot_json == snapshot
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_000, payer_id=a.id)          # 解锁后能改了


def test_reclose_never_overwrites_the_first_snapshot(session: Session, members) -> None:
    """关账 → 解锁 → 补录 → 再关账：**原快照必须还在**。

    「发现漏录、解锁补一笔、再关账」是常规操作。要是每次关账都重写快照，
    室友照着旧账单转了钱、系统里的账单却已经变了，就再没有东西能还原当时那张 ——
    而这正是 snapshot_json 存在的唯一理由。
    """
    from app.models import AuditLog

    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=9_000, payer_id=a.id)
    period = get_or_create_period(session, SEP)
    close_period(session, period, actor_id=a.id)
    assert period.snapshot_json["total_expense"] == 9_000

    reopen_period(session, period, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=5_000, payer_id=a.id)          # 补录漏掉的那笔
    close_period(session, period, actor_id=a.id)

    assert period.snapshot_json["total_expense"] == 9_000, "当初发出去的那张账单被覆盖了"

    # 新版本没丢，进了审计日志，要查得到
    again = [l for l in session.exec(select(AuditLog)).all() if l.action == "close_period_again"]
    assert len(again) == 1
    assert again[0].before_json["total_expense"] == 9_000
    assert again[0].after_json["total_expense"] == 14_000


def test_covers_only_annotates_cross_period_entries(session: Session, members) -> None:
    """账单上那句「含…」只留真正跨期的。

    等每一行都能顺手填计费期间之后，本期内的常规项会把这句话撑成一百多字，
    把「这个月为什么贵了一万二」这个唯一有用的信号淹掉。
    """
    a, *_ = members
    # 跨期：7〜8 月的水费，9 月收到账单 —— 该标
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=12_000, payer_id=a.id, title="水道",
                 period_start=dt.date(2026, 7, 1), period_end=dt.date(2026, 8, 31))
    # 本期内：9 月的电费标着 9 月的期间 —— 不该标，纯噪音
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=8_700, payer_id=a.id, title="電気",
                 period_start=dt.date(2026, 9, 1), period_end=dt.date(2026, 9, 30))

    bill = build_bill(session, get_or_create_period(session, SEP))
    assert [c["title"] for c in bill["covers"]] == ["水道"]


def test_covers_catches_one_sided_cross_period(session: Session, members) -> None:
    """只填了一头也算跨期（家賃前払い常见：只标「10月分」的起始日）。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 9, 30),
                 amount=120_000, payer_id=a.id, title="家賃",
                 period_start=dt.date(2026, 10, 1))
    bill = build_bill(session, get_or_create_period(session, dt.date(2026, 9, 30)))
    assert [c["title"] for c in bill["covers"]] == ["家賃"]
