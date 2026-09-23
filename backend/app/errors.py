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

from fastapi.responses import JSONResponse


class AppError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail


def reject_nulls(fields: dict[str, Any], names: tuple[str, ...]) -> None:
    """PATCH 里把非空字段显式传成 null 的，在这里挡掉。

    不挡的话是**裸 500**：NOT NULL 约束要等到 commit 才炸，那时已经是
    IntegrityError 冒到最外层。前端拿到的是「服务器出错了」，人不知道自己哪里填错了。

    `fields` 拼成一句话再进 detail —— 这个值是要直接插进界面文案的 `{fields}` 的，
    传数组的话 vue-i18n 会把 `["a","b"]` 原样印进 toast。
    """
    nulled = [k for k in names if k in fields and fields[k] is None]
    if nulled:
        raise AppError("null_field", f"cannot be cleared: {nulled}", fields=", ".join(nulled))


def not_found(what: str) -> AppError:
    """找不到了。多半是别人刚删掉、或者手里这份列表旧了 —— 刷新一下再试。"""
    return AppError("not_found", f"{what} not found", status=404, what=what)


#: 这些错误是「用户输入不对」，不是 500。个别要用 409 让前端知道该刷新。
CONFLICT_CODES = {"version_conflict", "transfer_changed"}


def error_response(exc: Any) -> JSONResponse:
    """业务错误 → `{code, message, detail}`。

    exc 是 main.py 注册的那六族之一（都带 code / detail）。参数不写成那几个类：
    那样 errors.py 就得反过来 import services，而 services 本来就 import 这里。
    """
    # AppError 自己带状态码（404/403/409 都有），别的那几种统一 400，
    # 只有 version_conflict 要 409 —— 前端靠它知道该刷新再重试
    status_code = getattr(exc, "status", None) or (409 if exc.code in CONFLICT_CODES else 400)
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": str(exc), "detail": exc.detail},
    )
