"""账单回归 —— 按「点出账单那一刻」切。

核心性质：
  * 没出账的账目合起来就是当前草稿账单
  * 出账＝划线 + 冻结快照，**不锁定**任何东西
  * 事后改了已出账的账，钱不会算错（差额进下一张的「上期结转」），但改动要能看见
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models import Category, EntryKind, Statement, jst_date, now_utc
from app.services import settings as settings_svc
from app.services.bill import (
    _opening,
    BillError,
    build_bill,
    cut_statement,
    entries_of,
)
from app.services.ledger import balances, create_entry, delete_entry, restore_entry, update_entry

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


def test_pairwise_mode_with_a_transfer_and_a_cut(session: Session, members) -> None:
    """「按原始债权结算」跟真实账目连起来的那条路：转账要**反向**抵掉债权，
    出账冻结的方案要把这张**自己的**账也算上。

    原来只验「每笔 > 0」：把抵消的方向写反（B 已经两清，却被叫去再转 20,000）、
    或者已出账单的范围漏掉本张（冻结出一个空方案，群里那张单子上一笔转账都没有），
    全套测试照样全绿。"""
    a, b, c = members
    settings_svc.set_(session, "simplify_debts", False)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP, amount=10_000,
                 payer_id=b.id, to_member_id=a.id)
    want = [{"from_id": c.id, "to_id": a.id, "amount": 10_000}]
    assert build_bill(session, None)["transfers"] == want
    st = cut_statement(session, actor_id=a.id)
    assert st.snapshot_json["transfers"] == want, "冻结下来的就是群里大家照着转的那份"
    assert build_bill(session, st)["live_transfers"] == want

    # 第二张：C 垫了一笔，更早那张的账也得在范围里
    create_entry(session, actor_id=c.id, kind=EntryKind.expense, on=OCT, amount=6_000, payer_id=c.id)
    st2 = cut_statement(session, actor_id=a.id)
    plan = st2.snapshot_json["transfers"]
    assert plan == [{"from_id": c.id, "to_id": a.id, "amount": 8_000},
                    {"from_id": b.id, "to_id": c.id, "amount": 2_000}], plan


def test_statements_are_ordered_and_labelled(session: Session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    first = cut_statement(session, actor_id=a.id)
    # 出账是「此刻」，所以下一笔的日期也得相对它定：原来写死 10/10，
    # 等真实日期过了 10/10，这笔就成了「补录的、比上次出账还早」，走的是另一条分支
    after = jst_date(first.cut_at) + dt.timedelta(days=10)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=after, amount=2_000, payer_id=a.id)
    second = cut_statement(session, actor_id=a.id)

    rows = list(session.exec(select(Statement).order_by(Statement.cut_at)))
    assert [r.id for r in rows] == [first.id, second.id]
    # 头一张没有「上一次」，只能从第一笔算起
    assert first.covers_from == SEP and first.covers_to == SEP
    # 第二张起，起始日是**上一次出账那天**，不是这张单子里最早那笔的日期 ——
    # 「10 月那张从 10/10 开始」是错觉，10 月上旬没人花钱而已，
    # 它管的是上次出账之后的一切
    assert second.covers_from == jst_date(first.cut_at)
    assert second.covers_to == after
    # 名字留空：后端不拼展示文案（拼出来的中文会被写进库，日文界面上救不回来），
    # 前端按 cut_at 用 i18n 渲染。自己起的名字才存
    assert first.label == ""
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=after, amount=300, payer_id=a.id)
    named = cut_statement(session, actor_id=a.id, label="搬家那次")
    assert named.label == "搬家那次"


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
    """快照里**一个结算进度字段都不许有**。

    转账是出账之后才发生的，而快照算在 snapshot_json 还没写入的那一刻 ——
    plan 为空会被当成「已结清」，冻下来就是个假值。

    字段名**从 settlement_progress 的返回值推导**，不手抄：手抄的那版就是
    `settled_paid` 漏进快照的原因（加字段时只记得改一处）。
    """
    from app.services.bill import settlement_progress

    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)

    fields = list(settlement_progress(session, None))
    assert len(fields) >= 3, "进度字段该有三个，正则/结构变了就该红在这儿"
    leaked = [k for k in fields if k in (st.snapshot_json or {})]
    assert leaked == [], f"这些进度字段被冻进快照了：{leaked}"
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


def test_touching_without_changing_does_not_mark_issued_bill(session: Session, members) -> None:
    """原样点「保存」、删了又撤销、改了又改回来 —— 已出的账单上不该挂「出账后被改过」。

    那句话会跟着复制进群里，写的却是「当初 ¥30,000，现在 ¥30,000」，而且消不掉。
    """
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=900, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    big, small = sorted(entries_of(session, st.id), key=lambda x: -x.amount_jpy)

    v = big.version
    saved = update_entry(session, big, actor_id=a.id, version=v, fields={"amount_jpy": 30_000})
    assert saved.version == v                      # 没变就不推 version，别人的编辑页不会平白撞冲突
    delete_entry(session, small, actor_id=a.id)
    restore_entry(session, small, actor_id=a.id)
    assert build_bill(session, st)["edited_after_cut"] is None

    update_entry(session, big, actor_id=a.id, version=big.version, fields={"amount_jpy": 3_000})
    assert build_bill(session, st)["edited_after_cut"]["count"] == 1
    update_entry(session, big, actor_id=a.id, version=big.version, fields={"amount_jpy": 30_000})
    assert build_bill(session, st)["edited_after_cut"] is None


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
    assert st.label == "", "后端不再拼「9/30 出账」这种展示文案，前端按日期渲染"


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


def test_the_list_endpoint_agrees_with_the_per_bill_one(session: Session, members) -> None:
    """列表页那两个数是批量算的，必须和逐张算出来的**一模一样**。

    批量是为了性能（逐张调 60 张就是 120 次查询，而这个接口每次打开账单页都调，
    实测 5 年规模要 51ms）—— 但快不能换来对不上。
    """
    from app.services.bill import list_settled, list_totals, settlement_progress

    a, b, _ = members
    cat = Category(name="日用品", monthly=False)
    session.add(cat)
    session.commit()
    session.refresh(cat)

    sts = []
    for i, day in enumerate((SEP, OCT)):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=day,
                     amount=30_000 + i, payer_id=a.id, category_id=cat.id)
        if i == 0:
            # 收入和转账也归在这张上：列表那个数是「支出合计」，它俩不许混进去
            create_entry(session, actor_id=b.id, kind=EntryKind.income, on=day,
                         amount=-2_000, payer_id=b.id)
            create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=day,
                         amount=1_500, payer_id=b.id, to_member_id=a.id)
        sts.append(cut_statement(session, actor_id=a.id))
    # 把第一张的方案转掉一部分，让两张的结清状态不一样
    plan = (sts[0].snapshot_json or {})["transfers"]
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=OCT,
                 amount=plan[0]["amount"], payer_id=plan[0]["from_id"], to_member_id=plan[0]["to_id"])

    totals = list_totals(session)
    assert totals[sts[0].id] == 30_000, "收入、转账混进了支出合计"
    settled = list_settled(session, sts)
    for st in sts:
        expense = sum(e.amount_jpy for e in entries_of(session, st.id) if e.kind == EntryKind.expense)
        assert totals.get(st.id, 0) == expense, st.id
        assert settled[st.id] == settlement_progress(session, st)["settled"], st.id
    # 至少有一张没结清，否则这条用例等于什么都没验
    assert not all(settled.values())


def test_small_cut_does_not_reset_the_monthly_clock(session: Session, members) -> None:
    """月中结过一次「不含固定费」的小账，月底那次正经出账照样默认带上固定费。

    原来「距上次出账几天」量的是最近一张，小账才过三天，月底那次就默认不勾
    「包括固定费」（审计 integrity-4）。
    """
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    full = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT, amount=2_000, payer_id=a.id)
    small = cut_statement(session, actor_id=a.id, include_monthly=False)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT, amount=3_000, payer_id=a.id)

    full.cut_at = now_utc() - dt.timedelta(days=25)
    small.cut_at = now_utc() - dt.timedelta(days=3)
    session.add_all([full, small])
    session.commit()

    draft = build_bill(session, None)
    assert draft["days_since_prev_cut"] == 25
    assert draft["suggest_monthly"] is True


def test_the_opening_balance_is_read_in_one_statement(session: Session, members) -> None:
    """上期结转必须**一条 SQL 数完** —— 一条语句才是一个快照。

    分成「垫付」「应担」两条 SELECT 的话它们各取各的最新状态（pysqlite 不为 SELECT
    开事务）。别人在这两条之间改了一笔已出账的账，这边就数到了新的垫付、旧的应担，
    算出一本不平的账，GET /api/bill 当场 500。
    实测：旧写法在「一边改已出账的账、一边看账单」6 秒里 3582 次读炸了 248 次，
    改成一条 UNION ALL 之后 3420 次读 0 次。这里钉的就是「别再拆回两条」。
    """
    from sqlalchemy import event

    a, *_ = members
    cat = Category(name="日用品", monthly=False)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    for i in range(3):
        create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=1000 + i, payer_id=a.id, category_id=cat.id)
    cut_statement(session, actor_id=a.id, label="上一期", on=SEP)

    seen: list[str] = []
    bind = session.get_bind()

    def _count(conn, cursor, statement, *args):  # noqa: ANN001, ARG001
        seen.append(statement)

    event.listen(bind, "before_cursor_execute", _count)
    try:
        opening = _opening(session, None)
    finally:
        event.remove(bind, "before_cursor_execute", _count)

    assert opening, "这一期之前确实有账，结转不该是空的"
    # 一条数 statement 的（_earlier_ids，草稿时不查）+ 一条数钱的
    assert len(seen) == 1, "\n---\n".join(seen)


def test_an_old_bill_tells_you_what_is_still_owed_right_now(session: Session, members) -> None:
    """已出账那张单子要同时说两件事：**当初**的方案，和**此刻**还该转多少。

    少了后者，界面只能拿冻结方案当行动指示 —— 于是：
      * 已经还清的人被继续命令「你要给 Zen ¥10,000」，他真会再转一次；
      * 出账后大家换了条路结清（现金、经第三人），冻结方案里那一对再也不走钱，
        而「确认已完成」按钮还亮着 —— 按一下凭空造一笔债。
    """
    a, b, c_ = members
    cat = Category(name="日用品", monthly=False)
    session.add(cat)
    session.commit()
    session.refresh(cat)
    create_entry(session, actor_id=c_.id, kind=EntryKind.expense, on=SEP,
                 amount=30_000, payer_id=c_.id, category_id=cat.id)
    st = cut_statement(session, actor_id=a.id, label="上一期", on=SEP)

    frozen = build_bill(session, st)
    assert {(t["from_id"], t["to_id"], t["amount"]) for t in frozen["transfers"]} == {
        (a.id, c_.id, 10_000), (b.id, c_.id, 10_000)
    }
    # 一分没转时，此刻 = 当初
    assert frozen["live_transfers"] == frozen["transfers"]

    # a 还了一半
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP,
                 amount=4_000, payer_id=a.id, to_member_id=c_.id)
    now = build_bill(session, st)
    assert now["transfers"][0]["amount"] == 10_000, "当初那份方案不许变"
    live = {(t["from_id"], t["to_id"]): t["amount"] for t in now["live_transfers"]}
    assert live[(a.id, c_.id)] == 6_000, "此刻只该再转 6,000"
    assert now["live_closing"][a.id] == -6_000

    # b 的钱**绕 a 还了**（现金/并单转都是这个形状）：冻结方案里 b→c 那一对
    # 从此再也不会走钱，此刻的方案里它必须消失，否则按钮会叫 b 再转一次
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP,
                 amount=10_000, payer_id=b.id, to_member_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP,
                 amount=10_000, payer_id=a.id, to_member_id=c_.id)
    after = build_bill(session, st)
    live = {(t["from_id"], t["to_id"]): t["amount"] for t in after["live_transfers"]}
    assert live.get((b.id, c_.id), 0) == 0, "b 已经不欠 c 了，此刻的方案里不许还有这一对"
    assert after["live_closing"][b.id] == 0
    assert after["transfers"][1]["amount"] == 10_000, "当初那份方案还是不许变"


def test_help_buy_is_an_expense_borne_by_one_other_person(session: Session, members) -> None:
    """帮买：Go 付钱、全算 Kan 的。钱照支出算（Kan 的应担多了、Go 的垫付多了），
    合计照算，但要单列出来 —— 不然群里看账单的人不知道 Kan 那份为什么多了 3,200"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=9_000, payer_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_200, payer_id=a.id,
                 title="洗发水", member_ids=[b.id], rule={"mode": "ratio", "weights": {str(b.id): 1}})
    bill = build_bill(session, None)

    assert bill["total_expense"] == 12_200
    assert bill["help_total"] == 3_200
    assert bill["help_items"] == [
        {"entry_id": bill["help_items"][0]["entry_id"], "payer_id": a.id, "for_id": b.id,
         "amount": 3_200, "title": "洗发水"}
    ]
    assert row_of(bill, b.id)["owed"] == 3_000 + 3_200
    assert row_of(bill, a.id)["paid"] == 12_200
    assert sum(r["closing"] for r in bill["members"]) == 0


