"""分摊引擎回归 —— SPEC §7.3。

三层保护：
    1. 跑 tests/fixtures/split_cases.json（前端 vitest 跑的是同一份）
    2. 属性测试：随机 1000 组，断言 Σ shares == amount 恒成立
    3. AST 扫描：金额路径上不许出现 float 字面量或真除法
"""

from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import pytest

from app.core import split as split_mod
from app.core.split import SplitError, split

FIXTURE = Path(__file__).parents[2] / "tests" / "fixtures" / "split_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _rule(case: dict) -> dict:
    if case["mode"] == "exact":
        return {"mode": "exact", "exact": case["exact"]}
    return {
        "mode": "ratio",
        "weights": case["weights"],
        "adjustments": case.get("adjustments", {}),
        "remainder_to": case.get("remainder_to", "payer"),
    }


def _run(case: dict) -> dict[str, int]:
    return split(
        _rule(case),
        case["amount"],
        order=case["order"],
        payer=case.get("payer"),
        rotate_seed=case.get("rotate_seed", 0),
    )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_case(case: dict) -> None:
    """共享 fixture：每一条的结果必须逐円吻合。"""
    if "expect_error" in case:
        with pytest.raises(SplitError) as exc:
            _run(case)
        assert exc.value.code == case["expect_error"]
        if "expect_diff" in case:
            assert exc.value.detail["diff"] == case["expect_diff"]
        return

    shares = _run(case)
    assert shares == case["expected"]
    assert sum(shares.values()) == case["amount"]
    assert all(isinstance(v, int) for v in shares.values())


# ----------------------------------------------------------- 属性测试


def _random_input(rng: random.Random) -> dict:
    n = rng.randint(1, 5)
    order = [chr(ord("a") + i) for i in range(n)]
    weights = {m: rng.randint(0, 5) for m in order}
    if sum(weights.values()) == 0:  # 全 0 是另一条用例管的分支
        weights[rng.choice(order)] = 1
    adjustments = {m: rng.randint(-10_000, 10_000) for m in order if rng.random() < 0.4}
    return {
        "mode": "ratio",
        "amount": rng.randint(-1_000_000, 1_000_000),
        "order": order,
        "weights": weights,
        "adjustments": adjustments,
        "remainder_to": rng.choice(["payer", "order", "rotate"]),
        "payer": rng.choice(order),
        "rotate_seed": rng.randint(0, 100),
    }


def test_sum_always_equals_amount() -> None:
    """∀ 输入，Σ shares == amount。这是整个账本最硬的一条不变量。"""
    rng = random.Random(20260921)
    for _ in range(1000):
        case = _random_input(rng)
        shares = _run(case)
        assert sum(shares.values()) == case["amount"], case
        assert all(isinstance(v, int) for v in shares.values()), case


def test_zero_weight_member_only_pays_their_adjustment() -> None:
    """权重 0 ＝ 不参与：他身上只该有自己的调整额，不多一円。"""
    rng = random.Random(4649)
    for _ in range(200):
        case = _random_input(rng)
        case["weights"]["a"] = 0
        if sum(case["weights"].values()) == 0:
            case["weights"]["b" if len(case["order"]) > 1 else "a"] = 1
        if case["weights"]["a"] != 0:
            continue
        shares = _run(case)
        assert shares["a"] == case["adjustments"].get("a", 0), case


def test_equal_weights_differ_by_at_most_one_yen() -> None:
    """等权重且无调整额时，任意两人的份额最多差 1 円。"""
    rng = random.Random(1234)
    for _ in range(200):
        case = _random_input(rng)
        case["adjustments"] = {}
        case["weights"] = {m: 1 for m in case["order"]}
        shares = _run(case)
        assert max(shares.values()) - min(shares.values()) <= 1, case


def test_deterministic() -> None:
    """同样的输入必须每次都给同样的结果（否则历史账没法复算）。"""
    rng = random.Random(777)
    for _ in range(100):
        case = _random_input(rng)
        assert _run(case) == _run(case), case


