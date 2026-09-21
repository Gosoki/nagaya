"""当前草稿账单上的「固定费」回归。

要钉死的一条：**上次的金额只能是灰色参考（hint），绝不能变成本期的值（amount）。**
一旦它变成真值，某个月忘了改就会带着上月的电费把账单发出去，而且谁都看不出来。
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session

from app.models import Category, EntryKind
from app.services.bill import carry_same_as_last, cut_statement, monthly_rows
from app.services.ledger import create_entry, delete_entry

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


def rows_by_name(session: Session) -> dict[str, dict]:
    return {r["name"]: r for r in monthly_rows(session)["rows"]}


def test_only_monthly_unarchived_show_up(session, members) -> None:
    cats(session)
    assert list(rows_by_name(session)) == ["家賃", "電気", "水道"]


def test_unrecorded_rows_carry_hint_not_value(session, members) -> None:
    """上次的金额只能出现在 hint 里。amount 必须是 None。"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)        # 上一张出掉

    rows = rows_by_name(session)
    assert rows["電気"]["amount"] is None, "上次的金额被当成本期的值了"
    assert rows["電気"]["entry_id"] is None
    assert rows["電気"]["hint"] == 8_700
    assert rows["水道"]["hint"] is None           # 从来没录过，连参考都没有


def test_entries_in_the_current_draft_are_real_values(session, members) -> None:
    a, *_ = members
    c = cats(session)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_100, payer_id=a.id, category_id=c["電気"].id)
    rows = rows_by_name(session)
    assert rows["電気"]["amount"] == 9_100
    assert rows["電気"]["entry_id"] == e.id
    assert rows["電気"]["version"] == e.version   # 改它要带乐观锁