def test_not_every_uneven_split_is_a_help_buy(session: Session, members) -> None:
    """付款人自己也担一份、或者全算在两个人头上的，都是普通支出，不叫帮买"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id,
                 member_ids=[a.id, b.id], rule={"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1}})
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id,
                 member_ids=[b.id, c.id], rule={"mode": "ratio", "weights": {str(b.id): 1, str(c.id): 1}})
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP, amount=500,
                 payer_id=b.id, to_member_id=a.id)
    # 只有付款人自己担：自己买自己用的
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=800, payer_id=a.id,
                 member_ids=[a.id], rule={"mode": "ratio", "weights": {str(a.id): 1}})
    bill = build_bill(session, None)
    assert bill["help_items"] == [] and bill["help_total"] == 0


def test_help_buy_counts_rows_borne_by_nobody_but_not_fixed_costs(session: Session, members) -> None:
    """在支出页把另外两人点成「不参与」记的（他们那两行是 0）也认作帮买；
    但挂在固定费上的不认 —— 「Kan 的车位」从 Go 卡上扣，固定费那块已经列着它了"""
    a, b, c = members
    parking = Category(name="车位", monthly=True)
    session.add(parking)
    session.commit()
    rule = {"mode": "ratio", "weights": {str(a.id): 0, str(b.id): 1, str(c.id): 0}}
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=2_000, payer_id=a.id,
                 member_ids=[a.id, b.id, c.id], rule=rule)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=8_000, payer_id=a.id,
                 category_id=parking.id, member_ids=[a.id, b.id, c.id], rule=rule)
    bill = build_bill(session, None)
    assert [(h["for_id"], h["amount"]) for h in bill["help_items"]] == [(b.id, 2_000)]
    assert bill["help_total"] == 2_000


# ------------------------------------------------ 两台手机同时出账（#5，出账那一半）


def test_cutting_with_a_stale_view_of_the_last_bill_cuts_nothing(session: Session, members) -> None:
    """对话框打开时看到的「最近一张」已经不是最近一张了 ＝ 刚有人出过账。
    后到的这一下不许再出一张（多半只剩被它自己的照上期记进来的房租）。"""
    a, *_ = members
    rent = Category(name="房租", monthly=True)
    session.add(rent)
    session.commit()
    session.refresh(rent)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    first = cut_statement(session, actor_id=a.id, after_statement_id=0)        # 头一张：看到的是「没出过」
    late = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=120_000,
                        payer_id=a.id, category_id=rent.id)

    with pytest.raises(BillError) as e:
        cut_statement(session, actor_id=a.id, after_statement_id=0)            # 还拿着出账前那一份
    assert e.value.code == "bill_changed" and e.value.detail["latest"] == first.id
    assert len(list(session.exec(select(Statement)))) == 1, "一张都不许多出"
    session.refresh(late)
    assert late.statement_id is None and late.date == SEP, "固定费的日期也不许被盖"

    second = cut_statement(session, actor_id=a.id, after_statement_id=first.id)
    assert second.id != first.id
    # 不带这个参数（旧前端）照旧能出
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=500, payer_id=a.id)
    cut_statement(session, actor_id=a.id)


def test_cut_endpoint_takes_the_view_it_was_opened_with(client, auth, session, members) -> None:
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    r = client.post("/api/statements?after_statement_id=7", headers=auth)
    assert r.status_code == 409 and r.json()["code"] == "bill_changed"
    assert client.get("/api/statements", headers=auth).json() == []
    seen = client.get("/api/bill", headers=auth).json()["prev_statement_id"]
    assert client.post(f"/api/statements?after_statement_id={seen}", headers=auth).status_code == 201


# ------------------------------------------- 出账时刻在写锁之内盖（#41）


def test_an_edit_committed_just_before_the_cut_does_not_flag_the_new_bill(
    session: Session, members, monkeypatch
) -> None:
    """出账时刻原来在锁外取：正好有人在改一笔草稿，他的审计时间晚于这个时刻、却先拿到锁提交了 ——
    刚出的账单永久挂着「出账后被改过 1 处：当初 ¥9,000，现在 ¥9,000」。
    这里把「锁外取的那个时刻」钉成比那条审计早 1ms，模拟那次交错。"""
    from app.models import AuditLog
    from app.services import bill as bill_mod

    a, *_ = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=9_000, payer_id=a.id)
    update_entry(session, e, actor_id=a.id, version=e.version, fields={"amount_jpy": 13_000})
    edited_at = session.exec(select(AuditLog.at).where(AuditLog.action == "update")).one()

    early = iter([edited_at - dt.timedelta(milliseconds=1)])
    monkeypatch.setattr(bill_mod, "now_utc", lambda: next(early, None) or now_utc())
    st = cut_statement(session, actor_id=a.id)
    assert st.cut_at > edited_at
    assert build_bill(session, st)["edited_after_cut"] is None


# ---------------------------------------------- 出账后被改过：说清楚改了什么（#12 / #20）


def test_edited_after_cut_says_who_changed_what_and_by_how_much(session: Session, members) -> None:
    """只改分摊的话，「当初 ¥30,000，现在 ¥30,000」什么都没说。逐人给出当初 / 现在的结余，
    逐笔给出改了哪笔、前后金额、谁改的（出账后动过它的所有人）。"""
    a, b, c = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    gone = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=900, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)

    rule = {"mode": "ratio", "weights": {str(a.id): 1, str(b.id): 1, str(c.id): 1},
            "adjustments": {str(b.id): 3_000, str(c.id): -3_000}}
    e = update_entry(session, e, actor_id=b.id, version=e.version, fields={}, rule=rule)
    e = update_entry(session, e, actor_id=c.id, version=e.version, fields={"title": "超市"})
    e = update_entry(session, e, actor_id=b.id, version=e.version, fields={"title": "超市 2"})
    delete_entry(session, gone, actor_id=c.id)

    flagged = build_bill(session, st)["edited_after_cut"]
    assert flagged["count"] == 2 and flagged["from_earlier"] is False
    by_id = {x["entry_id"]: x for x in flagged["entries"]}
    assert by_id[e.id] == {"entry_id": e.id, "title": "超市 2", "category_id": None,
                           "before_amount": 30_000, "after_amount": 30_000, "deleted": False,
                           "by": [b.id, c.id]}
    assert by_id[gone.id]["deleted"] is True and by_id[gone.id]["by"] == [c.id]
    moved = {m["member_id"]: (m["frozen_closing"], m["live_closing"]) for m in flagged["members"]}
    assert moved == {a.id: (20_600, 20_000), b.id: (-10_300, -13_000), c.id: (-10_300, -7_000)}
    assert flagged["sources"] == []


def test_a_later_bill_names_the_earlier_one_that_was_edited(session: Session, members) -> None:
    """更早那张被改，后面每张都挂签 —— 得说出是哪张。改了又改回的那张不算来源。"""
    a, b, c = members
    e1 = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id)
    s1 = cut_statement(session, actor_id=a.id)
    e2 = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=6_000, payer_id=b.id)
    s2 = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_500, payer_id=c.id)
    s3 = cut_statement(session, actor_id=a.id)

    e1 = update_entry(session, e1, actor_id=a.id, version=e1.version, fields={"amount_jpy": 4_000})
    update_entry(session, e1, actor_id=a.id, version=e1.version, fields={"amount_jpy": 3_000})   # 改回去
    update_entry(session, e2, actor_id=b.id, version=e2.version, fields={"amount_jpy": 9_000})

    third = build_bill(session, s3)["edited_after_cut"]
    assert third["from_earlier"] is True and third["count"] == 0
    assert third["sources"] == [s2.id], "s1 那笔改了又改回，不是来源"
    assert build_bill(session, s1)["edited_after_cut"] is None


def test_drift_between_two_people_who_already_left_still_flags_the_bill(session: Session, members) -> None:
    """出账时已经搬走又结清的两个人不占快照的行。原来只比快照里有的人：他俩之间一笔旧账被改，
    这张会凭空多出两行而不标。成员取并集、缺的按 0（#12）。"""
    a, b, c = members
    help_buy = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000,
                            payer_id=a.id, member_ids=[c.id], rule={"mode": "ratio", "weights": {str(c.id): 1}})
    create_entry(session, actor_id=c.id, kind=EntryKind.settlement, on=SEP, amount=3_000,
                 payer_id=c.id, to_member_id=a.id)
    s1 = cut_statement(session, actor_id=a.id)
    for m in (a, c):
        m.left_on = SEP
        session.add(m)
    session.commit()
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP + dt.timedelta(days=1),
                 amount=700, payer_id=b.id)
    s2 = cut_statement(session, actor_id=b.id)
    assert [r["member_id"] for r in s2.snapshot_json["members"]] == [b.id]

    update_entry(session, help_buy, actor_id=b.id, version=help_buy.version, fields={"amount_jpy": 4_000})
    flagged = build_bill(session, s2)["edited_after_cut"]
    assert flagged is not None and flagged["from_earlier"] is True
    assert {m["member_id"]: (m["frozen_closing"], m["live_closing"]) for m in flagged["members"]} == {
        a.id: (0, 1_000), c.id: (0, -1_000),
    }
    assert flagged["sources"] == [s1.id]


