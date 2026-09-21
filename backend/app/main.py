"""应用入口。

后端只做 REST：返数据、返错误码，**不返界面文案** —— 文案全在前端 vue-i18n，
这样中日切换只需要改一处（SPEC §7.5）。
错误响应统一是 {code, message, detail}，code 给前端决定怎么提示（比如
sum_mismatch 要红字显示差额），message 只是给开发看的兜底。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.rules import RuleError
from app.services.bill import BillError
from app.core.split import SplitError
from app.init_db import init_db
from app.routers import auth, categories, entries, ledger, members, settings
from app.services.ledger import LedgerError

#: 这些错误是「用户输入不对」，不是 500。个别要用 409 让前端知道该刷新。
CONFLICT_CODES = {"version_conflict"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="nagaya 長屋", description="合租记账", version="0.1.0", lifespan=lifespan)

# 开发期前端跑在 vite dev server 上，走代理；这里放开以防直连调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("NAGAYA_CORS", "http://localhost:9000,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(exc: LedgerError | RuleError | SplitError) -> JSONResponse:
    status_code = 409 if exc.code in CONFLICT_CODES else 400
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": str(exc), "detail": exc.detail},
    )


for error_type in (LedgerError, RuleError, SplitError, BillError):
    app.add_exception_handler(
        error_type,
        lambda request, exc: _error_response(exc),  # noqa: ARG005
    )

for module in (auth, members, categories, entries, ledger, settings):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 打包后前端 dist 挂在同一个端口上 —— 「两个代码库」不等于「两个服务」（SPEC §7.2）
DIST = Path(__file__).parents[2] / "frontend" / "dist" / "pwa"

if DIST.is_dir():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """SPA 回退。

        不能用 `StaticFiles(html=True)` 了事 —— 它只在**目录**路径上回退 index.html，
        `/balance` 这种客户端路由会直接 404。手机上表现为「刷新一下就白屏」，
        而 PWA 从主屏冷启动走的正是 start_url 之外的任意路径，必须治。
        """
        if full_path.startswith("api/"):
            # /api 下的未知路径要老老实实 404，被 index.html 吞掉会让前端
            # 拿到一坨 HTML 去 JSON.parse，报出去的错完全指不到问题上
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such API")
        candidate = (DIST / full_path).resolve()
        # resolve 之后再比对根目录，挡住 ../ 穿越
        if full_path and candidate.is_file() and candidate.is_relative_to(DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
