"""草稿账单上「要人看一眼」的那几样（GET /api/bill 的 review、opening_drift、prev_statement_id）。

要钉死的是**只标不改**：标出来的账一个数字都不许变，也不许拦出账；
以及每一样「不该报」的那半 —— 挂错的签会让人对这块提示视而不见。
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.models import Category, EntryKind, EntryShare, Member
from app.services import settings as settings_svc
from app.services.bill import build_bill, cut_statement
from app.services.ledger import balances, create_entry, delete_entry, update_entry

SEP = dt.date(2026, 9, 10)


def _cat(session: Session, name: str, *, monthly: bool = False) -> Category:
    c = Category(name=name, monthly=monthly)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _review(session: Session) -> dict:
    return build_bill(session, None)["review"]


# ------------------------------------------------- 参与人和在籍日对不上（#1）


def test_a_late_move_out_flags_the_draft_entries_still_charging_them(session: Session, members) -> None:
    """10/15 搬走、晚几天才去标：草稿里那之后的账照样算着他一份 —— 不重算，但要标出来。"""
    a, b, c = members
    food = _cat(session, "伙食")
    before = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP - dt.timedelta(days=5),
                          amount=3_000, payer_id=a.id, category_id=food.id)
    after = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                         amount=3_000, payer_id=a.id, category_id=food.id)
    c.left_on = SEP - dt.timedelta(days=1)            # 事后补标的搬走日
    session.add(c)
    session.commit()

    gaps = _review(session)["membership_gaps"]
    assert gaps == [{"entry_id": after.id, "member_id": c.id, "type": "left_but_charged", "share": 1_000}]
    assert before.id not in {g["entry_id"] for g in gaps}, "搬走之前的账本来就该算他"
    # 只标不改：那一笔的分摊一分没动
    shares = dict(session.exec(
        select(EntryShare.member_id, EntryShare.amount_jpy).where(EntryShare.entry_id == after.id)
    ).all())
    assert shares == {a.id: 1_000, b.id: 1_000, c.id: 1_000}


def test_a_late_move_in_flags_the_draft_entries_that_left_them_out(session: Session, members) -> None:
    a, *_ = members
    food = _cat(session, "伙食")
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=3_000, payer_id=a.id, category_id=food.id)
    d = Member(name="d", display_name="D", display_order=3, joined_on=SEP - dt.timedelta(days=3))
    session.add(d)
    session.commit()

    assert _review(session)["membership_gaps"] == [
        {"entry_id": e.id, "member_id": d.id, "type": "joined_not_charged", "share": 0}
    ]


def test_membership_gaps_skip_what_is_supposed_to_differ(session: Session, members) -> None:
    """转账、固定费（出账时日期会被盖成出账日，D30）、帮买、点了「不参与」的人：都不报。"""
    a, b, c = members
    rent = _cat(session, "房租", monthly=True)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=9_000,
                 payer_id=a.id, category_id=rent.id)
    create_entry(session, actor_id=c.id, kind=EntryKind.settlement, on=SEP, amount=1_000,
                 payer_id=c.id, to_member_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=800, payer_id=a.id,
                 member_ids=[b.id], rule={"mode": "ratio", "weights": {str(b.id): 1}})     # 帮买
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=600, payer_id=a.id,
                 rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c.id): 0}})
    c.left_on = SEP - dt.timedelta(days=1)
    session.add(c)
    session.commit()

    assert _review(session)["membership_gaps"] == []


def test_issued_bills_carry_no_review(session: Session, members) -> None:
    """已出的账单不挂：冻结的历史和 D30 改过的日期，挂上去就是永久的噪音。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    issued = build_bill(session, st)
    assert issued["review"] is None and issued["opening_drift"] is None
    assert build_bill(session, None)["review"] == {
        "membership_gaps": [], "possible_duplicates": [], "outliers": []
    }


# ----------------------------------------------------------- 疑似重复（#17）


def test_the_same_receipt_from_two_phones_is_flagged_whoever_paid(session: Session, members) -> None:
    """两台手机各记一遍同一张小票：同分类、同金额、日期差一天以内。付款人不同照样报 ——
    没设默认垫付人时各自填自己，付款人不同反倒是重复的典型样子。"""
    a, b, _ = members
    food = _cat(session, "伙食")
    x = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=4_200,
                     payer_id=a.id, category_id=food.id)
    y = create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP + dt.timedelta(days=1),
                     amount=4_200, payer_id=b.id, category_id=food.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP + dt.timedelta(days=3),
                 amount=4_200, payer_id=a.id, category_id=food.id)            # 隔了三天：不算
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=4_201,
                 payer_id=a.id, category_id=food.id)                          # 金额不同
    assert _review(session)["possible_duplicates"] == [{"a": x.id, "b": y.id}]
    # 只标不删：账照样都在
    assert len(build_bill(session, None)["members"]) == 3
    assert build_bill(session, None)["entry_count"] == 4