# ------------------------------------------------ 审计里的来历（#46）


def test_cut_and_confirm_leave_their_traces_in_the_audit(session: Session, members) -> None:
    """出账把固定费的日期盖成出账日（D30）：原来是哪天、盖了哪几笔，记在出账那一条里 ——
    不给每笔另写 update（那条的时间晚于出账，每张都会挂上「出账后被改过」）。
    「确认已完成」记的转账，审计里写明是在哪张单子上、看到还差多少时点的。"""
    from app.models import AuditLog
    from app.services.bill import confirm_transfer

    a, b, _ = members
    rent = Category(name="房租", monthly=True)
    session.add(rent)
    session.commit()
    session.refresh(rent)
    early = dt.date(2026, 9, 1)
    fixed = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=early, amount=90_000,
                         payer_id=a.id, category_id=rent.id)
    st = cut_statement(session, actor_id=a.id, on=SEP)
    cut_log = session.exec(select(AuditLog).where(AuditLog.action == "cut_statement")).one()
    assert cut_log.after_json["stamped"] == {str(fixed.id): early.isoformat()}
    assert build_bill(session, st)["edited_after_cut"] is None

    t = build_bill(session, st)["transfers"][0]
    made = confirm_transfer(session, statement=st, from_id=t["from_id"], to_id=t["to_id"],
                            amount=t["amount"], expect_left=t["amount"], on=SEP, actor_id=b.id)
    log = session.exec(select(AuditLog).where(AuditLog.target_id == made.id, AuditLog.action == "create")).one()
    assert log.after_json["via"] == {"kind": "confirm", "statement_id": st.id, "expect_left": t["amount"]}


