"""打包好的前端挂在同一个端口上 —— 「两个代码库」不等于「两个服务」（SPEC §7.2）。

SPA 回退、缓存头、把这屋自己的 App 名字写进 index.html。main.py 最后调 mount(app)：
这条兜底路由**必须最后注册**，否则会把 /api/health 这类后注册的路由吞掉。
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlmodel import Session

from app.db import engine
from app.routers import appearance
from app.services import settings as settings_svc

DIST = Path(__file__).parents[2] / "frontend" / "dist" / "pwa"

#: assets/ 下全是内容哈希文件名，内容一变文件名就变，可以永久缓存
IMMUTABLE = "public, max-age=31536000, immutable"
#: 其余（index.html / sw.js / manifest / 图标）必须每次回源确认。
#: 注意是 no-cache 不是 no-store —— 仍然走 etag，命中 304 只花一个往返。
REVALIDATE = "no-cache"


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


def mount(app: FastAPI) -> None:
    """dist 在（打过包）才挂。没打包就只有接口 —— 开发时前端走 vite dev server"""
    if not DIST.is_dir():
        return

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
        # 库文件、备份半成品、WAL **永远不从这儿发出去**。前端产物里本来没有这些，
        # 有就只可能是备份目录被指进了前端目录 —— 那样整本账（含密码哈希）
        # 未登录就能下载。设置那边也拦了，这里是第二道
        if candidate.name.endswith((".db", ".part", ".sqlite", "-wal", "-shm", "-journal")):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")
        # resolve 之后再比对根目录，挡住 ../ 穿越
        if full_path and candidate.is_file() and candidate.is_relative_to(DIST.resolve()):
            cache = IMMUTABLE if full_path.startswith("assets/") else REVALIDATE
            return FileResponse(candidate, headers={"Cache-Control": cache})

        if "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")

        return _index()
