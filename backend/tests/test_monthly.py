"""当前草稿账单上的「固定费」回归。

要钉死的一条：**上期的金额只有开了「和上期一样」才会进来，而且进来就是黑字实数。**
没开开关的项，草稿里一个数字都不许出现 —— 参考值就摆在输入框那个位置，
长得跟亲手填的没两样，某个月忘了改就带着上月的电费把账单发出去了。没填按 0 结。
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session

from app.models import Category, EntryKind
from app.services.bill import carry_same_as_last, cut_statement, monthly_rows, unbilled
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


def test_unrecorded_rows_stay_empty(session, members) -> None:
    """没开「和上期一样」的项：上期出过多少都不许漏进这一期，连参考值都不给。"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)        # 上一张出掉

    rows = rows_by_name(session)
    assert rows["電気"]["amount"] is None, "上次的金额被当成本期的值了"
    assert rows["電気"]["entry_id"] is None
    # 整行里不能有任何一个字段捎着 8,700 回来 —— 前端拿它当 placeholder 就等于预填
    assert 8_700 not in rows["電気"].values()


def test_entries_in_the_current_draft_are_real_values(session, members) -> None:
    a, *_ = members
    c = cats(session)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_100, payer_id=a.id, category_id=c["電気"].id)
    rows = rows_by_name(session)
    assert rows["電気"]["amount"] == 9_100
    assert rows["電気"]["entry_id"] == e.id
    assert rows["電気"]["version"] == e.version   # 改它要带乐观锁


def test_carry_looks_back_past_statements_without_that_item(session, members) -> None:
    """水费两个月一收，上一张单子本来就没有它 —— 要按分类往回找。

    只看上一张的话，「和上期一样」在水费上永远搬不过来，而它恰恰是最该自动搬的那种。
    """
    a, *_ = members
    c = cats(session)
    c["水道"].same_as_last = True
    session.add(c["水道"])
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=dt.date(2026, 7, 10),
                 amount=12_000, payer_id=a.id, category_id=c["水道"].id)
    cut_statement(session, actor_id=a.id)                       # 7 月那张
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)                       # 8 月那张（没有水费）

    assert [m["amount"] for m in carry_same_as_last(session, actor_id=a.id)["created"]] == [12_000]


def test_deleted_entries_are_not_carried(session, members) -> None:
    """删掉的那笔不算「上期」—— 否则「和上期一样」会把一笔已经作废的钱抄回来。"""
    a, *_ = members
    c = cats(session)
    c["電気"].same_as_last = True
    session.add(c["電気"])
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=8_700, payer_id=a.id, category_id=c["電気"].id)
    delete_entry(session, e, actor_id=a.id)      # 出账前删掉
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=1, payer_id=a.id, category_id=c["水道"].id)
    cut_statement(session, actor_id=a.id)
    assert carry_same_as_last(session, actor_id=a.id)["created"] == []


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
    from app.services.bill import carry_same_as_last, cut_statement, monthly_rows, unbilled

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

    # 当前草稿仍然两项都列（没录的那项是个空框，出账时按 0 结）
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
    就等于「某个月忘了改，带着上月的电费把账单发出去」。
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

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["name"] for m in made] == ["家賃"]
    assert made[0]["amount"] == 120_000
    rows = {r["name"]: r for r in monthly_rows(session)["rows"]}
    assert rows["家賃"]["amount"] == 120_000, "搬过来的是真值"
    assert rows["電気"]["amount"] is None, "没开开关的一分都不许自动记"
    assert 8_000 not in rows["電気"].values(), "没开开关的，上期金额一点都不许漏过来"

    # 再跑一次不会重复记
    assert carry_same_as_last(session, actor_id=a.id)["created"] == []


def test_carry_skips_items_that_never_had_an_amount(session: Session, members) -> None:
    """从来没出过账的项没有「上期」可抄，跳过 —— 不能凭空记一笔 0 元。"""
    a, *_ = members
    c = cats(session)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    session.commit()
    assert carry_same_as_last(session, actor_id=a.id)["created"] == []


def test_carry_uses_the_global_default_payer_when_the_category_has_none(
    session: Session, members
) -> None:
    """分类上没定垫付人时要回退到全局设置，不能算「谁先打开账单页」头上。

    少了中间这一级的话，房租那 12 万会算到本期第一个点开账单页的人名下 ——
    两个人各错一整笔房租的钱，而通知里只说「已按上期记入 家賃 ¥120,000」，
    一个字都不提算谁的。
    """
    from app.services import settings as settings_svc

    a, b, _ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=b.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)

    c["家賃"].same_as_last = True          # 分类上**故意不设** default_payer_id
    session.add(c["家賃"])
    session.commit()
    settings_svc.set_(session, "default_payer_id", b.id)

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["name"] for m in made] == ["家賃"]
    entry = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    assert entry.payer_id == b.id, "垫付人该是全局设置里的那个人，不是点开页面的人"