# ------------------------------------------------ 账不平时：两种模式一个样（#25）


def _break_one_share(session: Session, entry_id: int) -> None:
    from app.models import EntryShare

    share = session.exec(select(EntryShare).where(EntryShare.entry_id == entry_id)).first()
    share.amount_jpy += 1
    session.add(share)
    session.commit()


@pytest.mark.parametrize("simplify", [True, False])
def test_a_broken_entry_is_named_in_the_log_in_both_settlement_modes(
    session: Session, members, simplify: bool
) -> None:
    """一笔分摊合计 ≠ 金额的坏账：最少转账模式原来 500、只报一个总数；按原始债权模式原来照常 200，
    每人结余加起来不是 0、转账方案也加不平，悄悄错着。现在两种都 500，日志里点名是哪一笔。"""
    import logging

    from app.core.settle import SettleError

    a, *_ = members
    settings_svc.set_(session, "simplify_debts", simplify)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=900, payer_id=a.id)
    bad = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=3_000, payer_id=a.id)
    _break_one_share(session, bad.id)

    seen: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: seen.append(record.getMessage())   # type: ignore[method-assign]
    log = logging.getLogger("nagaya")
    log.addHandler(handler)
    try:
        with pytest.raises(SettleError):
            build_bill(session, None)
    finally:
        log.removeHandler(handler)
    assert any(f"[{bad.id}]" in m for m in seen), seen


