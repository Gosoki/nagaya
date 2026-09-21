"""分摊规则的解析 —— SPEC §4.7。

三层，越往下优先级越高：
    1. 全局默认（setting.default_rule）
    2. 分类默认（category.default_rule_json）
    3. 这一笔自己带的规则

**生效边界**：解析只在「新建/编辑某一笔」的那一刻发生。解析完就算出 entry_share
落库固化。之后改第 1、2 层，历史账一个数字都不会动。

成员 key 统一用**字符串形式的 member id**（JSON 对象的 key 本来就只能是字符串，
不做这个统一的话，前端传 "3" 后端拿 3，会在权重查找上悄悄漏人）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


class RuleError(ValueError):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


def mkey(member_id: int | str) -> str:
    """成员在规则 / 分摊结果里的 key。"""
    return str(int(member_id))


def pick_rule(*candidates: Mapping[str, Any] | None) -> dict[str, Any]:
    """按优先级取第一个非空的规则。全空则退回「所有人等权」。"""
    for rule in candidates:
        if rule:
            return dict(rule)
    return {"mode": "ratio", "equal_weight": 1}


def _as_int(value: Any, field: str, key: str) -> int:
    """规则里的数字必须**本来就是整数**。

    原来这里写的是 `int(value)`，两头都出事：
      * 传进来 None / 字符串 / 对象时，int() 抛的 TypeError 一路冒到 FastAPI 顶上变成 500
      * 传浮点时更隐蔽 —— int(0.5) 静默截成 0。权重 0.5/0.5/1 于是变成 0/0/1：
        前两个人一分不出、第三个人全担，屏幕上一个字都不提。
        而分摊引擎两边（split.py 的 _require_int、split.ts 的 requireInt）**本来是挡了的**，
        是这一行抢在它们前面把证据抹掉了 —— 于是前端预览抛错、后端静默存下，
        正好是那 523 条 fixture 想钉死的「预览和落库不一样」。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuleError(
            "not_integer",
            f"{field}[{key}] 必须是整数，收到 {value!r}",
            field=field,
            member=key,
        )
    return value


def expand(rule: Mapping[str, Any], member_ids: Sequence[int]) -> dict[str, Any]:
    """把规则展开成显式的、逐人列全的形式，交给分摊引擎。

    `equal_weight` 是一种「不点名」的写法：所有参与人同权。这样加人减人都不用
    回头改配置 —— 但展开之后存进 entry.split_rule_json 的是**展开后的显式权重**，
    所以历史账不会因为成员变动而改变。
    """
    keys = [mkey(m) for m in member_ids]
    if len(set(keys)) != len(keys):
        raise RuleError("duplicate_member", "参与人里有重复", members=keys)
    mode = rule.get("mode", "ratio")

    if mode == "exact":
        exact = _normalize(rule.get("exact", {}))
        unknown = sorted(set(exact) - set(keys))
        if unknown:
            raise RuleError("unknown_member", f"固定金额给了不在参与人里的人：{unknown}", members=unknown)
        return {"mode": "exact", "exact": {k: _as_int(exact.get(k, 0), "exact", k) for k in keys}}

    if mode != "ratio":
        raise RuleError("unknown_mode", f"未知的分摊模式：{mode}", mode=mode)

    if "weights" in rule and rule["weights"] is not None:
        weights_raw = _normalize(rule["weights"])
        unknown = sorted(set(weights_raw) - set(keys))
        if unknown:
            raise RuleError("unknown_member", f"权重给了不在参与人里的人：{unknown}", members=unknown)
        # 规则里没提到的人按 0 补齐 —— 「没写＝不参与」，而不是「没写＝报错」
        weights = {k: _as_int(weights_raw.get(k, 0), "weights", k) for k in keys}
    else:
        w = _as_int(rule.get("equal_weight", 1), "equal_weight", "*")
        weights = {k: w for k in keys}

    adjustments_raw = _normalize(rule.get("adjustments") or {})
    unknown = sorted(set(adjustments_raw) - set(keys))
    if unknown:
        raise RuleError("unknown_member", f"调整额给了不在参与人里的人：{unknown}", members=unknown)
    adjustments = {
        k: v
        for k, v in ((k, _as_int(v, "adjustments", k)) for k, v in adjustments_raw.items())
        if v != 0
    }

    out: dict[str, Any] = {"mode": "ratio", "weights": weights}
    if adjustments:
        out["adjustments"] = adjustments
    if rule.get("remainder_to"):
        out["remainder_to"] = rule["remainder_to"]
    return out


def participants(rule: Mapping[str, Any]) -> list[str]:
    """展开后的规则涉及哪些人（含权重 0 的，他们要在账单上显示为 ¥0）。"""
    if rule.get("mode") == "exact":
        return list(rule.get("exact", {}))
    return list(rule.get("weights", {}))


def _normalize(d: Mapping[Any, Any]) -> dict[str, Any]:
    """把 key 统一成字符串形式的 member id。"""
    out: dict[str, Any] = {}
    for k, v in d.items():
        try:
            key = mkey(k)
        except (TypeError, ValueError):
            raise RuleError("bad_member_key", f"成员 key 必须是数字 id，收到 {k!r}", key=k) from None
        out[key] = v
    return out
