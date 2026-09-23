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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlmodel import Session

from app.db import engine
from app.services import backup as backup_svc

from app.core.rules import RuleError
from app.errors import AppError, error_response, not_found
from app.middleware import BodyLimit, IdleRelease, release_memory
from app.services.backup import BackupError
from app.services.bill import BillError
from app.core.split import SplitError
from app.init_db import init_db
from app import spa
from app.routers import appearance, auth, backup, bill, categories, entries, members, memos, prefs, settings
from app.services.ledger import LedgerError

log = logging.getLogger("nagaya")

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
        except BackupError as e:
            # 预料之中的「这回不备」：账本还是空的（新装好、还没建账号）、目录写不进去、盘满……
            # 原因一句话就说清了，不值得每小时甩一整段 traceback；设置页上那一行也会照实说
            if e.code == "backup_empty_source":
                log.info("账本里还没有人，这回不备份")
            else:
                log.warning("自动备份没做成：%s（%s）", e, e.code)
        except Exception:
            log.exception("自动备份失败")
        # 备份不走 HTTP，IdleRelease 看不见它：那次 VACUUM INTO 把整本库读进了连接的页缓存，
        # 不在这儿还的话要一直攥到第二天有人来。没做成的那次也读过库，一样要还
        await asyncio.to_thread(release_memory)
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


for error_type in (LedgerError, RuleError, SplitError, BillError, BackupError, AppError):
    app.add_exception_handler(
        error_type,
        lambda request, exc: error_response(exc),  # noqa: ARG005
    )


@app.exception_handler(OverflowError)
def _id_too_big(request, exc):  # noqa: ANN001, ARG001
    """id 大到 SQLite 存不下（`/api/entries/99999999999999999999` 这种）。

    sqlite3 在绑参数那一层就抛 OverflowError —— 不是返回「查无此行」，
    于是一路冒到顶变成裸 500。这么大的 id 在库里**不可能存在**，
    回「找不到」才是实话。挂在这里而不是每个 session.get() 前面，
    是因为这条路径遍布路由、服务、外键检查三层，一处一处堵必然漏。
    """
    return error_response(not_found("row"))

for module in (auth, members, prefs, categories, entries, bill, memos, settings, backup, appearance):
    app.include_router(module.router)

# 压缩。前面没有 nginx，没人替它压：流水 500 笔的 JSON 是 230KB（压完 18KB），
# 第一次装 PWA 要下 800KB 的脚本和样式（压完 270KB）。在外面用手机流量时差的就是这些
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

# 最后挂 ＝ 最外层：CORS 和路由都还没碰到请求体之前就先卡住
app.add_middleware(BodyLimit)
app.add_middleware(IdleRelease)


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# 最后挂前端：它那条兜底路由会接住所有还没人认领的路径
spa.mount(app)