# ------------------------------------------------ 已出账单的上期结转 / 每人结余（#10）


def _rows(bill: dict, ids: list[int], key: str) -> list[int]:
    """每人那一列；搬走且结清的人不占行，按 0 算"""
    by = {r["member_id"]: r[key] for r in bill["members"]}
    return [by.get(i, 0) for i in ids]


def test_issued_bills_carry_forward_through_a_delete_and_a_restore(session: Session, members) -> None:
    """三张账单，中间删掉第一张里的一笔、出第三张之前又恢复它，最后再删一笔第二张的：
    逐人钉住每张的上期结转、结余、此刻余额，和草稿的上期结转。

    原来断言 opening 的只有草稿那两处：已出账单的 opening 把自己和后面几张也算进去、
    或者草稿的结转把**删掉的**账也算上，全套照样全绿 —— 每人结余加起来照样是 0。"""
    a, b, c = members
    ids = [a.id, b.id, c.id]
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    e2 = create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=SEP, amount=6_000, payer_id=b.id)
    s1 = cut_statement(session, actor_id=a.id)
    delete_entry(session, e2, actor_id=a.id)
    e3 = create_entry(session, actor_id=c.id, kind=EntryKind.expense, on=OCT, amount=9_000, payer_id=c.id)
    s2 = cut_statement(session, actor_id=a.id)
    restore_entry(session, e2, actor_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.expense, on=OCT, amount=3_000, payer_id=b.id)
    s3 = cut_statement(session, actor_id=a.id)
    delete_entry(session, e3, actor_id=a.id)

    want = {
        s1.id: ([0, 0, 0], [18_000, -6_000, -12_000]),
        s2.id: ([18_000, -6_000, -12_000], [18_000, -6_000, -12_000]),     # 它自己那笔删了
        s3.id: ([18_000, -6_000, -12_000], [17_000, -4_000, -13_000]),
    }
    now = [17_000, -4_000, -13_000]
    assert [balances(session)[i] for i in ids] == now
    for st in (s1, s2, s3):
        bill = build_bill(session, st)
        assert (_rows(bill, ids, "opening"), _rows(bill, ids, "closing")) == want[st.id], st.id
        assert [bill["live_closing"][i] for i in ids] == now, st.id
    draft = build_bill(session, None)
    assert _rows(draft, ids, "opening") == now, "草稿的上期结转 ＝ 全部没删的出过账的账"
    assert [draft["live_closing"][i] for i in ids] == now


