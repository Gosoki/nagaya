"""两个纯 ASGI 中间件：请求体卡大小（BodyLimit）、空闲时把内存还回去（IdleRelease）。

挂的顺序在 main.py（「最后挂＝最外层」）。这里只管它们自己做什么。
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import logging

from app.db import engine
from app.errors import AppError, error_response

log = logging.getLogger("nagaya")


#: 最后一个请求之后这么多秒没人再用，就把内存还回去
IDLE_RELEASE = 60


def release_memory() -> None:
    """没人在用的时候，能还的都还回去。

    三个人的账本一天里绝大多数时候没人在点，可进程手里一直攥着：数据库连接
    （每条带着自己的页缓存、表结构、编译好的语句）、刚才那几个大响应用过的堆。
    Python 释放掉的内存，C 库不一定还给系统 —— 最后那一下 trim 才是真还。
    """
    engine.dispose()   # 连接全关（正在用的那条用完再关）。下个请求再开一条，毫秒级
    gc.collect()
    try:
        libc = ctypes.CDLL(None)
        if hasattr(libc, "malloc_trim"):                       # Linux（glibc）
            libc.malloc_trim(0)
        elif hasattr(libc, "malloc_zone_pressure_relief"):     # macOS
            libc.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            libc.malloc_zone_pressure_relief(None, 0)
    except OSError:
        pass


class IdleRelease:
    """纯 ASGI：最后一个请求结束 IDLE_RELEASE 秒后还没有新请求，就 release_memory() 一次。

    只在「刚闲下来」时收一次，之后一直没人用就一直不动 —— 不定时空转，也不跟请求抢。
    """

    def __init__(self, inner) -> None:  # noqa: ANN001
        self.inner = inner
        self.busy = 0
        self.timer: asyncio.TimerHandle | None = None

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        # 探活不算「有人在用」：Docker 的 HEALTHCHECK 每 30 秒来一次，算进来的话
        # 60 秒的空闲永远等不到。它也不碰数据库，没什么可收的
        if scope["type"] != "http" or scope.get("path") == "/api/health":
            await self.inner(scope, receive, send)
            return
        self.busy += 1
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        try:
            await self.inner(scope, receive, send)
        finally:
            self.busy -= 1
            if not self.busy:
                self.timer = asyncio.get_running_loop().call_later(IDLE_RELEASE, self._release)

    def _release(self) -> None:
        self.timer = None
        try:
            release_memory()
        except Exception:
            log.exception("归还内存失败")


#: 请求体上限。原来没有：未登录的请求就能 POST 一个几个 G 的体，
#: 在鉴权之前就被整个读进内存/临时文件，把进程或磁盘撑满。
#: 头像和 App 图标各有自己带文案的闸（members.MAX_AVATAR_BYTES 1MB、appearance.MAX_ICON_BYTES 2MB），
#: 这里给这两条路留到 16MB，让超了自己那道闸的图还能走到那儿、拿到带上限的那句话
MAX_BODY = 1024 * 1024
MAX_UPLOAD_BODY = 16 * 1024 * 1024


class _TooLarge(Exception):
    pass


class BodyLimit:
    """按路径卡请求体大小。纯 ASGI：Content-Length 先看一眼，
    没有长度头（分块上传）的就边收边数，超了当场停。"""

    def __init__(self, inner) -> None:  # noqa: ANN001
        self.inner = inner

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        path = scope.get("path", "")
        limit = MAX_UPLOAD_BODY if path.startswith("/api/appearance/icon") or path.endswith("/avatar") else MAX_BODY
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > limit:
                await self._reject(scope, send)
                return

        seen = 0
        started = False
        exceeded = False
        replaced = False

        async def counted():  # noqa: ANN202
            nonlocal seen, exceeded
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise _TooLarge
            return msg

        async def watched(msg) -> None:  # noqa: ANN001
            nonlocal started, replaced
            # 超限之后应用自己回的那句（FastAPI 把读体时的异常翻成 400
            # 「There was an error parsing the body」）不许发出去，换成 413
            if exceeded:
                if not replaced and msg["type"] == "http.response.start":
                    replaced = True
                    await self._reject(scope, send)
                return
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.inner(scope, counted, watched)
        except _TooLarge:
            if not started and not replaced:
                await self._reject(scope, send)

    @staticmethod
    async def _reject(scope, send) -> None:  # noqa: ANN001
        async def nothing():  # noqa: ANN202
            return {"type": "http.disconnect"}

        response = error_response(AppError("payload_too_large", "request body too large", status=413))
        await response(scope, nothing, send)
