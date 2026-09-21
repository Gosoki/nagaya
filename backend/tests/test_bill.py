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

from app.models import Category, EntryKind, Statement, jst_date, now_utc
from app.services import settings as settings_svc
from app.services.bill import BillError, build_bill, cut_statement, entries_of
from app.services.ledger import balances, create_entry, update_entry

SEP = dt.date(2026, 9, 10)
OCT = dt.date(2026, 10, 10)


def row_of(bill: dict, member_id: int) -> dict:
    return next(r for r in bill["members"] if r["member_id"] == member_id)


def test_draft_bill_is_everything_not_yet_billed(session: Session, members) -> None:
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, title="房租")
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
                 amount=-3_000, payer_id=a.id, title="返现")

    bill = build_bill(session, None)
    assert bill["total_income"] == -3_000
    assert row_of(bill, b.id)["transferred_out"] == 30_000
    assert sum(r["closing"] for r in bill["members"]) == 0


def test_editing_a_billed_entry_is_visible(session: Session, members) -> None:
    """已出账的账目随时能改 —— 但改了必须看得见。

    没有锁：余额是全局累计的，改了钱也不会算错，差额进下一张的「上期结转」。
    留痕才是要紧事，否则下一张单子上冒出来的结转没人解释得清。
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
    # 头一张没有「上一次」，只能从第一笔算起
    assert first.covers_from == SEP and first.covers_to == SEP
    # 第二张起，起始日是**上一次出账那天**，不是这张单子里最早那笔的日期 ——
    # 「10 月那张从 10/10 开始」是错觉，10 月上旬没人花钱而已，
    # 它管的是上次出账之后的一切
    assert second.covers_from == jst_date(first.cut_at)
    assert second.covers_to == OCT
    assert "出账" in first.label


def test_editing_an_earlier_bill_flags_the_later_ones_too(session: Session, members) -> None:
    """改了**更早**那张单子上的账，后面每一张的数字都会跟着变 —— 那就都得标出来。

    「不锁历史」的前提是「改动必须可见」。原来只认「改到这张单子自己的账目」，
    于是改一笔五月的账，六月七月的账单会悄悄换一组数字，上面什么提示都没有。
    """
    a, b, c = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id)
    first = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT, amount=6_000, payer_id=b.id)
    second = cut_statement(session, actor_id=a.id)

    assert build_bill(session, second)["edited_after_cut"] is None

    # 动第一张单子上的那笔账：第二张一笔没碰，但它的「上期结转」变了
    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 9_000})

    flagged = build_bill(session, second)["edited_after_cut"]
    assert flagged is not None, "更早的账单被改过，这张也该标出来"
    assert flagged["count"] == 0 and flagged["from_earlier"] is True
    # 第一张自己那笔被改了，照旧按「本单被改」标
    own = build_bill(session, first)["edited_after_cut"]
    assert own["count"] == 1 and own["from_earlier"] is False


def test_empty_draft_covers_nothing(session: Session, members) -> None:
    """出完账草稿就空了 —— 覆盖期**两端一起留空**，不许只给一头。

    起始日改成「上次出账那天」之后踩过：草稿一笔都没有时 covers_from 照样有值、
    covers_to 是 None，界面上显示成「2026-09-22 〜 」，断了一截。
    """
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    cut_statement(session, actor_id=a.id)

    draft = build_bill(session, None)
    assert draft["entry_count"] == 0
    assert draft["covers_from"] is None and draft["covers_to"] is None


def test_moved_out_member_stays_until_settled_then_leaves_the_list(session: Session, members) -> None:
    """搬走的人：**还欠着就一直挂在账单上，结清了才从名单里消失。**

    「退出不删人」是为了历史账追溯得到人，可不该让每张新账单都顶着一排前室友的 0。
    """
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id)
    c.left_on = SEP
    session.add(c)
    session.commit()

    # 还欠着 1,000：照样在名单里
    draft = build_bill(session, None)
    assert row_of(draft, c.id)["closing"] == -1_000

    # 把账平掉（他把钱转给了 a），下一张单子上就不该再有他
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP,
                 amount=1_000, payer_id=c.id, to_member_id=a.id)
    cut_statement(session, actor_id=a.id)
    nxt = build_bill(session, None)
    assert [r["member_id"] for r in nxt["members"]] == [a.id, b.id]


def test_settled_when_every_planned_transfer_is_recorded(session: Session, members) -> None:
    """「转账按钮都点过了就显示结清」。"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)

    bill = build_bill(session, st)
    assert bill["settled"] is False
    assert bill["settled_transfers"] == [False, False]

    for t in bill["transfers"]:
        create_entry(session, actor_id=t["from_id"], kind=EntryKind.settlement,
                     on=dt.date(2026, 10, 15), amount=t["amount"],
                     payer_id=t["from_id"], to_member_id=t["to_id"])

    done = build_bill(session, st)
    assert done["settled_transfers"] == [True, True]
    assert done["settled"] is True


