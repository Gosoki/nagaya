from __future__ import annotations
import datetime as dt
from sqlmodel import Session
from app.models import Category, EntryKind, now_utc
from app.services.bill import build_bill, cut_statement, monthly_rows, entries_of
from app.services.ledger import create_entry, update_entry, balances

SEP = dt.date(2026, 9, 10)
OCT = dt.date(2026, 10, 10)

def row_of(bill, mid):
    return next(r for r in bill["members"] if r["member_id"] == mid)


def test_probe_opening_drift(session: Session, members):
    a, b, c = members
    e1 = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                      amount=30_000, payer_id=a.id)
    st1 = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=OCT,
                 amount=3_000, payer_id=b.id)
    st2 = cut_statement(session, actor_id=a.id)

    before = build_bill(session, st2)
    print("ST2 before:", [(r["member_id"], r["opening"], r["closing"]) for r in before["members"]])
    print("ST2 transfers before:", before["transfers"], "edited:", before["edited_after_cut"])

    # 改 st1 里那一笔
    session.refresh(e1)
    update_entry(session, e1, actor_id=a.id, version=e1.version, fields={"amount_jpy": 60_000})

    after = build_bill(session, st2)
    print("ST2 after :", [(r["member_id"], r["opening"], r["closing"]) for r in after["members"]])
    print("ST2 transfers after :", after["transfers"], "edited:", after["edited_after_cut"])
    print("ST2 snapshot members:", st2.snapshot_json["members"])
    print("ST1 edited:", build_bill(session, st1)["edited_after_cut"])


def test_probe_covers_from_backdated(session: Session, members):
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    st1 = cut_statement(session, actor_id=a.id)
    # 出账之后补录一笔很久以前的账
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 8, 1),
                 amount=2_000, payer_id=a.id)
    draft = build_bill(session, None)
    print("draft covers:", draft["covers_from"], "->", draft["covers_to"])
    st2 = cut_statement(session, actor_id=a.id)
    print("st2 covers:", st2.covers_from, "->", st2.covers_to)
    b2 = build_bill(session, st2)
    print("st2 bill covers:", b2["covers_from"], "->", b2["covers_to"])


def test_probe_prepay_marks_settled(session: Session, members):
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    bill = build_bill(session, st)
    print("plan:", bill["transfers"])
    # B 谁也没结上一期，只是提前给 A 打了下个月的房租预付
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=dt.date(2026, 10, 1),
                 amount=40_000, payer_id=b.id, to_member_id=a.id, title="下月房租预付")
    after = build_bill(session, st)
    print("settled_transfers:", after["settled_transfers"], "settled:", after["settled"])


def test_probe_archived_monthly_category(session: Session, members):
    a, *_ = members
    water = Category(name="水费", monthly=True)
    session.add(water)
    session.commit()
    session.refresh(water)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=11_800, payer_id=a.id, category_id=water.id)
    print("draft rows before archive:", monthly_rows(session, None)["rows"])
    water.archived = True
    session.add(water)
    session.commit()
    print("draft rows after archive:", monthly_rows(session, None)["rows"])
    print("bill total_expense:", build_bill(session, None)["total_expense"])
