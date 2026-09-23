"""结算方案 —— SPEC §4.5。

两种算法，对应设置项 `simplify_debts`：

* **最少转账（默认）**：贪心配对最大债权人 ↔ 最大债务人，n 个人最多 n−1 笔。
  副作用是会出现「原本没跟你有账的人要给你转钱」—— Splitwise 也一样，
  只有三四个室友，省笔数比保留债权对应关系更实用。
* **按原始债权**：谁垫的钱就还给谁，一分不串。笔数多，但每一笔都解释得清。

两个都是纯函数，不碰数据库。
"""

from __future__ import annotations

from typing import Mapping, NamedTuple


class Transfer(NamedTuple):
    """一笔该转的钱：from_id 把 amount 円 交给 to_id。"""

    from_id: int
    to_id: int
    amount: int


class SettleError(ValueError):
    """**故意不注册到 main.py 的错误处理里。**

    它只在 Σ余额 ≠ 0 时抛 —— 那不是「用户输入不对」，是账本本身已经坏了。
    那种情况就该是 500：前端拿一句翻好的文案糊过去，等于把地基塌了这件事
    说成一次普通的操作失败。前端那条守卫测试（error-codes.spec.ts）也是照
    main.py 的注册元组推导要哪些文案的，所以这个类天然、且正确地不在名单里。
    """

    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


def plan_simplified(balances: Mapping[int, int]) -> list[Transfer]:
    """最少转账方案。

    balances 正数＝别人欠他，负数＝他欠别人，合计必须为 0。
    排序全部带 member id 兜底，保证同样的输入永远给出同样的方案 ——
    否则每次刷新账单转账对象都在变，没人敢照着转。
    """
    total = sum(balances.values())
    if total != 0:
        raise SettleError("unbalanced", f"余额合计是 {total}，不是 0，账本已经不平了", total=total)

    creditors = sorted(
        ((m, v) for m, v in balances.items() if v > 0), key=lambda x: (-x[1], x[0])
    )
    debtors = sorted(
        ((m, -v) for m, v in balances.items() if v < 0), key=lambda x: (-x[1], x[0])
    )

    transfers: list[Transfer] = []
    i = j = 0
    credit = list(creditors)
    debt = list(debtors)
    while i < len(credit) and j < len(debt):
        cm, cv = credit[i]
        dm, dv = debt[j]
        amount = min(cv, dv)
        if amount > 0:
            transfers.append(Transfer(from_id=dm, to_id=cm, amount=amount))
        credit[i] = (cm, cv - amount)
        debt[j] = (dm, dv - amount)
        if credit[i][1] == 0:
            i += 1
        if debt[j][1] == 0:
            j += 1
    return transfers


def plan_pairwise(pair_debts: Mapping[tuple[int, int], int]) -> list[Transfer]:
    """按原始债权结算：谁垫的钱就还给谁。

    pair_debts[(欠钱的人, 垫钱的人)] = 金额。同一对人双向的债先抵消，
    剩下的净额才生成一笔转账。
    """
    netted: dict[tuple[int, int], int] = {}
    for (debtor, creditor), amount in pair_debts.items():
        if debtor == creditor or amount == 0:
            continue
        key = (debtor, creditor) if debtor < creditor else (creditor, debtor)
        sign = 1 if (debtor, creditor) == key else -1
        netted[key] = netted.get(key, 0) + sign * amount

    transfers: list[Transfer] = []
    for (a, b), net in sorted(netted.items()):
        if net > 0:
            transfers.append(Transfer(from_id=a, to_id=b, amount=net))
        elif net < 0:
            transfers.append(Transfer(from_id=b, to_id=a, amount=-net))
    return sorted(transfers, key=lambda t: (-t.amount, t.from_id, t.to_id))

