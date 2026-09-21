"""账本服务回归 —— SPEC §5 / §4.6 / §8 的硬性验收。"""

from __future__ import annotations

import datetime as dt
import random

import pytest
from sqlmodel import Session, select

from app.models import Entry, EntryKind, EntryShare, Member
from app.services import settings as settings_svc
from app.services.ledger import LedgerError, balances, create_entry

SEP = dt.date(2026, 9, 10)


def shares_of(session: Session, entry_id: int) -> dict[int, int]:
    rows = session.exec(select(EntryShare).where(EntryShare.entry_id == entry_id)).all()
    return {r.member_id: r.amount_jpy for r in rows}


def test_expense_splits_and_persists_snapshot(session, members) -> None:
    a, b, c = members
    e = create_entry(
        session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
        amount=10_000, payer_id=a.id, title="日用品",
    )
    s = shares_of(session, e.id)
    assert sum(s.values()) == 10_000
    assert s == {a.id: 3334, b.id: 3333, c.id: 3333}   # 余数跟着付款人 a


def test_balances_sum_to_zero(session, members) -> None:
    """∀ 时刻，Σ 全体余额 == 0。随机 80 笔也不许破。"""
    rng = random.Random(20260921)
    for i in range(80):
        kind = rng.choice([EntryKind.expense, EntryKind.expense, EntryKind.income])
        amount = rng.randint(1, 200_000)
        create_entry(
            session, actor_id=None, kind=kind, on=SEP,
            amount=amount if kind == EntryKind.expense else -amount,
            payer_id=rng.choice(members).id,
        )
        assert sum(balances(session).values()) == 0, f"第 {i} 笔之后就不平了"


def test_settlement_zeroes_out_the_debt(session, members) -> None:
    """A 垫 120000 三人平分 → B 把钱还给 A → B 归零、A 少收那么多。"""
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id, title="房租")
    before = balances(session)
    assert before[a.id] == 80_000 and before[b.id] == -40_000

    create_entry(session, actor_id=b.id, kind=EntryKind.settlement, on=dt.date(2026, 10, 15),
                 amount=40_000, payer_id=b.id, to_member_id=a.id)
    after = balances(session)
    assert after[b.id] == 0
    assert after[a.id] == 40_000
    assert sum(after.values()) == 0


def test_income_flips_the_direction(session, members) -> None:
    """返现 3000 进了 A 的卡、三人平分 → A 欠 B、C 各 1000。"""
    a, b, c = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.income, on=SEP,
                     amount=-3_000, payer_id=a.id, title="电费返现")
    assert shares_of(session, e.id) == {a.id: -1000, b.id: -1000, c.id: -1000}
    bal = balances(session)
    assert bal[a.id] == -2_000 and bal[b.id] == 1_000 and bal[c.id] == 1_000


def test_fourth_member_does_not_touch_history(session, members) -> None:
    """**整个设计里最重要的一条**：第 4 个人搬进来，历史账一个数字都不许变。"""
    a, b, c = members
    old = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=10_000, payer_id=a.id)
    snapshot = shares_of(session, old.id)

    d = Member(name="d", display_name="D", display_order=3, joined_on=dt.date(2026, 10, 1))
    session.add(d)
    session.commit()
    session.refresh(d)

    assert shares_of(session, old.id) == snapshot           # 历史纹丝不动
    assert d.id not in shares_of(session, old.id)

    new = create_entry(session, actor_id=a.id, kind=EntryKind.expense,
                       on=dt.date(2026, 10, 5), amount=10_000, payer_id=a.id)
    assert len(shares_of(session, new.id)) == 4             # 新账才 4 个人分
    assert sum(shares_of(session, new.id).values()) == 10_000


def test_changing_default_rule_does_not_touch_history(session, members) -> None:
    """SPEC §4.7：改第 1 层默认值，只影响之后新建的账。"""
    a, b, c = members
    old = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=9_000, payer_id=a.id)
    snapshot = shares_of(session, old.id)

    settings_svc.set_(session, "default_rule",
                      {"mode": "ratio", "weights": {str(a.id): 2, str(b.id): 1, str(c.id): 0}})

    assert shares_of(session, old.id) == snapshot
    new = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                       amount=9_000, payer_id=a.id)
    assert shares_of(session, new.id) == {a.id: 6_000, b.id: 3_000, c.id: 0}