def test_remainder_goes_to_payer_by_default() -> None:
    """默认规则：平局时那 1 円跟着付款人走。"""
    for payer in ("a", "b", "c"):
        shares = split(
            {"mode": "ratio", "weights": {"a": 1, "b": 1, "c": 1}},
            10_000,
            order=["a", "b", "c"],
            payer=payer,
        )
        assert shares[payer] == 3334
        assert sum(shares.values()) == 10_000


# ----------------------------------------------------------- 禁 float


def test_no_float_in_money_path() -> None:
    """AST 扫描：分摊引擎里不许有 float 字面量、float() 调用或真除法 `/`。

    用 AST 而不是 grep，是为了不被注释和文档字符串里的「float」误伤。
    """
    tree = ast.parse(Path(split_mod.__file__).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(f"第 {node.lineno} 行：float 字面量 {node.value!r}")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            offenders.append(f"第 {node.lineno} 行：真除法 `/`（要整数除法用 // 或 Fraction）")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            offenders.append(f"第 {node.lineno} 行：float() 调用")
    assert not offenders, "金额路径上出现了浮点：\n" + "\n".join(offenders)


# ------------------------------------------- 随机用例文件必须和当前实现同步

RANDOM_FIXTURE = FIXTURE.parent / "split_cases_random.json"


def test_random_fixture_is_up_to_date() -> None:
    """落盘的随机用例必须和当前 split.py 一致。

    它是锁住前端不漂的锚。如果改了算法却忘了重跑
    `python -m tools.gen_random_cases`，这条会红 —— 那正是前端还在按旧算法
    预览、后端已经按新算法落库的危险时刻。
    """
    data = json.loads(RANDOM_FIXTURE.read_text(encoding="utf-8"))
    stale: list[str] = []
    for i, case in enumerate(data["cases"]):
        rule = {
            "mode": "ratio",
            "weights": case["weights"],
            "remainder_to": case["remainder_to"],
        }
        if case.get("adjustments"):
            rule["adjustments"] = case["adjustments"]
        got = split(rule, case["amount"], order=case["order"],
                    payer=case["payer"], rotate_seed=case["rotate_seed"])
        if got != case["expected"]:
            stale.append(f"#{i} amount={case['amount']} 现在={got} 文件里={case['expected']}")
    assert not stale, (
        "随机用例文件过期了，请重跑 `.venv/bin/python -m tools.gen_random_cases`：\n"
        + "\n".join(stale[:5])
    )


#: 不带 order 的用例。**前端 test/split-no-order.spec.ts 里是同一份，期望值也一样** ——
#: 523 条夹具全都带 order，这条路一条都没测到，而两边默认顺序本来是不同的：
#: Python 的 dict 保持插入序，JS 的 Object.keys 会把数字键升序重排。
NO_ORDER_CASES = [
    ({"mode": "ratio", "weights": {"3": 1, "1": 1, "2": 1}}, 1001, "1",
     {"1": 334, "2": 334, "3": 333}),
    ({"mode": "ratio", "weights": {"10": 1, "2": 1, "1": 1}}, 1000, None,
     {"1": 334, "2": 333, "10": 333}),
    ({"mode": "ratio", "weights": {"2": 2, "1": 1, "3": 1}, "remainder_to": "order"}, 997, "2",
     {"1": 249, "2": 499, "3": 249}),
    ({"mode": "exact", "exact": {"3": 500, "1": 300, "2": 200}}, 1000, "1",
     {"1": 300, "2": 200, "3": 500}),
]


@pytest.mark.parametrize("rule, amount, payer, expected", NO_ORDER_CASES)
def test_without_order_both_implementations_pick_the_same_sequence(rule, amount, payer, expected):
    """不给顺序时也必须两边一致 —— 顺序决定平局时那 1 円归谁。"""
    assert split(rule, amount, payer=payer) == expected
