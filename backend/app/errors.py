"""路由层的错误。

后端只返数据和枚举 key，**不返界面文案** —— 这条规矩写在 main.py 和 schemas.py
的开头，业务错那一路（LedgerError / BillError / RuleError / SplitError）一直守着。
漏的是路由这一路：`HTTPException(404, "账目不存在")` 返出去的是
`{detail: "一句中文"}`，没有 code，前端只能把那句话原样贴到界面上 ——
于是日文界面上会冒出中文。

码是按「**用户看到之后该做什么**」分的，不是按「哪个函数抛的」分的：
「账目不存在 / 账单不存在 / 备忘不存在」对用户是同一件事（刷新一下再试），
就共用一个 `not_found`，具体是什么放进 detail 给排查用。
一个错一个码的话，十几条文案说的是同一句话，翻译两遍还容易翻歪。
"""

from __future__ import annotations

from typing import Any


class AppError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail


def not_found(what: str) -> AppError:
    """找不到了。多半是别人刚删掉、或者手里这份列表旧了 —— 刷新一下再试。"""
    return AppError("not_found", f"{what} not found", status=404, what=what)
