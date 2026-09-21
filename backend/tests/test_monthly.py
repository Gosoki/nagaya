"""账单页「本期固定费」回归。

这块的核心风险有两个，两条都必须钉死：
  1. 在 10 月填 9 月账单时，录进去的账不能落到 10 月期去
  2. 上期金额只能是**灰色参考**，不能变成预填的真值
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.models import Category, EntryKind
from app.services.bill import default_date_for, monthly_rows
from app.services.ledger import create_entry, get_or_create_period

AUG = dt.date(2026, 8, 10)
SEP = dt.date(2026, 9, 10)


def cats(session: Session) -> dict[str, Category]:
    rows = [
        Category(name="家賃", monthly=True, display_order=0),
        Category(name="電気", monthly=True, display_order=1),
        Category(name="水道", monthly=True, display_order=2),
        Category(name="日用品", monthly=False, display_order=3),
        Category(name="旧契約", monthly=True, archived=True, display_order=4),
    ]
    for c in rows:
        session.add(c)
    session.commit()
    for c in rows:
        session.refresh(c)
    return {c.name: c for c in rows}


def test_only_monthly_unarchived_categories_show_up(session, members) -> None:
    c = cats(session)
    rows = monthly_rows(session, get_or_create_period(session, SEP))["rows"]
    assert [r["name"] for r in rows] == ["家賃", "電気", "水道"]
    assert "日用品" not in [r["name"] for r in rows]     # 日常的不在这块
    assert "旧契約" not in [r["name"] for r in rows]     # 归档的也不在
    assert c["家賃"].id == rows[0]["category_id"]


def test_unrecorded_rows_carry_hint_not_value(session, members) -> None:
    """上期金额只能出现在 hint 里。amount 必须是 None ——
    一旦它变成真值，某个月忘了改就会带着上月的电费把账单发出去。"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)

    rows = {r["name"]: r for r in monthly_rows(session, get_or_create_period(session, SEP))["rows"]}
    assert rows["電気"]["amount"] is None, "上期金额被当成本期的值了"
    assert rows["電気"]["entry_id"] is None
    assert rows["電気"]["hint"] == 8_700
    assert rows["水道"]["hint"] is None                   # 上期也没录过，连参考都没有


def test_recorded_rows_carry_real_value_and_version(session, members) -> None:
    a, *_ = members
    c = cats(session)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_100, payer_id=a.id, category_id=c["電気"].id)
    rows = {r["name"]: r for r in monthly_rows(session, get_or_create_period(session, SEP))["rows"]}
    assert rows["電気"]["amount"] == 9_100
    assert rows["電気"]["entry_id"] == e.id
    assert rows["電気"]["version"] == e.version           # 改它要带乐观锁


def test_default_date_always_lands_inside_the_period(session, members) -> None:
    """**最要命的一条**：在 10 月填 9 月账单，录进去的账必须留在 9 月期。

    assign_period() 按发生日归期，默认日期取「今天」就会把家賃甩到 10 月期，
    9 月账单上凭空少一笔，而且一声不吭。
    """
    period = get_or_create_period(session, SEP)
    d = default_date_for(period)
    assert period.start_date <= d <= period.end_date

    a, *_ = members
    c = cats(session)
    entry = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=d,
                         amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    assert entry.period_id == period.id


def test_hint_label_tells_where_it_came_from(session, members) -> None:
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    data = monthly_rows(session, get_or_create_period(session, SEP))
    rows = {r["name"]: r for r in data["rows"]}
    assert rows["電気"]["hint_label"] == "2026-08"
    assert data["label"] == "2026-09"


def test_hint_looks_back_past_empty_periods(session, members) -> None:
    """参考值要按分类回溯，不能只看上一期。

    水费两个月一收，上一期本来就没有它；中间还可能夹着账目被删光的空账期。
    只看上一期的话，该给参考的时候给不出来。
    """
    a, *_ = members
    c = cats(session)
    # 7 月记过水费，8 月没有（两个月一收），9 月应当还能看到 7 月那个数
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 7, 10),
                 amount=12_000, payer_id=a.id, category_id=c["水道"].id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)

    rows = {r["name"]: r for r in monthly_rows(session, get_or_create_period(session, SEP))["rows"]}
    assert rows["水道"]["hint"] == 12_000
    assert rows["水道"]["hint_label"] == "2026-07"


def test_deleted_entries_do_not_become_hints(session, members) -> None:
    """软删掉的账目不该再当参考值 —— 它已经不算数了。"""
    from app.services.ledger import delete_entry

    a, *_ = members
    c = cats(session)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    delete_entry(session, e, actor_id=a.id)
    rows = {r["name"]: r for r in monthly_rows(session, get_or_create_period(session, SEP))["rows"]}
    assert rows["電気"]["hint"] is None


def test_rule_falls_back_to_category_default(session, members) -> None:
    """没录过的行，分摊规则用分类默认值；录过的用那笔账自己的规则。"""
    a, b, c_ = members
    c = cats(session)
    c["家賃"].default_rule_json = {"mode": "exact",
                                   "exact": {str(a.id): 45_000, str(b.id): 40_000, str(c_.id): 35_000}}
    session.add(c["家賃"])
    session.commit()

    rows = {r["name"]: r for r in monthly_rows(session, get_or_create_period(session, SEP))["rows"]}
    assert rows["家賃"]["rule"]["mode"] == "exact"