def test_partial_settlement_is_not_settled(session: Session, members) -> None:
    """只还了一部分不算结清 —— 那是赊账，差额进下一张。"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    plan = build_bill(session, st)["transfers"]

    create_entry(session, actor_id=plan[0]["from_id"], kind=EntryKind.settlement,
                 on=dt.date(2026, 10, 15), amount=plan[0]["amount"] // 2,
                 payer_id=plan[0]["from_id"], to_member_id=plan[0]["to_id"])
    bill = build_bill(session, st)
    assert bill["settled"] is False
    assert bill["settled_transfers"][0] is False


def test_cut_without_monthly_leaves_fixed_costs_in_draft(session: Session, members) -> None:
    """提前出个小账：只结日常那部分，固定费留在草稿里等账单来。"""
    from app.models import Category

    a, *_ = members
    rent = Category(name="房租", monthly=True)
    daily = Category(name="日用品", monthly=False)
    session.add(rent)
    session.add(daily)
    session.commit()
    session.refresh(rent)
    session.refresh(daily)

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, category_id=rent.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_380, payer_id=a.id, category_id=daily.id)

    st = cut_statement(session, actor_id=a.id, include_monthly=False)
    assert build_bill(session, st)["total_expense"] == 1_380       # 只出了日常
    assert build_bill(session, None)["total_expense"] == 120_000   # 房租还在草稿里


def test_cut_without_monthly_refuses_when_nothing_daily(session: Session, members) -> None:
    from app.models import Category

    a, *_ = members
    rent = Category(name="房租", monthly=True)
    session.add(rent)
    session.commit()
    session.refresh(rent)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, category_id=rent.id)

    with pytest.raises(BillError) as exc:
        cut_statement(session, actor_id=a.id, include_monthly=False)
    assert exc.value.code == "nothing_to_cut"


def test_bill_reports_previous_cut_time(session: Session, members) -> None:
    """前端要拿它显示「上次出账」，也用来挡住把日期选回上一张账单里。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_000, payer_id=a.id)
    assert build_bill(session, None)["prev_cut_at"] is None

    first = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT,
                 amount=2_000, payer_id=a.id)
    draft = build_bill(session, None)
    assert draft["prev_cut_at"] is not None
    assert draft["prev_label"] == first.label