# ------------------------------------------------ 出账前的预付不算进度（#32）


def test_transfers_before_the_cut_are_prepayment_not_progress(session: Session, members) -> None:
    """出账之前记的转账已经进了这张单子自己的「已预付」（方案因此只剩 6,000），
    结算进度只认**出账之后**的转账 —— 两边不重不漏。

    这条下界原来没人钉：删掉之后预付被算两遍，屏幕叫 B 只转 2,000（少 4,000），
    账单还会提前亮「已结清」。列表那份（list_settled）有自己的一份下界，一起钉。"""
    from app.services.bill import list_settled, pair_left

    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=30_000, payer_id=a.id)
    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=SEP, amount=4_000,
                 payer_id=b.id, to_member_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    plan = {(t["from_id"], t["to_id"]): t["amount"] for t in st.snapshot_json["transfers"]}
    assert plan == {(b.id, a.id): 6_000, (c.id, a.id): 10_000}

    bill = build_bill(session, st)
    assert bill["settled_paid"] == [0, 0] and bill["settled"] is False
    assert pair_left(session, st, b.id, a.id) == 6_000
    assert list_settled(session, [st])[st.id] is False

    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=OCT, amount=2_000,
                 payer_id=b.id, to_member_id=a.id)
    create_entry(session, actor_id=c.id, kind=EntryKind.settlement, on=OCT, amount=10_000,
                 payer_id=c.id, to_member_id=a.id)
    assert build_bill(session, st)["settled"] is False, "B 只转了 6,000 里的 2,000"
    assert list_settled(session, [st])[st.id] is False
    assert balances(session)[b.id] == -4_000