def test_duplicate_window_is_a_setting_and_zero_turns_it_off(session: Session, members) -> None:
    a, *_ = members
    food = _cat(session, "伙食")
    for day in (0, 2):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP + dt.timedelta(days=day),
                     amount=500, payer_id=a.id, category_id=food.id)
    assert _review(session)["possible_duplicates"] == []
    settings_svc.set_(session, "duplicate_window_days", 2)
    assert len(_review(session)["possible_duplicates"]) == 1
    settings_svc.set_(session, "duplicate_window_days", 0)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=500,
                 payer_id=a.id, category_id=food.id)                          # 同一天也不报：关了
    assert _review(session)["possible_duplicates"] == []


def test_a_transfer_recorded_by_both_sides_is_flagged(session: Session, members) -> None:
    """转出方和转入方各记一次 kan→go ¥5,000：余额动了两倍。方向反过来的不是同一笔。"""
    a, b, _ = members
    x = create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP, amount=5_000,
                     payer_id=b.id, to_member_id=a.id)
    y = create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP, amount=5_000,
                     payer_id=b.id, to_member_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP, amount=5_000,
                 payer_id=a.id, to_member_id=b.id)
    assert _review(session)["possible_duplicates"] == [{"a": x.id, "b": y.id}]


def test_help_buys_for_two_different_people_are_not_duplicates(session: Session, members) -> None:
    """同一天替 B、替 C 各买一份 ¥680：受益人不同，不是记了两遍。新记的帮买都不挂分类，
    按分类分组的话所有帮买挤在一组里，这种就会被问「是不是记了两遍」。"""
    a, b, c = members

    def help_buy(actor: Member, for_: Member) -> int:
        return create_entry(session, actor_id=actor.id, kind=EntryKind.expense, on=SEP, amount=680,
                            payer_id=a.id, member_ids=[for_.id],
                            rule={"mode": "ratio", "weights": {str(for_.id): 1}}).id

    for_b, _ = help_buy(a, b), help_buy(a, c)
    bill = build_bill(session, None)
    assert len(bill["help_items"]) == 2
    assert bill["review"]["possible_duplicates"] == []
    # 真记重的样子：B 自己又记了一笔「A 替我买」—— 帮的是同一个人，照样要报
    again = help_buy(b, b)
    assert _review(session)["possible_duplicates"] == [{"a": for_b, "b": again}]


def test_duplicates_ignore_fixed_costs_income_and_billed_entries(session: Session, members) -> None:
    """固定费那一行有「另有 N 笔」；收入不查；**只看草稿** —— 出过账的那笔不会被配上，
    否则挂错的签永远消不掉（没有「这不是重复」可点）。"""
    a, *_ = members
    rent, food = _cat(session, "房租", monthly=True), _cat(session, "伙食")
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=4_200,
                 payer_id=a.id, category_id=food.id)
    cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=4_200,
                 payer_id=a.id, category_id=food.id)
    for _ in range(2):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=90_000,
                     payer_id=a.id, category_id=rent.id)
        create_entry(session, actor_id=a.id, kind=EntryKind.income, on=SEP, amount=-300,
                     payer_id=a.id, category_id=food.id)
    assert _review(session)["possible_duplicates"] == []


# ------------------------------------------------------------- 离群（#16）


def _history(session: Session, payer: Member, cat: Category, amounts: list[int]) -> None:
    for i, amount in enumerate(amounts):
        create_entry(session, actor_id=payer.id, kind=EntryKind.expense, on=SEP - dt.timedelta(days=30 + i),
                     amount=amount, payer_id=payer.id, category_id=cat.id)


def test_a_typo_ten_times_the_usual_is_flagged_but_a_small_one_is_not(session: Session, members) -> None:
    """只看偏大那头。偏小（≤ 中位数的几分之一）不判：理由见 review.outliers。"""
    a, *_ = members
    daily = _cat(session, "日用")
    _history(session, a, daily, [480, 500, 520] * 3 + [500])          # 10 笔，中位数 500
    cut_statement(session, actor_id=a.id)
    big = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=5_000, payer_id=a.id, category_id=daily.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=100, payer_id=a.id, category_id=daily.id)            # 五分之一：不标
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_200, payer_id=a.id, category_id=daily.id)          # 大一点，正常

    flagged = {o["entry_id"]: o for o in _review(session)["outliers"]}
    assert set(flagged) == {big.id}
    assert flagged[big.id]["median"] == 500 and flagged[big.id]["ratio"] == 10
    # 只标不改
    assert build_bill(session, None)["total_expense"] == 5_000 + 100 + 1_200


def test_a_cheap_single_item_in_a_wide_category_is_not_flagged(session: Session, members) -> None:
    """日用里「一趟买好几样」和「单买一卷卫生纸」混在一起，¥158 对着 ¥1,500 上下的中位数是常态。
    原来按「五分之一以下」也标，贴近真实价位的模拟数据上四分之三的草稿都挂着这种误报。
    多打一个 0 的照样要标。"""
    a, *_ = members
    daily = _cat(session, "日用")
    _history(session, a, daily, [98, 158, 298, 798, 1_480, 1_480, 1_580, 1_980, 2_480, 2_980])  # 中位 1,530
    cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, title="卫生纸",
                 amount=158, payer_id=a.id, category_id=daily.id)
    typo = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                        amount=15_800, payer_id=a.id, category_id=daily.id)   # 1,580 多打一个 0
    assert [o["entry_id"] for o in _review(session)["outliers"]] == [typo.id]


