"""当前草稿账单上的「固定费」回归。

要钉死的一条：**上期的金额只有开了「和上期一样」才会进来，而且进来就是黑字实数。**
没开开关的项，草稿里一个数字都不许出现 —— 参考值就摆在输入框那个位置，
长得跟亲手填的没两样，某个月忘了改就带着上月的电费把账单发出去了。没填按 0 结。
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlmodel import Session, select

from app.models import Category, Entry, EntryKind, EntryShare, Member
from app.services.bill import cut_statement, unbilled
from app.services.ledger import create_entry, delete_entry
from app.services.monthly import carry_same_as_last, monthly_rows

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


def test_carry_copies_last_periods_payer_not_the_global_default(
    session: Session, members
) -> None:
    """分类上没定垫付人时，照上期**那一笔的垫付人**（第四轮 §B-1）——
    不是全局「默认垫付人」，也不是点按钮的那个人。

    原来这条叫「回退到全局默认垫付人」，可上期付款人和全局设置恰好是同一个人，
    断言恒成立；代码从来不读全局设置。名字留着的话，迟早有人「修」代码去对齐它，
    房租那 12 万就换了人垫。三个人在这里故意各不相同。
    """
    from app.services import settings as settings_svc

    a, b, c_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=b.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)

    c["家賃"].same_as_last = True          # 分类上**故意不设** default_payer_id
    session.add(c["家賃"])
    session.commit()
    settings_svc.set_(session, "default_payer_id", c_.id)

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["name"] for m in made] == ["家賃"]
    entry = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    assert entry.payer_id == b.id, "垫付人该是上期那一笔的人，不是全局设置、也不是点按钮的人"


def test_carry_prefers_the_category_default_payer(session: Session, members) -> None:
    """分类上明写了默认垫付人的，它优先于上期那一笔：「从这个月起房租由 Kan 付」
    只改了分类，照上期就该按 Kan 记。这一级原来没人钉 —— 去掉它全套照样绿"""
    from app.services import settings as settings_svc

    a, b, c_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=b.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)
    c["家賃"].same_as_last = True
    c["家賃"].default_payer_id = c_.id
    session.add(c["家賃"])
    session.commit()
    settings_svc.set_(session, "default_payer_id", a.id)

    carry_same_as_last(session, actor_id=a.id)
    entry = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    assert entry.payer_id == c_.id


def test_carry_survives_a_roommate_moving_out(session: Session, members) -> None:
    """有人搬走之后，「和上期一样」不许整条静默失效 —— 也不许替人重分他那一份。

    原来的坑：分类的默认分摊是当年按那时候几个人写死的，有人填了 left_on 之后，
    expand() 拿「今天在籍的人」当参与人，发现规则里多出个不认识的 id 就抛
    unknown_member，**整个循环**炸掉：排在前面的项已经 commit 进草稿，
    返回值随异常一起丢，接口 400，前端一个空 catch 吞掉。

    后来改成剔掉搬走的人（连他的调整额）照记：上期 45,000/40,000/35,000，
    C 一走默默变成 62,500/57,500，按钮和通知只报「房租 ¥120,000，按上期」——
    月中搬走的人那期该不该担、调整额怎么改，全被程序替人定了（审计 #2）。
    现在：上期给他记过钱的项**拦下来、说出来**（rule_stale），本来就不算他（权重 0）的项照抄；
    人手填一期之后，下一期照抄新的那一笔。
    """
    a, b, c_ = members
    c = cats(session)
    # 房租：三个人都分，C 还少担 5,000。电费：本来就只算 A、B（C 那一行是 0）
    rent_rule = {"mode": "ratio", "equal_weight": 1,
                 "adjustments": {str(a.id): 5_000, str(c_.id): -5_000}}
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=a.id, category_id=c["家賃"].id, category_rule=rent_rule)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=8_000,
                 payer_id=a.id, category_id=c["電気"].id,
                 rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 0}})
    cut_statement(session, actor_id=a.id)

    c["家賃"].same_as_last = True
    c["電気"].same_as_last = True
    session.add(c["家賃"]); session.add(c["電気"])
    c_.left_on = dt.date(2026, 8, 31)                 # 第三个人搬走了
    session.add(c_)
    session.commit()

    rows = rows_by_name(session)
    assert rows["家賃"]["carry_amount"] is None and rows["家賃"]["carry_blocked"] == "rule_stale"
    # 手填的起步分法照旧从上期抄（剔掉 C）—— 拦的只是「不经人手就记」那一下
    assert rows["家賃"]["rule"]["adjustments"] == {str(a.id): 5_000}
    assert rows["電気"]["carry_amount"] == 8_000

    out = carry_same_as_last(session, actor_id=a.id)       # 没炸，两项各有交代
    assert [m["name"] for m in out["created"]] == ["電気"], out
    assert [(f["name"], f["reason"]) for f in out["failed"]] == [("家賃", "rule_stale")]
    elec = next(e for e in unbilled(session) if e.category_id == c["電気"].id)
    shares = dict(session.exec(
        select(EntryShare.member_id, EntryShare.amount_jpy).where(EntryShare.entry_id == elec.id)
    ).all())
    assert shares == {a.id: 4_000, b.id: 4_000}, "本来就不算 C 的那一项，剔掉他一分钱不变"
    assert rows_by_name(session)["家賃"]["amount"] is None, "宁可空着让人填，也不替人重分"

    # 人手填这一期的房租（两个人怎么分由人定），出账；下一期照抄新的那一笔
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=110_000,
                 payer_id=a.id, category_id=c["家賃"].id,
                 rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1}})
    cut_statement(session, actor_id=a.id)
    again = carry_same_as_last(session, actor_id=a.id)
    assert {m["name"]: m["amount"] for m in again["created"]} == {"家賃": 110_000, "電気": 8_000}, again
    assert again["failed"] == []


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


def test_an_exact_rule_cannot_be_pruned_and_says_so(session: Session, members) -> None:
    """`exact` 模式点名了搬走的人时，剔掉他之后**和必然对不上总额** —— 那就该失败。

    不能替用户把剩下几个人的固定额按比例放大：45,000/40,000/35,000 是按房间大小
    谈好的数，凭空改成别的数字比不记账更糟。所以这一项进 failed 列表、
    面板上那行留空、界面弹一条 warning 说清是哪几项 —— 让人自己去把规则重定。
    """
    a, b, c_ = members
    cat = cats(session)["家賃"]
    cat.same_as_last = True
    cat.default_rule_json = {
        "mode": "exact",
        "exact": {str(a.id): 45_000, str(b.id): 40_000, str(c_.id): 35_000},
    }
    session.add(cat)
    # 和接口一样把分类规则带上（routers/entries.py 的 _category_rule）：
    # 上期那一笔存下的就是这条 exact 规则，carry 照它抄
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=cat.id,
                 category_rule=cat.default_rule_json)
    cut_statement(session, actor_id=a.id)
    c_.left_on = dt.date(2026, 8, 31)
    session.add(c_)
    session.commit()

    out = carry_same_as_last(session, actor_id=a.id)
    assert out["created"] == []
    assert [f["name"] for f in out["failed"]] == ["家賃"]
    assert out["failed"][0]["reason"] == "rule_stale"
    row = rows_by_name(session)["家賃"]
    assert row["amount"] is None, "宁可空着，也不许填一个编出来的数"
    # 面板上那行也不该挂着一个点了必失败的「照上期」，而是写明「人变了，要重填」
    assert row["carry_amount"] is None and row["carry_blocked"] == "rule_stale"


def test_deleted_this_period_stays_deleted_across_a_small_cut(session, members) -> None:
    """本期手动删掉的房租，中间出一张「不含固定费」的小账之后，不许被自动记账复活。

    原来 carry 拿「最近一张单子」当本期的下界 —— 那张小账不结固定费，
    它之前删掉的房租就不算「本期删的」了（审计 flow-8 / integrity-4）。
    """
    a, *_ = members
    c = cats(session)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    cut_statement(session, actor_id=a.id)                       # 8 月：结了房租

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["amount"] for m in made] == [120_000]
    rent = next(e for e in unbilled(session) if e.category_id == c["家賃"].id)
    delete_entry(session, rent, actor_id=a.id)                  # 这期不交（比如预付过了）

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=500, payer_id=a.id, category_id=c["日用品"].id)
    cut_statement(session, actor_id=a.id, include_monthly=False)  # 中途结一次日常小账

    assert carry_same_as_last(session, actor_id=a.id)["created"] == []


def test_carry_copies_last_periods_split_and_payer(session: Session, members) -> None:
    """「和上期一样」照抄上期那一笔的分摊和垫付人（审计 money-1 critical / money-2）。

    房租怎么分，界面上只能在固定费面板里逐笔改 —— 改的是那一笔、不是分类。
    原来 carry 用分类默认规则，「A 多担 5,000」下一期被悄悄打回均分；
    垫付人回退到「谁触发了 carry」（那时候是打开账单页就触发），房租就记成了看页面的那个人垫的。
    """
    a, b, c_ = members
    cat = cats(session)["家賃"]
    cat.same_as_last = True
    session.add(cat)
    create_entry(
        session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000, payer_id=a.id,
        category_id=cat.id,
        rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 1},
              "adjustments": {str(a.id): 5_000, str(c_.id): -5_000}},
    )
    cut_statement(session, actor_id=a.id)

    out = carry_same_as_last(session, actor_id=b.id)       # B 先打开的账单页
    assert [m["amount"] for m in out["created"]] == [120_000]
    rent = next(e for e in unbilled(session) if e.category_id == cat.id)
    assert rent.payer_id == a.id, "垫付人是上期那一笔的 A，不是打开页面的 B"
    from app.services.bill import _shares_of
    shares = _shares_of(session, [rent.id])[rent.id]
    assert shares == {a.id: 45_000, b.id: 40_000, c_.id: 35_000}


def test_carry_asks_when_someone_new_moved_in(session: Session, members) -> None:
    """上期那一笔点名了三个人，这期多了一个新室友 —— 不替人猜怎么分，报出来。"""
    from app.models import Member

    a, *_ = members
    cat = cats(session)["家賃"]
    cat.same_as_last = True
    session.add(cat)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id)
    session.add(Member(name="d", display_name="D", display_order=3, joined_on=dt.date(2026, 9, 1)))
    session.commit()

    out = carry_same_as_last(session, actor_id=a.id)
    assert out["created"] == []
    assert out["failed"][0]["reason"] == "rule_stale"


def test_unrecorded_row_starts_from_last_periods_payer_and_split(session: Session, members) -> None:
    """没开「和上期一样」、这期手填房租时，面板也从上期那一笔的垫付人和分摊起步 ——
    和 carry 同一个口径，否则每手填一次，分摊就被打回分类默认一次。金额照旧不预填。"""
    a, b, c_ = members
    cat = cats(session)["家賃"]
    rule = {"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 1},
            "adjustments": {str(a.id): 5_000, str(c_.id): -5_000}}
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=b.id, category_id=cat.id, rule=rule)
    cut_statement(session, actor_id=a.id)

    row = rows_by_name(session)["家賃"]
    assert row["amount"] is None
    assert row["last_payer_id"] == b.id
    assert row["rule"]["adjustments"] == {str(a.id): 5_000, str(c_.id): -5_000}


def test_the_panel_sees_what_carry_would_record_without_recording_it(session: Session, members) -> None:
    """「和上期一样」改成人点之后，面板得先看得到点下去会记什么 —— 而且光看不许记。"""
    a, *_ = members
    c = cats(session)
    for name, amount in [("家賃", 120_000), ("電気", 8_000)]:
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=amount, payer_id=a.id, category_id=c[name].id)
    cut_statement(session, actor_id=a.id)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    session.commit()

    rows = rows_by_name(session)
    assert rows["家賃"]["carry_amount"] == 120_000
    assert rows["家賃"]["carry_blocked"] is None
    assert rows["電気"]["carry_amount"] is None, "没开开关的不许出现在按钮上"
    assert rows["家賃"]["amount"] is None and unbilled(session) == [], "看一眼不许记钱"

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["amount"] for m in made] == [120_000]
    after = rows_by_name(session)
    assert after["家賃"]["carry_amount"] is None, "记过了，出账时就不该再替人记一遍"
    # 展开区那颗按钮按过了也还在（写「已照上期」），所以上期金额照给；没开开关的照旧一分不给
    assert after["家賃"]["last_amount"] == 120_000
    assert after["電気"]["last_amount"] is None


def test_carry_only_records_what_the_button_listed(session: Session, members) -> None:
    """点的那一刻有一行正在手填：它不在按钮上，就不许被记（手填的一存就是两笔）。"""
    a, *_ = members
    c = cats(session)
    for name in ("家賃", "水道"):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                     amount=50_000, payer_id=a.id, category_id=c[name].id)
        c[name].same_as_last = True
        session.add(c[name])
    session.commit()
    cut_statement(session, actor_id=a.id)

    made = carry_same_as_last(session, actor_id=a.id, only={c["家賃"].id})["created"]
    assert [m["name"] for m in made] == ["家賃"]
    assert rows_by_name(session)["水道"]["amount"] is None


def test_carry_endpoint_takes_an_optional_list(client, auth, session, members) -> None:
    c = cats(session)
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=50_000, payer_id=a.id, category_id=c["家賃"].id)
    c["家賃"].same_as_last = True
    session.add(c["家賃"])
    session.commit()
    cut_statement(session, actor_id=a.id)

    r = client.post("/api/monthly/carry", headers=auth, json={"category_ids": []})
    assert r.status_code == 200 and r.json()["created"] == [], "给了空列表就一项都不记"
    # 今天之前的旧版 PWA 打开账单页就调它、不带 body —— 不许再替人记钱
    r = client.post("/api/monthly/carry", headers=auth)
    assert r.status_code == 200 and r.json()["created"] == [], "不带清单就什么都不记"
    r = client.post("/api/monthly/carry", headers=auth, json={"category_ids": [c["家賃"].id]})
    assert [m["name"] for m in r.json()["created"]] == ["家賃"]


def test_an_issued_bill_still_lists_the_fixed_items_that_were_zero(session: Session, members) -> None:
    """出账时没填的固定费按 ¥0 结 —— 账单上也得照样列着，别出账前五行、出账后一行。"""
    from app.services.bill import billed_monthly_ids, build_bill

    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=120_000, payer_id=a.id, category_id=c["家賃"].id)
    st = cut_statement(session, actor_id=a.id)

    listed = build_bill(session, st)["monthly_ids"]
    assert listed == [c["家賃"].id, c["電気"].id, c["水道"].id], "没填的电费、水费也要列着"
    assert c["旧契約"].id not in listed, "归档了、这张上也没钱的不列"
    assert c["日用品"].id not in listed

    # 清单是出账那一刻的：之后再加一项固定费，这张旧账单上不许冒出来
    session.add(Category(name="ネット", monthly=True, display_order=9))
    session.commit()
    assert billed_monthly_ids(session, st) == listed

    # 没结固定费的小账：一项都不列
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=500, payer_id=a.id, category_id=c["日用品"].id)
    small = cut_statement(session, actor_id=a.id, include_monthly=False)
    assert build_bill(session, small)["monthly_ids"] == []
    assert build_bill(session, None)["monthly_ids"] is None, "草稿那页用的是面板，不给这个"


def test_two_people_opening_the_bill_page_at_once_do_not_double_the_rent(tmp_path) -> None:
    """群里一句「出账了」，三个人同时点开账单页 —— 房租不能记两笔。

    原来账单页一挂载就 POST /api/monthly/carry；现在改成人点按钮，两个人同时点、
    或者一个人连点照样是这条路。
    「读一遍本期已经有哪几项 → 把缺的记上」中间隔着几十毫秒，两个请求都会在对方
    commit 之前读到「本期还没记房租」。面板一行只显示得下一笔，所以屏幕上金额是对的、
    合计是两倍 —— 用户得自己去账目列表里翻出那笔重复的删掉。

    用真文件库 + 两条连接：内存库那套 StaticPool 只有一条连接，会把这个race 盖住。
    """
    import threading

    from sqlmodel import SQLModel, create_engine

    from app.services import settings as settings_svc
    from app.services.settings import seed_settings

    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        settings_svc.set_(s, "backup_path", str(tmp_path / "backups"))
        a = Member(name="a", display_name="A", display_order=0, joined_on=dt.date(2026, 1, 1))
        s.add(a)
        s.commit()
        s.refresh(a)
        aid = a.id
        cat = Category(name="房租", monthly=True, same_as_last=True, default_payer_id=aid)
        s.add(cat)
        s.commit()
        s.refresh(cat)
        cid = cat.id
        create_entry(s, actor_id=aid, kind=EntryKind.expense, on=SEP,
                     amount=90_000, payer_id=aid, category_id=cid)
        cut_statement(s, actor_id=aid, label="上一期", on=SEP)

    gate = threading.Barrier(2)

    def go() -> None:
        with Session(engine) as s:
            gate.wait()
            carry_same_as_last(s, actor_id=aid)

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    with Session(engine) as s:
        draft = [e for e in unbilled(s) if e.category_id == cid]
    assert len(draft) == 1, f"本期房租记了 {len(draft)} 笔，当期账单凭空翻倍"


def test_fixing_an_old_bill_does_not_switch_this_months_carry_off(session: Session, members) -> None:
    """回头删掉一笔**已经出过账**的固定费，不该让本期的「和上期一样」停摆。

    已出账的账目软删之后 statement_id 还留着；「本期删掉的不碰」那一条只该认草稿里的。
    分不开的话：9 月初去把 8 月手滑多记的那笔房租删了 → 整个 9 月房租都不再自动记，
    而它既不进 created 也不进 failed，屏幕上一句提示都没有，出账时按 0 结。
    """
    a, *_ = members
    cat = Category(name="房租", monthly=True, same_as_last=True, default_payer_id=a.id)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    for _ in range(2):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=120_000, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, label="8 月", on=SEP)

    extra = session.exec(
        select(Entry).where(Entry.category_id == cat.id).order_by(Entry.id.desc())
    ).first()
    delete_entry(session, entry=extra, actor_id=a.id)

    out = carry_same_as_last(session, actor_id=a.id)
    assert [c["name"] for c in out["created"]] == ["房租"], out


def test_carry_refuses_to_pay_rent_with_a_roommate_who_moved_out(session: Session, members) -> None:
    """垫付人搬走了就别再替他垫 —— 账单会反过来叫留下的人给他转账。"""
    a, b, c_ = members
    cat = Category(name="房租", monthly=True, same_as_last=True, default_payer_id=c_.id)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=c_.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, label="上一期", on=SEP)

    c_.left_on = SEP - dt.timedelta(days=1)
    session.add(c_)
    session.commit()

    out = carry_same_as_last(session, actor_id=a.id)
    assert out["created"] == [], "搬走的人不该又垫了一次房租"
    assert [f["reason"] for f in out["failed"]] == ["payer_left"], out


def test_carry_follows_the_remainder_setting_of_today(session: Session, members) -> None:
    """「余数归谁」是全局设置，不是那一笔自己的安排：上期那笔存着当时的 payer，
    设置改成 order 之后照上期记的新账得按 order 分，不能一期一期沿用旧的"""
    from app.services import settings as settings_svc

    a, *_ = members
    rent = cats(session)["家賃"]
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG,
                 amount=10_000, payer_id=a.id, category_id=rent.id)
    cut_statement(session, actor_id=a.id)
    rent.same_as_last = True
    session.add(rent)
    session.commit()
    settings_svc.set_(session, "remainder_to", "order")

    assert [m["name"] for m in carry_same_as_last(session, actor_id=a.id)["created"]] == ["家賃"]
    entry = next(e for e in unbilled(session) if e.category_id == rent.id)
    assert entry.split_rule_json["remainder_to"] == "order"


# ------------------------------------------------ 上期同一项有好几笔（#6）


def _two_rents_last_period(session: Session, members, amounts: tuple[int, int]) -> Category:
    a, b, _ = members
    rent = cats(session)["家賃"]
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=amounts[0],
                 payer_id=a.id, category_id=rent.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=AUG, amount=amounts[1],
                 payer_id=b.id, category_id=rent.id)
    cut_statement(session, actor_id=a.id)
    return rent


@pytest.mark.parametrize("amounts", [(100_000, 20_000), (120_000, 120_000)])
def test_carry_refuses_to_pick_one_of_several_last_period_entries(
    session: Session, members, amounts: tuple[int, int]
) -> None:
    """上期那张单子上房租有两笔（两台手机同时填、出账时没清掉）：照上期挑哪一笔都是猜 ——
    按 id 挑的话 ¥120,000 的房租能被抄成 ¥20,000，垫付人也跟着换。也不许替人求和：
    最常见的是同额重复，求和就是房租翻倍。拦下来，把笔数和合计报给人。"""
    rent = _two_rents_last_period(session, members, amounts)
    rent.same_as_last = True
    session.add(rent)
    session.commit()

    row = rows_by_name(session)["家賃"]
    assert row["carry_amount"] is None and row["last_amount"] is None
    assert row["carry_blocked"] == "last_multi"
    assert row["carry_blocked_detail"] == {"count": 2, "total": sum(amounts)}
    assert row["last_payer_id"] is None, "垫付人也是从那一笔抄的 —— 同样是猜"
    out = carry_same_as_last(session, actor_id=members[0].id)
    assert out["created"] == []
    assert out["failed"] == [{"category_id": rent.id, "name": "家賃", "reason": "last_multi",
                              "detail": {"count": 2, "total": sum(amounts)}}]
    assert unbilled(session) == []


def test_several_entries_on_an_older_bill_do_not_block_an_item_whose_last_bill_had_one(
    session: Session, members
) -> None:
    """「上期那一笔所在的那张」只数那一张。水道上期（S2）只有一笔，S1 上它有两笔，而電気的上期
    正好是 S1 —— 两项的上期凑在一起查，S1 上水道那两笔不许算到水道头上"""
    a, *_ = members
    c = cats(session)
    water, elec = c["水道"], c["電気"]
    for cat in (water, elec):
        cat.same_as_last = True
        session.add(cat)
    session.commit()
    _period(session, a, {water.id: [5_000, 5_000], elec.id: [8_000]})      # S1
    _period(session, a, {water.id: [5_000]})                                 # S2

    rows = rows_by_name(session)
    assert rows["水道"]["carry_blocked"] is None and rows["水道"]["carry_amount"] == 5_000
    out = carry_same_as_last(session, actor_id=a.id)
    assert {m["name"]: m["amount"] for m in out["created"]} == {"水道": 5_000, "電気": 8_000}
    assert out["failed"] == []


def test_carry_stops_when_only_an_adjustment_charged_the_one_who_left(session: Session, members) -> None:
    """上期的规则里 C 的权重是 0，可调整额给他记了 5,000（他的车位）。C 搬走了：
    照抄的话剔掉他连同那 5,000，留下的两个人默默多担 —— 和权重不为 0 时一样，请人手填一期"""
    a, b, c_ = members
    rent = cats(session)["家賃"]
    rent.same_as_last = True
    session.add(rent)
    session.commit()
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=a.id, category_id=rent.id,
                 rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 0},
                       "adjustments": {str(c_.id): 5_000}})
    cut_statement(session, actor_id=a.id)
    c_.left_on = SEP
    session.add(c_)
    session.commit()

    assert rows_by_name(session)["家賃"]["carry_blocked"] == "rule_stale"
    out = carry_same_as_last(session, actor_id=a.id)
    assert out["created"] == [] and [f["reason"] for f in out["failed"]] == ["rule_stale"]


def test_cleaning_up_the_duplicate_brings_carry_back(session: Session, members) -> None:
    a, *_ = members
    rent = _two_rents_last_period(session, members, (120_000, 120_000))
    rent.same_as_last = True
    session.add(rent)
    session.commit()
    extra = session.exec(select(Entry).where(Entry.category_id == rent.id).order_by(Entry.id.desc())).first()
    delete_entry(session, extra, actor_id=a.id)
    assert rows_by_name(session)["家賃"]["carry_blocked"] is None
    assert [m["amount"] for m in carry_same_as_last(session, actor_id=a.id)["created"]] == [120_000]


def test_several_last_period_entries_never_leak_into_an_item_without_same_as_last(
    session: Session, members
) -> None:
    """没开「和上期一样」的项：笔数、合计一个字都不给（D21），起步的分摊和垫付人也不从那几笔里挑。"""
    a, b, c_ = members
    rent = _two_rents_last_period(session, members, (100_000, 20_000))
    row = rows_by_name(session)["家賃"]
    assert row["carry_blocked"] is None and row["carry_blocked_detail"] is None
    assert row["last_amount"] is None and row["last_payer_id"] is None
    assert row["rule"] == rent.default_rule_json
    assert 100_000 not in row.values() and 20_000 not in row.values() and 120_000 not in row.values()


# ---------------------------------------------- 照上期记成谁垫的（#18）/ 面板上谁垫的（#23）


def test_the_panel_and_carry_say_who_pays(session: Session, members) -> None:
    """按钮上、通知里只写「房租 ¥120,000」的话，记成了谁垫的没人看得见。
    面板上已录那一行是谁垫的，也从库里给，不再让前端从账单页的缓存里猜。"""
    a, b, _ = members
    c = cats(session)
    c["家賃"].same_as_last = True
    c["家賃"].default_payer_id = b.id
    session.add(c["家賃"])
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=a.id, category_id=c["家賃"].id)
    st = cut_statement(session, actor_id=a.id)
    elec = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=8_000,
                        payer_id=a.id, category_id=c["電気"].id)

    rows = rows_by_name(session)
    assert rows["家賃"]["carry_payer_id"] == b.id, "分类上定了常驻垫付人，照上期记给他"
    assert rows["家賃"]["payer_id"] is None
    assert rows["電気"]["payer_id"] == a.id and rows["電気"]["entry_id"] == elec.id
    assert rows["水道"]["carry_payer_id"] is None

    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert made == [{"category_id": c["家賃"].id, "name": "家賃", "amount": 120_000, "payer_id": b.id}]
    assert rows_by_name(session)["家賃"]["payer_id"] == b.id
    # 翻已出的账单也有
    assert [r["payer_id"] for r in monthly_rows(session, st)["rows"]] == [a.id]


# ------------------------------------------------- 规则没写到新室友（#14）


def test_a_rule_that_names_everyone_but_the_new_roommate_is_marked(session: Session, members) -> None:
    """分类规则点名写了三个人，第四个人搬进来之后在这一项上按 0 算 —— 只标出来，不替人补权重。"""
    from app.services import settings as settings_svc

    a, b, c_ = members
    c = cats(session)
    c["家賃"].default_rule_json = {"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 1}}
    session.add(c["家賃"])
    d = Member(name="d", display_name="D", display_order=3, joined_on=dt.date(2026, 9, 1))
    session.add(d)
    session.commit()

    rows = rows_by_name(session)
    assert rows["家賃"]["rule_missing_member_ids"] == [d.id]
    assert rows["電気"]["rule_missing_member_ids"] == [], "没定规则 → 全局均分，谁在籍算谁"
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=120_000,
                 payer_id=a.id, category_id=c["家賃"].id, category_rule=c["家賃"].default_rule_json)
    assert rows_by_name(session)["家賃"]["rule_missing_member_ids"] == [], "录过了就不是「起步」的事了"

    # 全局默认要是点了名，没定规则的每一项都一样
    settings_svc.set_(session, "default_rule", {"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1}})
    assert rows_by_name(session)["電気"]["rule_missing_member_ids"] == [c_.id, d.id]


# -------------------------------------------------- 两台手机同时出账（#5，照上期那一半）


def test_carry_with_a_stale_view_of_the_last_bill_records_nothing(client, auth, session, members) -> None:
    """B 手里的对话框还是出账前那一份：上期已经被 A 出掉了，再照上期记就是把房租记进**下一期**。"""
    a, *_ = members
    rent = cats(session)["家賃"]
    rent.same_as_last = True
    session.add(rent)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=a.id, category_id=rent.id)
    first = cut_statement(session, actor_id=a.id)

    seen = client.get("/api/bill", headers=auth).json()["prev_statement_id"]        # 两台手机都看到这张
    assert seen == first.id
    body = {"category_ids": [rent.id], "after_statement_id": seen}
    assert client.post("/api/monthly/carry", headers=auth, json=body).json()["created"]   # A 记上
    r = client.post(f"/api/statements?after_statement_id={seen}", headers=auth)
    assert r.status_code == 201                                                     # A 出账

    r = client.post("/api/monthly/carry", headers=auth, json=body)                  # B 才点
    assert r.status_code == 409 and r.json()["code"] == "bill_changed", r.text
    assert unbilled(session) == [], "下一期不许多出一笔房租"
    # 不带这个参数的旧前端照旧（面板上那颗「照上期」也不带）
    r = client.post("/api/monthly/carry", headers=auth, json={"category_ids": [rent.id]})
    assert [m["amount"] for m in r.json()["created"]] == [120_000]


def _file_ledger(tmp_path):
    """真文件库：上期出过一张带房租的单子，草稿里有一笔伙食。返回 (engine, 成员 id, 房租 id, 上期那张的 id)。
    内存库那套 StaticPool 只有一条连接，两台手机交错的读写在它上面演不出来。"""
    from sqlmodel import SQLModel, create_engine

    from app.services import settings as settings_svc
    from app.services.settings import seed_settings

    engine = create_engine(f"sqlite:///{tmp_path / 'two-phones.db'}",
                           connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        settings_svc.set_(s, "backup_path", str(tmp_path / "backups"))
        a = Member(name="a", display_name="A", display_order=0, joined_on=dt.date(2026, 1, 1))
        rent = Category(name="房租", monthly=True, same_as_last=True)
        food = Category(name="伙食")
        for row in (a, rent, food):
            s.add(row)
        s.commit()
        aid, rid, fid = a.id, rent.id, food.id
        create_entry(s, actor_id=aid, kind=EntryKind.expense, on=AUG, amount=120_000,
                     payer_id=aid, category_id=rid)
        first = cut_statement(s, actor_id=aid, on=AUG).id
        create_entry(s, actor_id=aid, kind=EntryKind.expense, on=SEP, amount=3_000,
                     payer_id=aid, category_id=fid)
    return engine, aid, rid, first


def test_the_draft_hands_out_the_bill_id_it_was_read_against(tmp_path, monkeypatch) -> None:
    """B 刷新出账框的那一刻，A 的「照上期 + 出账」正好在 B 读完草稿之后提交。
    「最近一张」原来放在 build_bill 最后才读：B 拿到的是**旧草稿 + 新 id**，
    弹框照样勾着「先按上期记上：房租」，带着新 id 一路过关 —— 房租记进下一期，
    再出一张只有房租的单子。先拿 id 再读账目，最坏是旧 id，后面一律 409。"""
    import app.services.bill as bill_mod
    from app.services.bill import BillError, build_bill

    engine, aid, rid, seen = _file_ledger(tmp_path)
    real = bill_mod.unbilled
    fired: list[bool] = []

    def a_cuts_right_after_b_read_the_draft(session):
        rows = real(session)
        if not fired:
            fired.append(True)
            with Session(engine) as a:
                carry_same_as_last(a, actor_id=aid, after_statement_id=seen)
                cut_statement(a, actor_id=aid, after_statement_id=seen)
        return rows

    monkeypatch.setattr(bill_mod, "unbilled", a_cuts_right_after_b_read_the_draft)
    with Session(engine) as s:
        b = build_bill(s, None)
    monkeypatch.undo()
    assert fired and b["entry_count"] == 1, "B 手里是 A 出账之前那份草稿"
    assert b["prev_statement_id"] == seen, "旧草稿配上新 id，后面的照上期和出账都会放行"

    with Session(engine) as s:                     # B 照着这份对话框点下去
        with pytest.raises(BillError) as e:
            carry_same_as_last(s, actor_id=aid, after_statement_id=b["prev_statement_id"])
        assert e.value.code == "bill_changed"
        assert [x for x in unbilled(s) if x.category_id == rid] == [], "下一期不许多出一笔房租"


def test_a_cut_landing_inside_a_carry_cannot_push_rent_into_the_next_period(tmp_path, monkeypatch) -> None:
    """B 的「照上期」刚核完 after_statement_id、还没读本期有哪几项，A 的出账就提交了：
    草稿一下子空了，房租被当成「本期还没记」，记进了**下一期**；B 紧接着的出账 409
    「这次什么都没动」，可下一期的房租已经在那儿了。照上期和出账共用一把锁才堵得上。

    B 读草稿之前等 A 出完账（最多等 1 秒）：没有共用的锁时 A 直接出完，B 读到空草稿；
    有锁时 A 被挡在外面，B 等不到、超时接着走，整个跑在 A 出账之前。"""
    import threading

    import app.services.monthly as monthly_mod
    from app.services.bill import BillError

    engine, aid, rid, seen = _file_ledger(tmp_path)
    with Session(engine) as s:
        carry_same_as_last(s, actor_id=aid, after_statement_id=seen)      # A 先照上期记上房租

    real = monthly_mod.unbilled
    b_reading, a_cut = threading.Event(), threading.Event()

    def b_waits_for_a_before_reading(session):
        if threading.current_thread().name == "B":
            b_reading.set()
            a_cut.wait(timeout=1)
        return real(session)

    monkeypatch.setattr(monthly_mod, "unbilled", b_waits_for_a_before_reading)
    out: dict[str, object] = {}

    def a() -> None:
        b_reading.wait(timeout=5)
        with Session(engine) as s:
            out["A"] = cut_statement(s, actor_id=aid, after_statement_id=seen).id
        a_cut.set()

    def b() -> None:
        with Session(engine) as s:
            try:
                out["B"] = carry_same_as_last(s, actor_id=aid, after_statement_id=seen)
            except BillError as e:
                out["B"] = e.code

    ts = [threading.Thread(target=a, name="A"), threading.Thread(target=b, name="B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    monkeypatch.undo()

    assert "A" in out, "A 的出账没出成"
    assert out["B"] == "bill_changed" or out["B"]["created"] == [], out["B"]
    with Session(engine) as s:
        assert [x for x in unbilled(s) if x.category_id == rid] == [], "A 出账之后草稿里又多了一笔房租"


# ------------------------------------------------------- 审计里的来历（#46）


def test_carry_leaves_where_it_was_copied_from_in_the_audit(session: Session, members) -> None:
    from app.models import AuditLog

    a, *_ = members
    rent = cats(session)["家賃"]
    rent.same_as_last = True
    session.add(rent)
    prev = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                        payer_id=a.id, category_id=rent.id)
    cut_statement(session, actor_id=a.id)
    carry_same_as_last(session, actor_id=a.id)
    made = next(e for e in unbilled(session) if e.category_id == rent.id)
    log = session.exec(select(AuditLog).where(AuditLog.target_id == made.id, AuditLog.action == "create")).one()
    assert log.after_json["via"] == {"kind": "carry", "from_entry": prev.id}
    assert log.after_json["amount_jpy"] == 120_000, "快照本身的形状不变"


# ------------------------------------------ 最近几期一模一样 → 问一句（#51）


def _period(session: Session, a: Member, items: dict[int, list[int]], *, monthly: bool = True) -> None:
    """出一期：items 是 {分类 id: 这期记的几笔}"""
    filler = session.exec(select(Category).where(Category.name == "日用品")).one()
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=100,
                 payer_id=a.id, category_id=filler.id)          # 好让每一期都有东西出
    for cid, amounts in items.items():
        for amount in amounts:
            create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=amount,
                         payer_id=a.id, category_id=cid)
    cut_statement(session, actor_id=a.id, include_monthly=monthly)


def test_suggest_same_as_last_after_k_identical_periods_without_saying_how_much(
    session: Session, members
) -> None:
    a, *_ = members
    c = cats(session)
    rent, elec, water = c["家賃"], c["電気"], c["水道"]
    _period(session, a, {rent.id: [120_000], elec.id: [8_000], water.id: [5_000]})
    _period(session, a, {rent.id: [120_000], elec.id: [8_000], water.id: [5_000, 5_000]})   # 水费那期记了两笔
    _period(session, a, {}, monthly=False)                                         # 中途一张日常小账，不断链
    rows = rows_by_name(session)
    assert rows["家賃"]["suggest_same_as_last"] is False, "才两期，不够 k=3"

    _period(session, a, {rent.id: [120_000], elec.id: [9_100], water.id: [5_000]})
    rows = rows_by_name(session)
    assert rows["家賃"]["suggest_same_as_last"] is True
    assert rows["家賃"]["last_amount"] is None and 120_000 not in rows["家賃"].values(), "只问，不报金额（D21）"
    assert rows["電気"]["suggest_same_as_last"] is False, "金额变过"
    assert rows["水道"]["suggest_same_as_last"] is False, "有一期是两笔"

    rent.same_as_last = True
    session.add(rent)
    session.commit()
    assert rows_by_name(session)["家賃"]["suggest_same_as_last"] is False, "已经开了就不问了"


def test_suggest_same_as_last_skips_items_that_come_every_other_period(session: Session, members) -> None:
    """隔月收、每次金额一样的水费不能被挑中：人照提示一开，单月那期出账框就默认勾上
    「先按上期记上：水费」，每个单月多收一次。按账单数「最近 k 期」，缺一期就不问。"""
    from app.services import settings as settings_svc

    a, *_ = members
    c = cats(session)
    for i in range(6):
        _period(session, a, {c["水道"].id: [12_000]} if i % 2 == 0 else {c["家賃"].id: [120_000]})
    assert rows_by_name(session)["水道"]["suggest_same_as_last"] is False
    settings_svc.set_(session, "same_as_last_hint_k", 0)
    _period(session, a, {c["家賃"].id: [120_000]})
    assert rows_by_name(session)["家賃"]["suggest_same_as_last"] is False, "0 ＝ 关"


# ------------------------------------------ 隔几期出现一次（#47）


def test_rhythm_tells_a_skipped_bimonthly_bill_from_a_forgotten_one(session: Session, members) -> None:
    """出账时「X 还空着」：隔月收的水费上一期刚收过，这期本来轮空（cuts_since_last < typical_gap）；
    上一期没收，这期就该有了。中途的日常小账不算一期。历史不够两个间隔的一律不给节奏 ——
    猜错了就是把真忘了的账画成灰字。"""
    a, *_ = members
    c = cats(session)
    rent, water, elec = c["家賃"], c["水道"], c["電気"]
    _period(session, a, {rent.id: [120_000], water.id: [12_000], elec.id: [8_000]})
    _period(session, a, {rent.id: [120_000]})
    _period(session, a, {}, monthly=False)
    _period(session, a, {rent.id: [120_000], water.id: [12_000]})
    _period(session, a, {rent.id: [120_000]})
    _period(session, a, {rent.id: [120_000], water.id: [12_000]})

    rows = rows_by_name(session)
    assert (rows["家賃"]["cuts_since_last"], rows["家賃"]["typical_gap"]) == (1, 1)     # 每期都有：该填
    assert (rows["水道"]["cuts_since_last"], rows["水道"]["typical_gap"]) == (1, 2)     # 刚收过：这期轮空
    assert (rows["電気"]["cuts_since_last"], rows["電気"]["typical_gap"]) == (5, None)  # 只出现过一次
    _period(session, a, {rent.id: [120_000]})
    rows = rows_by_name(session)
    assert (rows["水道"]["cuts_since_last"], rows["水道"]["typical_gap"]) == (2, 2)     # 隔了一期：该收了


def test_rhythm_gives_no_gap_while_the_history_is_short_or_uneven(session: Session, members) -> None:
    a, *_ = members
    c = cats(session)
    water = c["水道"]
    assert rows_by_name(session)["水道"]["cuts_since_last"] is None, "从来没出现过"
    _period(session, a, {water.id: [12_000]})
    _period(session, a, {water.id: [12_000]})
    assert rows_by_name(session)["水道"]["typical_gap"] is None, "一个间隔不够"
    _period(session, a, {c["家賃"].id: [1]})
    _period(session, a, {water.id: [12_000]})                    # 间隔 1、2：不稳
    assert rows_by_name(session)["水道"]["typical_gap"] is None


def test_rhythm_needs_the_last_two_gaps_to_match_the_usual_one(session: Session, members) -> None:
    """间隔 2、2、1、2：中位数是 2、最后一个间隔也是 2，可倒数第二个是 1 —— 节奏不稳，不给。
    只看最后一个的话这期会被画成灰字的「还没轮到」，真忘了的那笔就藏起来了"""
    a, *_ = members
    c = cats(session)
    water, rent = c["水道"], c["家賃"]
    for i in range(8):                                           # 水道出现在第 0、2、4、5、7 期
        _period(session, a, {rent.id: [120_000], **({water.id: [12_000]} if i in (0, 2, 4, 5, 7) else {})})
    rows = rows_by_name(session)
    assert (rows["水道"]["cuts_since_last"], rows["水道"]["typical_gap"]) == (1, None)


# ---------------------------------------- 固定费记进了别的分类（#58）


def test_a_fixed_cost_recorded_under_another_category_is_pointed_at(session: Session, members) -> None:
    """「其他」里备注着「電気代」：面板和出账框照样说电费空着，人照着再填一次就重复了。
    只问「是不是它？」—— 那一行还是空的、照上期照旧在、分类不替人改。"""
    a, *_ = members
    c = cats(session)
    c["電気"].same_as_last = True
    session.add(c["電気"])
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=8_700,
                 payer_id=a.id, category_id=c["電気"].id)
    cut_statement(session, actor_id=a.id)
    stray = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=8_700,
                         payer_id=a.id, category_id=c["日用品"].id, title="９月の電気代")
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=300,
                 payer_id=a.id, category_id=c["日用品"].id, title="电池")

    rows = rows_by_name(session)
    assert rows["電気"]["maybe_elsewhere"] == [
        {"entry_id": stray.id, "amount": 8_700, "category_name": "日用品", "title": "９月の電気代"}
    ]
    assert rows["電気"]["amount"] is None and rows["電気"]["carry_amount"] == 8_700, "弱证据不改任何默认"
    assert rows["水道"]["maybe_elsewhere"] == []
    session.refresh(stray)
    assert stray.category_id == c["日用品"].id

    # 已经填了的行也要说（那就是「可能记重了」）
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=8_700,
                 payer_id=a.id, category_id=c["電気"].id)
    assert [x["entry_id"] for x in rows_by_name(session)["電気"]["maybe_elsewhere"]] == [stray.id]
    # 别的固定费那一行底下备注着「電気」（水费单上写着「含電気」）：它在自己那一行，不是记错了分类
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=5_000,
                 payer_id=a.id, category_id=c["水道"].id, title="水道・電気まとめ")
    assert [x["entry_id"] for x in rows_by_name(session)["電気"]["maybe_elsewhere"]] == [stray.id]


# ------------------------------------------------ 抄的是最近那一期（#33）


def test_carry_copies_the_latest_period_not_an_older_one(session: Session, members) -> None:
    """8 月房租 120,000（A 垫、均分），9 月涨到 125,000（B 垫、A 多担 5,000）。
    照上期抄的、面板上「上期」给的，都得是 9 月那一笔 —— 金额、垫付人、分摊一起。

    排序方向原来没人钉：改成取最老的，会一直抄涨租之前的旧租金、旧垫付人。
    两张故意在不同的日子出（固定费的日期出账时被盖成出账日，同一天出的话分不出先后）。"""
    from app.services.bill import _shares_of

    a, b, c_ = members
    cat = cats(session)["家賃"]
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, on=dt.date(2026, 8, 31))
    rule = {"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c_.id): 1},
            "adjustments": {str(a.id): 5_000, str(c_.id): -5_000}}
    sep = create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP, amount=125_000,
                       payer_id=b.id, category_id=cat.id, rule=rule)
    cut_statement(session, actor_id=a.id, on=dt.date(2026, 9, 30))
    cat.same_as_last = True
    session.add(cat)
    session.commit()

    row = rows_by_name(session)["家賃"]
    assert (row["carry_amount"], row["last_amount"], row["last_payer_id"]) == (125_000, 125_000, b.id)
    made = carry_same_as_last(session, actor_id=a.id)["created"]
    assert [m["amount"] for m in made] == [125_000]
    rent = next(e for e in unbilled(session) if e.category_id == cat.id)
    assert rent.payer_id == b.id
    assert _shares_of(session, [rent.id])[rent.id] == _shares_of(session, [sep.id])[sep.id]


def test_on_the_same_date_the_later_entry_wins(session: Session, members) -> None:
    """两张在同一天出（日期一样）：按 id 取后记的那一笔。这一层平局规则也要钉"""
    a, *_ = members
    cat = cats(session)["家賃"]
    same_day = dt.date(2026, 9, 30)
    for amount in (120_000, 125_000):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=amount,
                     payer_id=a.id, category_id=cat.id)
        cut_statement(session, actor_id=a.id, on=same_day)
    cat.same_as_last = True
    session.add(cat)
    session.commit()
    assert rows_by_name(session)["家賃"]["carry_amount"] == 125_000


# ------------------------------------------------ 面板上「这笔算谁垫的」不预填搬走的人（#38）


def test_unrecorded_row_skips_last_payer_who_moved_out(session: Session, members) -> None:
    """上期房租是 C 垫的，C 已经搬走：面板手填的那一行不许预填成 C ——
    账单会反过来叫留下的人给他转钱（AUDIT 第二轮「我替你定的」#2）。
    后端没有「垫付人当天在籍」的校验（还挂着），这一道过滤是唯一的闸"""
    a, b, c_ = members
    cat = cats(session)["家賃"]
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=AUG, amount=120_000,
                 payer_id=c_.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id)
    c_.left_on = dt.date(2026, 8, 31)
    session.add(c_)
    session.commit()
    assert rows_by_name(session)["家賃"]["last_payer_id"] is None


# ------------------------------------------------ 面板合计只算固定费（#79）


def test_the_panel_total_counts_only_fixed_costs(session: Session, members) -> None:
    """面板底下那个合计是「本期固定费」：同一张草稿里的日常开销不许混进去"""
    a, *_ = members
    c = cats(session)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=120_000,
                 payer_id=a.id, category_id=c["家賃"].id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000,
                 payer_id=a.id, category_id=c["日用品"].id)
    assert monthly_rows(session)["total"] == 120_000