# ------------------------------------------------ 显示上的几个边界（#79）


def test_covers_from_reaches_back_to_a_backdated_entry(session: Session, members) -> None:
    """改日期改到上次出账之前的（补录、回收站里捞回来的），覆盖期从它算起 ——
    否则账单顶上是「10/29 〜 9/01」这种头尾颠倒的区间"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=jst_date(st.cut_at),
                     amount=2_000, payer_id=a.id)
    assert build_bill(session, None)["covers_from"] == jst_date(st.cut_at).isoformat()
    early = dt.date(2026, 8, 3)
    update_entry(session, e, actor_id=a.id, version=e.version, fields={"date": early})
    assert build_bill(session, None)["covers_from"] == early.isoformat()


def test_suggest_monthly_flips_exactly_at_the_threshold(session: Session, members) -> None:
    """「距上次出账**不足** N 天」才默认不勾：正好 N 天就该勾上（D29）。按日本时间的自然日数"""
    a, *_ = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=1_000, payer_id=a.id)
    st = cut_statement(session, actor_id=a.id)
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=OCT, amount=2_000, payer_id=a.id)
    n = int(settings_svc.get(session, "monthly_gap_days"))

    def after(days: int) -> dict:
        st.cut_at = now_utc() - dt.timedelta(days=days)
        session.add(st)
        session.commit()
        return build_bill(session, None)

    assert after(n)["days_since_prev_cut"] == n and after(n)["suggest_monthly"] is True
    assert after(n - 1)["suggest_monthly"] is False


# ------------------------------------------------ 帮买：前后端跑同一份用例（#83）

_HELP_BUY = json.loads(
    (Path(__file__).parents[2] / "tests" / "fixtures" / "help_buy_cases.json").read_text(encoding="utf-8")
)["cases"]


def test_the_help_buy_fixture_is_not_empty() -> None:
    assert len(_HELP_BUY) > 5


@pytest.mark.parametrize("case", _HELP_BUY, ids=[c["name"] for c in _HELP_BUY])
def test_help_buy_matches_the_shared_fixture(case: dict) -> None:
    """help_buy_for 和前端 helpBuyFor 跑这同一份（tests/fixtures/help_buy_cases.json）。
    原来两边各手抄一份镜像用例、只靠注释同步：加一条规则只改一边，另一边照样绿"""
    from app.services.bill import help_buy_for

    got = help_buy_for(
        EntryKind(case["kind"]), case["payer_id"], {int(k): v for k, v in case["shares"].items()},
        fixed_cost=case.get("fixed_cost", False),
    )
    assert got == case["expected"]
