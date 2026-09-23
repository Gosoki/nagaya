"""结算方案回归 —— SPEC §4.5 与 §8 的硬性验收。"""

from __future__ import annotations

import random

import pytest

from app.core.settle import (
    SettleError,
    Transfer,
    plan_pairwise,
    plan_simplified,
)


def apply_transfers(balances: dict[int, int], transfers: list[Transfer]) -> dict[int, int]:
    """把方案套到余额上，用来验「执行完是不是真归零」。"""
    out = dict(balances)
    for t in transfers:
        out[t.from_id] = out.get(t.from_id, 0) + t.amount
        out[t.to_id] = out.get(t.to_id, 0) - t.amount
    return out


def test_three_people_two_transfers() -> None:
    """A 垫了钱，B、C 各还一笔 —— 3 个人最多 2 笔。"""
    balances = {1: 80_000, 2: -40_000, 3: -40_000}
    plan = plan_simplified(balances)
    assert len(plan) == 2
    assert set(plan) == {Transfer(2, 1, 40_000), Transfer(3, 1, 40_000)}
    assert all(v == 0 for v in apply_transfers(balances, plan).values())


def test_already_settled_needs_no_transfer() -> None:
    assert plan_simplified({1: 0, 2: 0, 3: 0}) == []


def test_rejects_unbalanced_input() -> None:
    """合计不为 0 说明账本已经坏了，这时候给方案只会把错误扩散出去。"""
    with pytest.raises(SettleError) as exc:
        plan_simplified({1: 100, 2: -50})
    assert exc.value.code == "unbalanced"


def test_at_most_n_minus_1_transfers_and_always_zeroes_out() -> None:
    """∀ 随机余额：笔数 ≤ n−1，执行后全体归零。"""
    rng = random.Random(20260921)
    for _ in range(500):
        n = rng.randint(2, 6)
        members = list(range(1, n + 1))
        values = [rng.randint(-200_000, 200_000) for _ in members[:-1]]
        values.append(-sum(values))            # 强行配平
        balances = dict(zip(members, values))

        plan = plan_simplified(balances)
        assert len(plan) <= n - 1, (balances, plan)
        assert all(t.amount > 0 for t in plan), plan
        assert all(v == 0 for v in apply_transfers(balances, plan).values()), (balances, plan)


def test_deterministic() -> None:
    """同样的余额必须永远给出同样的方案，否则每次刷新转账对象都在变。"""
    balances = {1: 50_000, 2: 50_000, 3: -30_000, 4: -70_000}
    assert plan_simplified(balances) == plan_simplified(dict(reversed(list(balances.items()))))


def test_pairwise_keeps_original_creditors() -> None:
    """按原始债权：B 欠 A，C 欠 A，各还各的，不会让 B 去还给 C。"""
    pair_debts = {(2, 1): 40_000, (3, 1): 40_000}
    plan = plan_pairwise(pair_debts)
    assert set(plan) == {Transfer(2, 1, 40_000), Transfer(3, 1, 40_000)}


def test_pairwise_nets_mutual_debts() -> None:
    """A 欠 B 5000、B 又欠 A 3000 → 只转净额 2000 那一笔。"""
    plan = plan_pairwise({(1, 2): 5_000, (2, 1): 3_000})
    assert plan == [Transfer(1, 2, 2_000)]


def test_pairwise_drops_fully_offset_pairs() -> None:
    assert plan_pairwise({(1, 2): 5_000, (2, 1): 5_000}) == []


def test_simplified_never_more_transfers_than_pairwise() -> None:
    """最少转账的卖点就是笔数不会更多。"""
    pair_debts = {(2, 1): 30_000, (3, 1): 20_000, (3, 2): 15_000, (1, 3): 5_000}
    balances: dict[int, int] = {}
    for (debtor, creditor), amount in pair_debts.items():
        balances[debtor] = balances.get(debtor, 0) - amount
        balances[creditor] = balances.get(creditor, 0) + amount
    assert len(plan_simplified(balances)) <= len(plan_pairwise(pair_debts))
