"""应用入口。

后端只做 REST：返数据、返错误码，**不返界面文案** —— 文案全在前端 vue-i18n，
这样中日切换只需要改一处（SPEC §7.5）。
错误响应统一是 {code, message, detail}，code 给前端决定怎么提示（比如
sum_mismatch 要红字显示差额），message 只是给开发看的兜底。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from html import escape
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlmodel import Session

from app.db import engine
from app.services import backup as backup_svc
from app.services import settings as settings_svc

from app.core.rules import RuleError
from app.errors import AppError, not_found
from app.services.backup import BackupError
from app.services.bill import BillError
from app.core.split import SplitError
from app.init_db import init_db
from app.routers import appearance, auth, backup, categories, entries, ledger, members, memos, settings
from app.services.ledger import LedgerError

log = logging.getLogger("nagaya")

#: 这些错误是「用户输入不对」，不是 500。个别要用 409 让前端知道该刷新。
CONFLICT_CODES = {"version_conflict"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    task = asyncio.create_task(_daily_backup())
    try:
        yield
    finally:
        task.cancel()


#: 多久醒一次看看今天备过没有。一小时够了 —— 判据不是「距上次多久」而是
#: 「今天有没有产出」，所以醒得勤一点只是多几次空查
_BACKUP_TICK = 3600


async def _daily_backup() -> None:
    """每天一份备份，跑在进程里。

    **为什么不挂 cron / systemd timer**：部署形态还没定（SPEC D8 写的是「部署放 M3
    再定」），而这个功能的起因正是「面板承诺了一个不存在的备份」—— 一个还要用户
    另外配一遍才生效的方案，在他配完之前仍然没有备份。这个 app 是单端口单进程
    （README 部署那一行），进程内跑一个任务不会出现多实例互相打架。

    判据是「离上一份多久了」而不是「睡够 24 小时没有」：合盖睡眠、半夜重启、
    改系统时间都会让后者失准，而前者读的是目录里那份文件自己的时间戳。

    备份失败**只记日志不抛**：备份坏了不该把记账也带下去。用户在设置页上看得见
    「上次备份」停在哪天 —— 那比一条崩溃日志更可能被真的看到。
    """
    while True:
        try:
            made = await asyncio.to_thread(_backup_once)
            if made is not None:
                log.info("备份完成：%s（%d 字节）", made["name"], made["bytes"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("自动备份失败")
        await asyncio.sleep(_BACKUP_TICK)


def _backup_once() -> dict | None:
    """在线程里跑：sqlite 那几步是阻塞的，别占着事件循环。"""
    with Session(engine) as session:
        return backup_svc.run_if_due(session)


app = FastAPI(title="nagaya 長屋", description="合租记账", version="0.1.0", lifespan=lifespan)

# 开发期前端跑在 vite dev server 上，走代理；这里放开以防直连调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("NAGAYA_CORS", "http://localhost:9000,http://localhost:5173").split(","),
    # 不开 credentials：认证走的是 Authorization 头 + localStorage，从来不用 cookie。
    # 开着只是白白多一个面
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(
    exc: LedgerError | RuleError | SplitError | BillError | BackupError | AppError,
) -> JSONResponse:
    # AppError 自己带状态码（404/403/409 都有），别的那几种统一 400，
    # 只有 version_conflict 要 409 —— 前端靠它知道该刷新再重试
    status_code = getattr(exc, "status", None) or (409 if exc.code in CONFLICT_CODES else 400)
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": str(exc), "detail": exc.detail},
    )


for error_type in (LedgerError, RuleError, SplitError, BillError, BackupError, AppError):
    app.add_exception_handler(
        error_type,
        lambda request, exc: _error_response(exc),  # noqa: ARG005
    )


@app.exception_handler(OverflowError)
def _id_too_big(request, exc):  # noqa: ANN001, ARG001
    """id 大到 SQLite 存不下（`/api/entries/99999999999999999999` 这种）。

    sqlite3 在绑参数那一层就抛 OverflowError —— 不是返回「查无此行」，
    于是一路冒到顶变成裸 500。这么大的 id 在库里**不可能存在**，
    回「找不到」才是实话。挂在这里而不是每个 session.get() 前面，
    是因为这条路径遍布路由、服务、外键检查三层，一处一处堵必然漏。
    """
    return _error_response(not_found("row"))

for module in (auth, members, categories, entries, ledger, memos, settings, backup, appearance):
    app.include_router(module.router)


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# 打包后前端 dist 挂在同一个端口上 —— 「两个代码库」不等于「两个服务」（SPEC §7.2）
DIST = Path(__file__).parents[2] / "frontend" / "dist" / "pwa"

#: assets/ 下全是内容哈希文件名，内容一变文件名就变，可以永久缓存
IMMUTABLE = "public, max-age=31536000, immutable"
#: 其余（index.html / sw.js / manifest / 图标）必须每次回源确认。
#: 注意是 no-cache 不是 no-store —— 仍然走 etag，命中 304 只花一个往返。
REVALIDATE = "no-cache"

if DIST.is_dir():

    def _index() -> Response:
        """index.html —— 把这屋自己的 App 名字**写进 HTML 再吐出去**。

        **iOS 加到主屏时叫什么，只看 `apple-mobile-web-app-title`。**
        打包产物里那行是写死的「長屋」，设置里改完名字，主屏上那个图标底下
        照样写着長屋。前端在运行时改过这个标签，但那是 JS 跑起来之后的事 ——
        而「添加到主屏幕」有可能在更早的时刻就把名字读走了。写死在 HTML 里最稳。

        <title> 一并换掉：页签、历史记录、分享出去的链接标题都用它。
        """
        html = (DIST / "index.html").read_text(encoding="utf-8")
        # **清单也得在 HTML 里就指对地方。** Safari 是在页面加载时读 manifest 的，
        # 打包产物里指的是那份写死的静态清单（「長屋 nagaya」），等前端 JS 把
        # link 改指到 /api 那份，名字早被读走了 —— 加到主屏于是永远叫長屋
        html = html.replace(
            'href="/manifest.webmanifest"',
            'href="/api/appearance/manifest.webmanifest"',
        )
        with Session(engine) as session:
            name = (settings_svc.get(session, "app_name") or "").strip()
            version = int(settings_svc.get(session, "app_icon_version") or 0)
        if version:
            # 主屏图标 iOS 只认 apple-touch-icon（优先于清单里的 icons），
            # 而这两行也是打包时写死的静态路径。带上版本号绕开手机的死缓存
            html = html.replace(
                'href="/icons/apple-touch-icon.png"',
                f'href="/api/appearance/icon/180.png?v={version}"',
            )
            html = html.replace(
                'href="/icons/favicon.png"',
                f'href="/api/appearance/icon/32.png?v={version}"',
            )
        if name:
            safe = escape(name)
            html = html.replace(
                '<meta name="apple-mobile-web-app-title" content="長屋" />',
                f'<meta name="apple-mobile-web-app-title" content="{safe}" />',
            )
            # 替换串用函数给，不用字符串：re.sub 会把字符串里的「\1」「\d」当成
            # 反向引用/转义去解析 —— 名字里带个反斜杠，index.html 就 500，
            # 所有人（连装到主屏的 app）都进不来，也就没法进设置把名字改回去
            html = re.sub(r"<title>.*?</title>", lambda _: f"<title>{safe}</title>", html, count=1)
        return Response(html, media_type="text/html", headers={"Cache-Control": REVALIDATE})

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str) -> Response:
        """SPA 回退 + 缓存头。

        三件事，每一件都对应一个真实故障：

        1. **回退**：不能用 `StaticFiles(html=True)` —— 它只在目录路径上回退 index.html，
           `/bill` 这种客户端路由会直接 404，手机上表现为「刷新一下就白屏」。

        2. **带后缀的路径不存在就老实 404**，绝不拿 index.html 冒充。
           否则新版删掉旧 chunk 之后，旧页面 `import('/assets/XxxPage-旧hash.js')`
           会拿到 200 的 HTML，浏览器拒绝按 JS 执行，动态 import 抛错、路由导航被
           reject —— 界面上就是**点了 Tab 没反应**。用户报的「余额账目点不开」就是它。

        3. **缓存头**：一个都不发的话浏览器会按启发式规则（自上次修改起时长的 10%）
           自作主张缓存 index.html，产物放一周就有十几个小时完全不问服务器，
           三个人于是跑着不同版本的记账 app。

        HEAD 也要注册：FastAPI 的 `@app.get` 不像 Starlette 那样自动补 HEAD，
        不注册的话 `curl -I` 和用 HEAD 探活的监控都会拿到 405。
        """
        if full_path.startswith("api/"):
            # /api 下的未知路径要老老实实 404，被 index.html 吞掉会让前端
            # 拿到一坨 HTML 去 JSON.parse，报出去的错完全指不到问题上
            # 这两处 404 是 HTTP 管道，不是给人看的话，所以不配错误码
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such API")

        # 打包时那份静态清单也让动态的来答：手机上还留着旧 HTML 的时候，
        # 它指的就是这个地址 —— 那份文件里名字写死成「長屋 nagaya」
        if full_path in ("manifest.webmanifest", "/manifest.webmanifest"):
            with Session(engine) as session:
                return appearance.manifest(session)

        # index.html 不许走「原样吐文件」那一支：service worker 预缓存的就是它，
        # 吐原件等于把写死的「長屋」和静态清单缓存进手机，之后怎么改都刷不出来
        if full_path in ("index.html", "/index.html"):
            return _index()

        candidate = (DIST / full_path).resolve()
        # resolve 之后再比对根目录，挡住 ../ 穿越
        if full_path and candidate.is_file() and candidate.is_relative_to(DIST.resolve()):
            cache = IMMUTABLE if full_path.startswith("assets/") else REVALIDATE
            return FileResponse(candidate, headers={"Cache-Control": cache})

        if "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")

        return _index()