def test_snapshot_does_not_freeze_settlement_progress(session: Session, members) -> None:
    """快照里不该有 settled —— 转账是出账之后才发生的，冻结下来就是假值。"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    assert "settled" not in st.snapshot_json
    assert "settled_transfers" not in st.snapshot_json
    # 实时那份仍然要算得出来
    assert build_bill(session, st)["settled"] is False


def test_suggest_monthly_turns_off_right_after_a_cut(session: Session, members) -> None:
    """刚出过账又出一张，多半是临时结的小账 —— 固定费默认别带上。

    只影响勾选框的默认值，出账逻辑本身不看它；阈值在设置里，不写死。
    """
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_000, payer_id=a.id)

    # 头一张账单没有「上次」，当然该带上固定费
    first_draft = build_bill(session, None)
    assert first_draft["days_since_prev_cut"] is None
    assert first_draft["suggest_monthly"] is True

    st = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT,
                 amount=2_000, payer_id=a.id)

    def backdate(days: int) -> dict:
        st.cut_at = now_utc() - dt.timedelta(days=days)
        session.add(st)
        session.commit()
        return build_bill(session, None)

    near = backdate(5)
    assert near["days_since_prev_cut"] == 5
    assert near["suggest_monthly"] is False

    far = backdate(25)
    assert far["days_since_prev_cut"] == 25
    assert far["suggest_monthly"] is True

    # 阈值可调：改小了，5 天也算隔得够久
    settings_svc.set_(session, "monthly_gap_days", 3)
    assert backdate(5)["suggest_monthly"] is True


def test_overpayment_comes_back_in_the_next_bill(session: Session, members) -> None:
    """改了已出账的账，多付的钱在下一张账单里自己扣回来 —— 这是不上锁的全部底气。

    顺带守住另一半：**那张已出的单子，转账方案和「已收到」的勾不许跟着变**。
    方案是真发到群里、大家照着转的钱；它一变，按下标对位的勾就会对到别的行上去。
    """
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=30_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)

    issued = build_bill(session, st)
    plan_before = [dict(t) for t in issued["transfers"]]
    assert plan_before, "这张单子本来就该有转账方案"

    # 大家照着方案转完钱
    for t in plan_before:
        create_entry(session, actor_id=t["from_id"], kind=EntryKind.settlement, on=SEP,
                     amount=t["amount"], payer_id=t["from_id"], to_member_id=t["to_id"])
    assert build_bill(session, st)["settled"] is True

    # 事后发现这笔其实只有 18,000 —— 大家多付了
    e = next(x for x in entries_of(session, st.id) if x.kind == EntryKind.expense)
    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 18_000})

    after = build_bill(session, st)
    assert [dict(t) for t in after["transfers"]] == plan_before   # 历史方案不动
    assert after["settled"] is True                               # 勾也不动
    assert after["edited_after_cut"]["count"] == 1                # 但要标出来

    # 下一张草稿：改小后每人只该担 6,000，可是当初照 10,000 转的钱已经付出去了 ——
    # 差额 4,000 一分不差地摆在下一张上，变成「a 该还 b、c 各 4,000」
    draft = build_bill(session, None)
    assert row_of(draft, b.id)["opening"] == -6_000      # 已出账那部分的应担
    assert row_of(draft, b.id)["transferred_out"] == 10_000
    assert row_of(draft, b.id)["closing"] == 4_000       # 多付了 4,000，应收
    assert row_of(draft, c.id)["closing"] == 4_000
    assert row_of(draft, a.id)["closing"] == -8_000
    assert sum(r["closing"] for r in draft["members"]) == 0
    assert sorted((t["from_id"], t["to_id"], t["amount"]) for t in draft["transfers"]) == [
        (a.id, b.id, 4_000),
        (a.id, c.id, 4_000),
    ]
    assert sum(balances(session).values()) == 0


def test_cut_stamps_monthly_entries_with_the_cut_date(session: Session, members) -> None:
    """固定费的日期在出账那一刻统一盖成出账日。

    房租这种根本没有「填入日」—— 它不是某天发生的事，就是这张账单的一项。
    日常开销不动：几号买的日用品是真事。
    """
    a, *_ = members
    rent, daily = Category(name="房租", monthly=True), Category(name="日用品", monthly=False)
    session.add(rent)
    session.add(daily)
    session.commit()
    session.refresh(rent)
    session.refresh(daily)

    fixed = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                         amount=120_000, payer_id=a.id, category_id=rent.id)
    shopping = create_entry(session, actor_id=a.id, kind=EntryKind.expense,
                            on=dt.date(2026, 9, 14), amount=1_980, payer_id=a.id,
                            category_id=daily.id)

    cut_day = dt.date(2026, 9, 30)
    st = cut_statement(session, actor_id=a.id, on=cut_day)

    session.refresh(fixed)
    session.refresh(shopping)
    assert fixed.date == cut_day                      # 固定费盖成出账日
    assert shopping.date == dt.date(2026, 9, 14)      # 日常开销原样不动
    assert st.covers_to == cut_day
    assert st.label == "9/30 出账"


def test_cut_without_monthly_leaves_their_dates_alone(session: Session, members) -> None:
    """不勾「包括固定费」时固定费留在草稿里，日期当然也不该被盖。"""
    a, *_ = members
    rent, daily = Category(name="房租", monthly=True), Category(name="日用品", monthly=False)
    session.add(rent)
    session.add(daily)
    session.commit()
    session.refresh(rent)
    session.refresh(daily)

    fixed = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                         amount=120_000, payer_id=a.id, category_id=rent.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=1_980, payer_id=a.id, category_id=daily.id)

    cut_statement(session, actor_id=a.id, on=dt.date(2026, 9, 30), include_monthly=False)
    session.refresh(fixed)
    assert fixed.date == SEP
    assert fixed.statement_id is None


def test_a_late_transfer_still_lights_up_the_bill_it_was_paying(
    session: Session, members
) -> None:
    """拖到下一张出账之后才还的钱，也得把当初那张点亮。

    原来的判据拿「下一张的出账时刻」当上界，于是这条最常见的路径永远点不亮：
    那张单子的方案是冻结的（钱到账也不会变），屏幕上哪儿都不变绿。
    用户以为没点上，照着屏幕再转一次 —— 这一屏的全部作用就是防这件事。
    """
    a, b, _ = members
    cat = Category(name="日用品", monthly=False)
    session.add(cat)
    session.commit()
    session.refresh(cat)

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=30_000, payer_id=a.id, category_id=cat.id)
    s1 = cut_statement(session, actor_id=a.id)
    plan = (s1.snapshot_json or {})["transfers"]
    assert plan, "这张单子该开出转账方案"

    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT,
                 amount=3_000, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id)                  # 下一张先出了

    t = plan[0]
    # 部分还款：还没够，不许点亮，但「已经转了多少」要说得出来
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=OCT,
                 amount=t["amount"] - 1, payer_id=t["from_id"], to_member_id=t["to_id"])
    bill = build_bill(session, s1)
    assert bill["settled_transfers"][0] is False
    assert bill["settled_paid"][0] == t["amount"] - 1

    # 补齐那 1 円 —— 当初那张必须跟着变绿
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=OCT,
                 amount=1, payer_id=t["from_id"], to_member_id=t["to_id"])
    assert build_bill(session, s1)["settled_transfers"][0] is True


def test_unrelated_transfers_do_not_settle_a_bill(session: Session, members) -> None:
    """跟这张单子的方案无关的那几对，转再多也不算数。"""
    a, b, c = members
    cat = Category(name="日用品", monthly=False)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=30_000, payer_id=a.id, category_id=cat.id)
    s1 = cut_statement(session, actor_id=a.id)
    t = (s1.snapshot_json or {})["transfers"][0]
    other = next(m.id for m in (a, b, c) if m.id not in (t["from_id"], t["to_id"]))

    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=OCT,
                 amount=999_999, payer_id=t["from_id"], to_member_id=other)
    assert build_bill(session, s1)["settled"] is False