def test_outliers_need_enough_history_and_never_count_the_entry_itself(session: Session, members) -> None:
    """历史不够 outlier_min_history 笔不判；那一笔自己不算历史 ——
    算进去的话 9 笔历史 + 它自己凑够 10 笔，门槛就形同虚设。"""
    a, *_ = members
    daily = _cat(session, "日用")
    _history(session, a, daily, [500] * 9)
    big = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=5_000, payer_id=a.id, category_id=daily.id)
    assert _review(session)["outliers"] == []

    _history(session, a, daily, [500])                                     # 第 10 笔
    assert [o["entry_id"] for o in _review(session)["outliers"]] == [big.id]


def test_outlier_history_window_and_deleted_entries(session: Session, members) -> None:
    """窗口外的、删掉的都不算历史。"""
    a, *_ = members
    daily = _cat(session, "日用")
    for i in range(10):                                                     # 半年多以前的 10 笔
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP - dt.timedelta(days=200 + i),
                     amount=500, payer_id=a.id, category_id=daily.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=5_000, payer_id=a.id, category_id=daily.id)
    assert _review(session)["outliers"] == []

    settings_svc.set_(session, "outlier_days", 250)
    assert len(_review(session)["outliers"]) == 1
    gone = entries_of_category(session, daily.id)[0]
    delete_entry(session, gone, actor_id=a.id)                             # 剩 9 笔
    assert _review(session)["outliers"] == []


def entries_of_category(session: Session, category_id: int):
    from app.models import Entry

    return list(session.exec(
        select(Entry).where(Entry.category_id == category_id, Entry.deleted_at.is_(None)).order_by(Entry.date)
    ))


def test_outliers_skip_fixed_costs_and_can_be_switched_off(session: Session, members) -> None:
    a, *_ = members
    rent, daily = _cat(session, "房租", monthly=True), _cat(session, "日用")
    _history(session, a, rent, [1_000] * 10)
    _history(session, a, daily, [500] * 10)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, category_id=rent.id)
    big = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=5_000, payer_id=a.id, category_id=daily.id)
    assert [o["entry_id"] for o in _review(session)["outliers"]] == [big.id], "固定费有自己的量级闸"
    settings_svc.set_(session, "outlier_ratio", 0)
    assert _review(session)["outliers"] == []


# --------------------------------------------- 上期结转变了（#44）/ prev_statement_id


def test_draft_points_at_the_bill_whose_frozen_balances_no_longer_hold(session: Session, members) -> None:
    """改了已出账的账，草稿的上期结转跟着变 —— 草稿页上要指得出是哪张。改回去就不指了。"""
    a, *_ = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id, label="9 月")
    assert build_bill(session, None)["opening_drift"] is None

    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 18_000})
    assert build_bill(session, None)["opening_drift"] == {"statement_id": st.id, "label": "9 月"}

    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 30_000})
    assert build_bill(session, None)["opening_drift"] is None
    assert sum(balances(session).values()) == 0


def test_draft_opening_drift_counts_members_missing_from_the_snapshot(session: Session, members) -> None:
    """搬走又结清的人不占快照的行（缺的按 0 比）：他俩之间的旧账一改，草稿照样要指出来。"""
    a, b, c = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id,
                     member_ids=[c.id], rule={"mode": "ratio", "weights": {str(c.id): 1}})
    create_entry(session, actor_id=c.id, kind=EntryKind.settlement, on=SEP, amount=3_000,
                 payer_id=c.id, to_member_id=a.id)
    cut_statement(session, actor_id=b.id)
    for m in (a, c):
        m.left_on = SEP
        session.add(m)
    session.commit()
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP + dt.timedelta(days=1),
                 amount=700, payer_id=b.id)
    st = cut_statement(session, actor_id=b.id)
    assert {r["member_id"] for r in st.snapshot_json["members"]} == {b.id}, "a、c 搬走且结清：这张不占行"

    update_entry(session, e, actor_id=b.id, version=e.version, fields={"amount_jpy": 4_000})
    assert build_bill(session, None)["opening_drift"] == {"statement_id": st.id, "label": st.label}


def test_prev_statement_id_is_the_latest_bill_or_zero(client, auth, session, members) -> None:
    a, *_ = members
    assert client.get("/api/bill", headers=auth).json()["prev_statement_id"] == 0
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    body = client.get("/api/bill", headers=auth).json()
    assert body["prev_statement_id"] == st.id
    assert body["review"] == {"membership_gaps": [], "possible_duplicates": [], "outliers": []}
    assert body["opening_drift"] is None
    issued = client.get(f"/api/statements/{st.id}/bill", headers=auth).json()
    assert issued["review"] is None
