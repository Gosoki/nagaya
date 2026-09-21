"""规则解析回归 —— SPEC §4.7。"""

from __future__ import annotations

import pytest

from app.core.rules import RuleError, expand, participants, pick_rule
from app.core.split import split


def test_priority_entry_beats_category_beats_global() -> None:
    entry_rule = {"mode": "ratio", "weights": {"1": 2}}
    cat_rule = {"mode": "ratio", "weights": {"1": 3}}
    glob = {"mode": "ratio", "equal_weight": 1}
    assert pick_rule(entry_rule, cat_rule, glob) == entry_rule
    assert pick_rule(None, cat_rule, glob) == cat_rule
    assert pick_rule(None, None, glob) == glob
    assert pick_rule(None, None, None) == {"mode": "ratio", "equal_weight": 1}


def test_equal_weight_expands_over_current_members() -> None:
    """equal_weight 是「不点名」写法，展开时才知道有谁在。"""
    assert expand({"mode": "ratio", "equal_weight": 1}, [1, 2, 3]) == {
        "mode": "ratio",
        "weights": {"1": 1, "2": 1, "3": 1},
    }
    # 第 4 个人加进来，同一条全局规则自动覆盖到他
    assert expand({"mode": "ratio", "equal_weight": 1}, [1, 2, 3, 4])["weights"] == {
        "1": 1, "2": 1, "3": 1, "4": 1
    }


def test_int_and_str_member_keys_are_the_same_person() -> None:
    """前端传 "3"、后端拿 3，不能变成两个人。"""
    a = expand({"mode": "ratio", "weights": {3: 2, 4: 1}}, [3, 4])
    b = expand({"mode": "ratio", "weights": {"3": 2, "4": 1}}, [3, 4])
    assert a == b == {"mode": "ratio", "weights": {"3": 2, "4": 1}}


def test_unmentioned_member_defaults_to_zero_weight() -> None:
    """规则里没提到的人＝不参与（权重 0），不是报错。"""
    assert expand({"mode": "ratio", "weights": {"1": 1, "2": 1}}, [1, 2, 3])["weights"] == {
        "1": 1, "2": 1, "3": 0
    }


def test_zero_adjustments_are_dropped() -> None:
    r = expand({"mode": "ratio", "equal_weight": 1, "adjustments": {"1": 0, "2": 500}}, [1, 2])
    assert r["adjustments"] == {"2": 500}


def test_exact_mode_fills_missing_with_zero() -> None:
    r = expand({"mode": "exact", "exact": {"1": 45000, "2": 40000}}, [1, 2, 3])
    assert r == {"mode": "exact", "exact": {"1": 45000, "2": 40000, "3": 0}}


def test_unknown_member_rejected() -> None:
    for rule in (
        {"mode": "ratio", "weights": {"9": 1}},
        {"mode": "ratio", "equal_weight": 1, "adjustments": {"9": 100}},
        {"mode": "exact", "exact": {"9": 100}},
    ):
        with pytest.raises(RuleError) as exc:
            expand(rule, [1, 2])
        assert exc.value.code == "unknown_member"


def test_bad_member_key_rejected() -> None:
    with pytest.raises(RuleError) as exc:
        expand({"mode": "ratio", "weights": {"tanaka": 1}}, [1, 2])
    assert exc.value.code == "bad_member_key"


def test_expanded_rule_feeds_split_engine_directly() -> None:
    """解析 → 分摊，端到端对上 SPEC §4.2 的例子。"""
    rule = expand(
        {"mode": "ratio", "equal_weight": 1, "adjustments": {"1": -1000, "2": 500}},
        [1, 2, 3],
    )
    shares = split(rule, 9000, order=participants(rule), payer="1")
    assert shares == {"1": 2167, "2": 3667, "3": 3166}
    assert sum(shares.values()) == 9000
