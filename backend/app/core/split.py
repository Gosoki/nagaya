"""分摊引擎 —— SPEC §4.1〜§4.3。

两种模式：
    ratio   比例 ＋ 调整额（水电煤网、日用品）
    exact   固定金额（家賃）

三条铁律：
    1. 全程整数 / Fraction 运算，**不出现 float**
    2. Σ shares 必须严格等于 amount，不成立就拒绝落库
    3. 本文件的行为由 tests/fixtures/split_cases.json 定义。
       前端 TS 实现跑的是同一份用例 —— 改这里，那边必须同步改。
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Literal, Mapping, Sequence

RemainderTo = Literal["payer", "order", "rotate"]

#: 最大余数法平局时，那 1 円归谁。默认给付款人（SPEC §4.3 (a)）。
DEFAULT_REMAINDER_TO: RemainderTo = "payer"


class SplitError(ValueError):
    """分摊输入不合法。

    code 给前端用来决定怎么提示（比如 sum_mismatch 要红字显示差额）。
    """

    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


def split_exact(
    amount: int,
    exact: Mapping[str, int],
    *,
    order: Sequence[str] | None = None,
) -> dict[str, int]:
    """固定金额模式：每人手填一个数，合计必须等于总额。

    对不上就拒绝，并在 detail.diff 里给出差多少（正数＝还差这么多没分完）。
    """
    members = _members(exact, order)
    for m in members:
        _require_int(exact.get(m, 0), "exact", m)

    shares = {m: int(exact.get(m, 0)) for m in members}
    total = sum(shares.values())
    if total != amount:
        diff = amount - total
        raise SplitError(
            "sum_mismatch",
            f"各人合计 {total} 円 ≠ 总额 {amount} 円，差 {diff:+d} 円",
            diff=diff,
            total=total,
            amount=amount,
        )
    return shares


def split_ratio(
    amount: int,
    weights: Mapping[str, int],
    *,
    adjustments: Mapping[str, int] | None = None,
    order: Sequence[str] | None = None,
    remainder_to: RemainderTo = DEFAULT_REMAINDER_TO,
    payer: str | None = None,
    rotate_seed: int = 0,
) -> dict[str, int]:
    """比例 ＋ 调整额模式（SPEC §4.1 模式二、§4.2 自动配平）。

        1. base = amount − Σ adjustments
        2. base 按 weights 分，floor 后用最大余数法把余数 1 円一个个派出去
        3. 各人再加上自己的调整额
        4. 断言 Σ == amount

    调整额语义是「自动配平」：先把调整额从总额里抠掉，剩下的按比例分，最后加回去。
    所以 a−1000 的含义是「a 比按比例应担的少付 1000」，差额由所有人共同吸收。
    """
    adjustments = dict(adjustments or {})
    members = _members(weights, order)

    for m in members:
        w = weights.get(m, 0)
        _require_int(w, "weights", m)
        if w < 0:
            raise SplitError("negative_weight", f"权重不能是负数：{m}={w}", member=m, weight=w)

    unknown = [m for m in adjustments if m not in members]
    if unknown:
        raise SplitError(
            "unknown_member",
            f"调整额给了不在参与人里的人：{', '.join(unknown)}",
            members=unknown,
        )
    for m, adj in adjustments.items():
        _require_int(adj, "adjustments", m)

    base = amount - sum(adjustments.values())
    total_w = sum(weights.get(m, 0) for m in members)

    if total_w == 0:
        # 没人按比例分。只有当调整额刚好吃掉全部金额时才说得通。
        if base != 0:
            raise SplitError(
                "weights_all_zero",
                f"所有权重都是 0，没人分摊这 {base} 円",
                base=base,
            )
        shares = {m: 0 for m in members}
    else:
        # 精确有理数，不碰 float
        raw = {m: Fraction(base * weights.get(m, 0), total_w) for m in members}
        shares = {m: math.floor(raw[m]) for m in members}

        # floor 之后总是差出 r 个 1 円（0 <= r < 参与人数），派给小数部分最大的人。
        # 负数也成立：floor 让小数部分恒在 [0,1)，所以这套逻辑正负通用。
        remainder = base - sum(shares.values())
        if remainder:
            ranked = sorted(
                members,
                key=lambda m: (
                    -(raw[m] - shares[m]),
                    _tiebreak(m, members, remainder_to, payer, rotate_seed),
                ),
            )
            for m in ranked[:remainder]:
                shares[m] += 1

    for m, adj in adjustments.items():
        shares[m] += adj

    total = sum(shares.values())
    if total != amount:  # pragma: no cover —— 上面的数学保证走不到这
        raise SplitError(
            "sum_mismatch",
            f"内部错误：分摊结果 {total} ≠ 总额 {amount}",
            total=total,
            amount=amount,
        )
    return shares


def split(
    rule: Mapping,
    amount: int,
    *,
    order: Sequence[str] | None = None,
    payer: str | None = None,
    rotate_seed: int = 0,
) -> dict[str, int]:
    """按 entry.split_rule_json 分发到两种模式。API 层用这个入口。"""
    mode = rule.get("mode", "ratio")
    if mode == "exact":
        return split_exact(amount, rule.get("exact", {}), order=order)
    if mode == "ratio":
        return split_ratio(
            amount,
            rule.get("weights", {}),
            adjustments=rule.get("adjustments"),
            order=order,
            remainder_to=rule.get("remainder_to", DEFAULT_REMAINDER_TO),
            payer=payer,
            rotate_seed=rotate_seed,
        )
    raise SplitError("unknown_mode", f"未知的分摊模式：{mode}", mode=mode)


# ---------------------------------------------------------------- 内部工具


def _member_sort_key(key: str) -> tuple[int, int, str]:
    """成员 id 按数值排，非数字的排在后面按字典序。"""
    return (0, int(key), "") if key.lstrip("-").isdigit() else (1, 0, key)


def _members(source: Mapping[str, int], order: Sequence[str] | None) -> list[str]:
    """确定参与人和他们的固定顺序（顺序决定平局时谁先拿到那 1 円）。"""
    if order is None:
        # 没给顺序时，两份实现必须挑**同一个**。Python 的 dict 保持插入序，
        # 而 JS 的 Object.keys 会把数字键升序重排 —— 同一条规则两边算出两个结果，
        # 原来夹具全都带 order，这条分歧一条都测不到（现在共享夹具末尾 4 条专门不带）。统一成按成员 id 排
        return sorted(source, key=_member_sort_key)
    members = list(order)
    if set(members) != set(source):
        missing = sorted(set(source) - set(members)) + sorted(set(members) - set(source))
        raise SplitError(
            "unknown_member",
            f"参与人和顺序表对不上：{', '.join(missing)}",
            members=missing,
        )
    return members


def _tiebreak(
    member: str,
    members: Sequence[str],
    remainder_to: RemainderTo,
    payer: str | None,
    rotate_seed: int,
) -> tuple[int, ...]:
    """小数部分相同时的排序键，越小越先拿到那 1 円。"""
    idx = members.index(member)
    if remainder_to == "payer":
        # 付款人排最前；付款人不在参与人里时自然退化成按顺序
        return (0 if member == payer else 1, idx)
    if remainder_to == "order":
        return (idx,)
    if remainder_to == "rotate":
        return ((idx + rotate_seed) % len(members),)
    raise SplitError("unknown_remainder_to", f"未知的余数规则：{remainder_to}", remainder_to=remainder_to)


def _require_int(value, field: str, member: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SplitError(
            "not_integer",
            f"{field}[{member}] 必须是整数，收到 {value!r}",
            field=field,
            member=member,
        )
