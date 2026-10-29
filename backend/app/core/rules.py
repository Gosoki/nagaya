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

from typing import Any, Mapping, Sequence


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


def _prune_rule(rule: dict[str, Any] | None, active: set[int]) -> dict[str, Any] | None:
    """把分类默认规则里**已经不在籍的人**剔掉。

    分类的默认分摊是当年按那时候几个人写死的（房租那条就点名了 adjustments）。
    有人搬走之后，expand() 会拿「今天在籍的人」当参与人，发现规则里多出一个
    不认识的 id，直接抛 unknown_member —— 于是那一行固定费永远存不上，
    「和上期一样」也从此一声不吭地停了。

    剔掉而不是报错：这是一条**为上一期写的**规则，拿它硬套今天的人本来就不对。
    注意剩下的人分摊会变（adjustments 是「先抠掉再按比例分」），所以调整额一并去掉
    的那份钱会回到大家头上 —— 记一笔继承默认规则时这是唯一说得通的默认，
    规则本身该由用户重新定。**「照上期」不走这条默认**：上期给搬走的人记过钱
    （权重、调整额、定额非 0）的，monthly._carry_plan 先拦下来请人重填，
    走到这里的只剩「点了名但本来就是 0」的人。

    **它只管「人少了」。**「人多了」是另一回事，在 _stale_for_today 那儿拦下来 ——
    往这条规则里补一个新人，补多少只有住的人知道。

    **点名的人全搬走了，weights 就留成空的 `{}`，不退回同权。** 原来是退回「所有在籍成员同权」：
    分类规则写的「只算 Zen」在 Zen 搬走之后悄悄变成大家均分，而前端预览（core/seed.ts）
    对同一条规则是全 0、不让存 —— 两边口径相反，而且 `{"3": 1}` 退回均分、
    等价的 `{"1": 0, "2": 0, "3": 1}` 却报错，存不存得下钱看规则碰巧怎么写。
    留空之后 expand 按 0 补齐，split 报 weights_all_zero（没人参与分摊），和前端一致。
    本来就没写 weights 的规则（equal_weight、只有调整额的）不受影响。

    放在 core 里是因为记一笔（services/ledger）也要用：没送规则、继承分类或全局默认时，
    点名了已搬走的人就会被 expand() 整笔拒掉，而前端预览（core/seed.ts）早就把他们剔掉了。
    名字的下划线是沿用（AUDIT「有歧义的名字」里定过不改）。
    """
    if not rule:
        return rule
    out = dict(rule)
    for field in ("weights", "adjustments", "exact"):
        if isinstance(out.get(field), dict):
            out[field] = {k: v for k, v in out[field].items() if int(k) in active}
            if not out[field] and field != "weights":
                out.pop(field)
    # 本来就没写 weights 的（equal_weight、只有调整额的）：照旧是「所有在籍成员同权」
    if out.get("mode", "ratio") == "ratio" and "weights" not in out:
        out.setdefault("equal_weight", 1)
    return out


#: 规则里那些数字的上界。和 ledger.MAX_AMOUNT 同一个数 —— 在这里写死而不是 import，
#: 是因为 core/ 不该反过来依赖 services/（现在的依赖方向是 services → core）
MAX_RULE_VALUE = 1_000_000_000_000


def _as_int(value: Any, field: str, key: str) -> int:
    """规则里的数字必须**本来就是整数**。

    原来这里写的是 `int(value)`，两头都出事：
      * 传进来 None / 字符串 / 对象时，int() 抛的 TypeError 一路冒到 FastAPI 顶上变成 500
      * 传浮点时更隐蔽 —— int(0.5) 静默截成 0。权重 0.5/0.5/1 于是变成 0/0/1：
        前两个人一分不出、第三个人全担，屏幕上一个字都不提。
        而分摊引擎两边（split.py 的 _require_int、split.ts 的 requireInt）**本来是挡了的**，
        是这一行抢在它们前面把证据抹掉了 —— 于是前端预览抛错、后端静默存下，
        正好是共享 fixture 想钉死的「预览和落库不一样」。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuleError(
            "not_integer",
            f"{field}[{key}] 必须是整数，收到 {value!r}",
            field=field,
            member=key,
        )
    # 上界和金额同一个数。不设的话一条写进设置/分类的规则就能把每笔账的应担
    # 打成天文数字 —— 而合计仍等于总额，所有自检照样是绿的。
    # 卡在这里意味着**存规则那一刻**就拒（settings 和 categories 都会先试着用一下），
    # 而不是等到有人拿它记第一笔账
    if abs(value) > MAX_RULE_VALUE:
        raise RuleError(
            "not_in_range", f"{field}[{key}] 超出范围：{value}", field=field, member=key
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
        # 当场认一下：只在「真有除不尽的 1 円」时才会走到 split 里的那道检查，
        # 存规则时拿 1000 円试算一次往往整除，坏值就这么混进库，等哪天记一笔
        # 除不尽的账才报错 —— 那时人正在记账，看不出是规则的事
        if rule["remainder_to"] not in ("payer", "order", "rotate"):
            raise RuleError(
                "unknown_remainder_to", f"未知的余数规则：{rule['remainder_to']}",
                remainder_to=rule["remainder_to"],
            )
        out["remainder_to"] = rule["remainder_to"]
    return out


def participants(rule: Mapping[str, Any]) -> list[str]:
    """展开后的规则涉及哪些人（含权重 0 的，他们要在账单上显示为 ¥0）。"""
    if rule.get("mode") == "exact":
        return list(rule.get("exact", {}))
    return list(rule.get("weights", {}))


def named_members(rule: Mapping[str, Any]) -> list[int]:
    """这次提交的**原始**规则点了哪几个人（participants 吃的是展开后的规则）。

    先验形状：`{"weights": "abc"}`、`{"x": 1}` 这种，直接 int() 会抛出
    TypeError/ValueError 冒成裸 500；这里抛 RuleError，和 POST 同样的输入一样是 400
    """
    section = rule.get("exact") if rule.get("mode") == "exact" else rule.get("weights")
    if section is None:
        return []
    return [int(k) for k in _normalize(section)]


def _normalize(d: Any) -> dict[str, Any]:
    """把 key 统一成字符串形式的 member id。

    先确认它真是个对象：`weights` / `exact` / `adjustments` 是从 JSON 里原样收进来的，
    传成数组或字符串时 `.items()` 抛的 AttributeError 会一路冒到 FastAPI 顶上变成裸 500。
    """
    if not isinstance(d, Mapping):
        raise RuleError("bad_rule_shape", f"这里要一个「成员 id → 数字」的对象，收到 {type(d).__name__}")
    out: dict[str, Any] = {}
    for k, v in d.items():
        try:
            key = mkey(k)
        except (TypeError, ValueError):
            raise RuleError("bad_member_key", f"成员 key 必须是数字 id，收到 {k!r}", key=k) from None
        out[key] = v
    return out