def test_category_rule_beats_global(session, members) -> None:
    a, b, c = members
    e = create_entry(
        session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
        amount=120_000, payer_id=a.id, title="房租",
        category_rule={"mode": "exact", "exact": {str(a.id): 45_000, str(b.id): 40_000, str(c.id): 35_000}},
    )
    assert shares_of(session, e.id) == {a.id: 45_000, b.id: 40_000, c.id: 35_000}


def test_entry_rule_beats_category(session, members) -> None:
    a, b, c = members
    e = create_entry(
        session, actor_id=a.id, kind=EntryKind.expense, on=SEP, amount=9_000, payer_id=a.id,
        rule={"mode": "ratio", "equal_weight": 1, "adjustments": {str(a.id): -1000, str(b.id): 500}},
        category_rule={"mode": "exact", "exact": {str(a.id): 9_000}},
    )
    assert shares_of(session, e.id) == {a.id: 2167, b.id: 3667, c.id: 3166}   # SPEC §4.2 的例子


def test_settlement_lands_in_the_current_draft(session, members) -> None:
    """转账和别的账一样，进当前这张还没出的草稿账单。

    不再有「挂到最早的未关账账期」这种规则 —— 线是点出账单时划的，
    在那之前记的一切都在同一张草稿上。
    """
    a, b, c = members
    create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                 amount=120_000, payer_id=a.id)
    s_ = create_entry(session, actor_id=b.id, kind=EntryKind.settlement,
                      on=dt.date(2026, 10, 15), amount=40_000, payer_id=b.id, to_member_id=a.id)
    assert s_.statement_id is None          # 还没出账
    assert balances(session)[b.id] == 0     # 但钱已经算清了


def test_editing_a_billed_entry_self_corrects(session, members) -> None:
    """已出账的账目也随便改，钱不会算错。

    余额全局累计，差额会原样出现在下一张账单的「上期结转」里 ——
    多付了就在下张扣回来，少付了就补上，不需要任何锁。
    """
    from app.services.bill import cut_statement
    from app.services.ledger import update_entry

    a, b, c = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=9_000, payer_id=a.id)
    cut_statement(session, actor_id=a.id)
    assert e.statement_id is not None

    update_entry(session, e, actor_id=a.id, version=e.version,
                 fields={"amount_jpy": 12_000})
    assert sum(balances(session).values()) == 0
    assert balances(session)[a.id] == 8_000     # 12000 − 4000


@pytest.mark.parametrize(
    "kind,amount",
    [
        (EntryKind.expense, -100),
        (EntryKind.income, 100),
        (EntryKind.settlement, -100),
        (EntryKind.expense, 0),
    ],
)
def test_sign_validation(session, members, kind, amount) -> None:
    a, b, _ = members
    with pytest.raises(LedgerError) as exc:
        create_entry(session, actor_id=a.id, kind=kind, on=SEP, amount=amount,
                     payer_id=a.id, to_member_id=b.id)
    assert exc.value.code in {"bad_sign", "zero_amount"}


def test_cannot_transfer_to_self(session, members) -> None:
    a, *_ = members
    with pytest.raises(LedgerError) as exc:
        create_entry(session, actor_id=a.id, kind=EntryKind.settlement, on=SEP,
                     amount=1_000, payer_id=a.id, to_member_id=a.id)
    assert exc.value.code == "self_transfer"


def test_member_who_left_is_not_in_new_entries(session, members) -> None:
    """退出的人不删，但新账不再算他。"""
    a, b, c = members
    c.left_on = dt.date(2026, 8, 31)
    session.add(c)
    session.commit()

    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=10_000, payer_id=a.id)
    s = shares_of(session, e.id)
    assert c.id not in s
    assert sum(s.values()) == 10_000


def test_audit_log_written(session, members) -> None:
    from app.models import AuditLog
    a, *_ = members
    e = create_entry(session, actor_id=a.id, kind=EntryKind.expense, on=SEP,
                     amount=1_000, payer_id=a.id)
    logs = session.exec(select(AuditLog)).all()
    assert len(logs) == 1
    assert logs[0].action == "create" and logs[0].target_id == e.id
    assert logs[0].after_json["shares"]