def test_hint_looks_back_past_statements_without_that_item(session, members) -> None:
    """水费两个月一收，上一张单子本来就没有它 —— 要按分类往回找。"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 7, 10),
                 amount=12_000, payer_id=a.id, category_id=c["水道"].id)
    cut_statement(session, actor_id=a.id)                       # 7 月那张
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)                       # 8 月那张（没有水费）

    rows = rows_by_name(session)
    assert rows["水道"]["hint"] == 12_000
    assert rows["電気"]["hint"] == 8_700


def test_deleted_entries_do_not_become_hints(session, members) -> None:
    a, *_ = members
    c = cats(session)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    delete_entry(session, e, actor_id=a.id)      # 出账前删掉
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=1, payer_id=a.id, category_id=c["水道"].id)
    cut_statement(session, actor_id=a.id)
    assert rows_by_name(session)["電気"]["hint"] is None


def test_rule_falls_back_to_category_default(session, members) -> None:
    a, b, c_ = members
    c = cats(session)
    c["家賃"].default_rule_json = {
        "mode": "exact",
        "exact": {str(a.id): 45_000, str(b.id): 40_000, str(c_.id): 35_000},
    }
    session.add(c["家賃"])
    session.commit()
    assert rows_by_name(session)["家賃"]["rule"]["mode"] == "exact"


def test_duplicate_entries_in_one_category_are_reported(session, members) -> None:
    """同一分类本期有两笔时必须说出来。

    面板一行只显示得下一笔，账单却是两笔都算。不提示的话，用户看到
    「家賃 170,000」，完全不知道总额里还有一笔 120,000。
    """
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    rows = rows_by_name(session)
    assert rows["家賃"]["entry_count"] == 1

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=170_000, payer_id=a.id, category_id=c["家賃"].id)
    rows = rows_by_name(session)
    assert rows["家賃"]["entry_count"] == 2, "重复没被报出来"
    assert rows["家賃"]["amount"] == 170_000          # 面板只显示得下最后一笔


def test_monthly_rows_of_a_past_statement_only_lists_what_is_on_it(session, members) -> None:
    """翻一张出过的账单，只列它真有的那几项。

    空行会诱人往里填，而填出来的是**新账目**，落进当前草稿，根本不会进这张单子。
    """
    from app.services.bill import carry_same_as_last, cut_statement, monthly_rows

    a, *_ = members
    rent = Category(name="家賃", monthly=True, display_order=0)
    water = Category(name="水道", monthly=True, display_order=1)
    session.add(rent)
    session.add(water)
    session.commit()
    session.refresh(rent)
    session.refresh(water)

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 9, 10),
                 amount=120_000, payer_id=a.id, category_id=rent.id)
    st = cut_statement(session, actor_id=a.id)

    names = [r["name"] for r in monthly_rows(session, st)["rows"]]
    assert names == ["家賃"]                       # 水道 这期没有，就不该出现

    # 当前草稿仍然两项都列（没录的那项给灰色参考值）
    assert [r["name"] for r in monthly_rows(session)["rows"]] == ["家賃", "水道"]


def test_archived_category_still_shows_on_old_bills(session: Session, members) -> None:
    """归档一个固定项之后，**旧账单上它那一行还得在**。

    那张单子上真有这笔钱、合计里也算着它。只按「现在还没归档」过滤的话，
    旧账单会少一行而总额不变 —— 看上去就是「这几项加不出总数」。
    当前草稿相反：归档就是「以后不用填了」，草稿里不该再给它留空位。
    """
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=120_000,
                 payer_id=a.id, category_id=c["家賃"].id)
    st = cut_statement(session, actor_id=a.id)

    c["家賃"].archived = True
    session.add(c["家賃"])
    session.commit()

    old = {r["name"] for r in monthly_rows(session, st)["rows"]}
    assert "家賃" in old, "旧账单上那一行不能因为归档就消失"
    draft = {r["name"] for r in monthly_rows(session)["rows"]}
    assert "家賃" not in draft, "草稿里归档的项不该再占位置"


def test_monthly_rows_carry_the_standing_payer(session: Session, members) -> None:
    """每项固定费默认谁垫，要跟着分类走。

    不定这个的话，面板上就是「谁填的算谁」：别人刷的卡被随手填进去，
    账本当场错一整笔房租的钱，而屏幕上一点提示都没有。
    """
    a, b, _ = members
    c = cats(session)
    c["家賃"].default_payer_id = a.id
    c["電気"].default_payer_id = b.id
    session.add(c["家賃"]); session.add(c["電気"]); session.commit()

    by_name = {r["name"]: r for r in monthly_rows(session)["rows"]}
    assert by_name["家賃"]["default_payer_id"] == a.id
    assert by_name["電気"]["default_payer_id"] == b.id
    assert by_name["水道"]["default_payer_id"] is None, "没定的就留空，由前端回退到全局设置"


def test_carry_only_touches_items_that_opted_in(session: Session, members) -> None:
    """「和上期一样」只搬明确开了开关的那几项。

    这条规矩的另一半是**默认不搬**：电费燃气每期都不一样，自动按上期记上，
    就等于「某个月忘了改，带着上月的电费把账单发出去」—— 那正是灰色占位
    当初要防的事。
    """
    a, *_ = members
    c = cats(session)
    for name, amount in [("家賃", 120_000), ("電気", 8_000)]:
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=amount, payer_id=a.id, category_id=c[name].id)
    cut_statement(session, actor_id=a.id)

    c["家賃"].same_as_last = True          # 房租每期一样，开
    c["家賃"].default_payer_id = a.id
    session.add(c["家賃"])
    session.commit()

    made = carry_same_as_last(session, actor_id=a.id)
    assert [m["name"] for m in made] == ["家賃"]
    assert made[0]["amount"] == 120_000
    rows = {r["name"]: r for r in monthly_rows(session)["rows"]}
    assert rows["家賃"]["amount"] == 120_000, "搬过来的是真值"
    assert rows["電気"]["amount"] is None, "没开开关的一分都不许自动记"
    assert rows["電気"]["hint"] == 8_000, "它继续只给灰色参考"

    # 再跑一次不会重复记
    assert carry_same_as_last(session, actor_id=a.id) == []


def test_carry_skips_items_that_never_had_an_amount(session: Session, members) -> None:
    """从来没出过账的项没有「上期」可抄，跳过 —— 不能凭空记一笔 0 元。"""
    a, *_ = members
    c = cats(session)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    session.commit()
    assert carry_same_as_last(session, actor_id=a.id) == []