def test_carry_survives_a_roommate_moving_out(session: Session, members) -> None:
    """有人搬走之后，「和上期一样」不许整条静默失效。

    分类的默认分摊是当年按那时候几个人写死的。有人填了 left_on 之后，
    expand() 拿「今天在籍的人」当参与人，发现规则里多出个不认识的 id 就抛
    unknown_member —— 原来这会让**整个循环**炸掉：排在前面的项已经 commit 进草稿，
    返回值随异常一起丢，接口 400，前端一个空 catch 吞掉。
    屏幕上那几行还是空框，用户照着空框再填一遍，同一分类当期就有了两笔。
    """
    a, b, c_ = members
    c = cats(session)
    for name, amount in [("家賃", 120_000), ("電気", 8_000)]:
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=amount, payer_id=a.id, category_id=c[name].id)
    cut_statement(session, actor_id=a.id)

    # 房租这条规则点名了三个人（按房间大小分），电费没有规则
    c["家賃"].same_as_last = True
    c["家賃"].default_rule_json = {
        "mode": "ratio", "equal_weight": 1,
        "adjustments": {str(a.id): 5_000, str(c_.id): -5_000},
    }
    c["電気"].same_as_last = True
    session.add(c["家賃"]); session.add(c["電気"])
    c_.left_on = dt.date(2026, 8, 31)                 # 第三个人搬走了
    session.add(c_)
    session.commit()

    out = carry_same_as_last(session, actor_id=a.id)
    assert {m["name"] for m in out["created"]} == {"家賃", "電気"}, out
    assert out["failed"] == []
    rows = rows_by_name(session)
    assert rows["家賃"]["amount"] == 120_000
    assert rows["電気"]["amount"] == 8_000
    # 搬走的人不该再被分摊
    entry = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    assert str(c_.id) not in entry.split_rule_json.get("adjustments", {})


def test_carry_does_not_resurrect_a_manually_deleted_row(session: Session, members) -> None:
    """本期手动删掉的那笔不许被搬回来 —— 否则每打开一次账单页复活一次，用户删不掉。"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    session.commit()

    assert len(carry_same_as_last(session, actor_id=a.id)["created"]) == 1
    made = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    delete_entry(session, made, actor_id=a.id)          # 这个月没有房租，删掉

    assert carry_same_as_last(session, actor_id=a.id)["created"] == []
    assert rows_by_name(session)["家賃"]["amount"] is None


def test_carry_never_copies_an_income_amount(session: Session, members) -> None:
    """收入的金额是负数，抄过来以 expense 建账当场撞 bad_sign。

    那一项的「和上期一样」于是每次都失败，而用户只看到它一直空着。
    """
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.income, on=AUG,
                 amount=-3_000, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)
    c["電気"].same_as_last = True
    session.add(c["電気"])
    session.commit()
    out = carry_same_as_last(session, actor_id=a.id)
    assert out == {"created": [], "failed": []}


def test_archived_category_keeps_its_row_while_it_still_holds_money(
    session: Session, members
) -> None:
    """归档一个**本期已经录了钱**的固定费项：那一行必须留着。

    不留的话那笔钱还在账单的合计和每人应担里，面板上却一行都看不见 ——
    同一张草稿两个对不上的合计，而那笔钱既改不了也删不掉。
    """
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=5_500, payer_id=a.id, category_id=c["電気"].id)
    c["電気"].archived = True
    session.add(c["電気"])
    session.commit()

    rows = rows_by_name(session)
    assert rows["電気"]["amount"] == 5_500, "钱还在账单里，行就不能消失"
    assert monthly_rows(session)["total"] == 5_500
    # 没钱的归档项照旧不占位
    assert "水道" in rows and "旧契約" not in rows


def test_a_long_ago_deletion_does_not_disable_carry_forever(session: Session, members) -> None:
    """**上一期**删过一次，不该让这一项从此再也不自动记。

    软删的账目 statement_id 永远留着 NULL（出账只认没删的），所以「本期删过没有」
    不能只看 statement_id IS NULL —— 那样半年前删过一次的分类会从此永久失效，
    这是「删一次复活一次」的反面，同样是静默的。判据要按**上次出账那一刻**卡。
    """
    a, *_ = members
    c = cats(session)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)                    # 上上期

    # 上一期：搬过来又删掉了（那个月真的没有房租）
    assert len(carry_same_as_last(session, actor_id=a.id)["created"]) == 1
    dropped = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    delete_entry(session, dropped, actor_id=a.id)
    assert carry_same_as_last(session, actor_id=a.id)["created"] == []

    # 这一期：又该自动记了
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1, payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)
    assert [m["name"] for m in carry_same_as_last(session, actor_id=a.id)["created"]] == ["家賃"]
