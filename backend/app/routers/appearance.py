"""这屋的 App 叫什么、图标长什么样。

**为什么值得做成可改的**：这东西是自托管的，一户一个实例。加到手机主屏之后，
图标和名字就是「这是哪个屋的账本」的全部标识 —— 默认那个「長」字对住在
長屋 的人合适，对别人不合适，而改它本来要去改代码再重新打包。

名字和「有没有自定义图标」两项走的是**普通设置**（settings 表，跟着备份一起走）；
图标本体存在库里的 app_icon 表里，同样跟着备份走 —— 放磁盘的话，
恢复一份备份之后图标还是旧的。
"""

from __future__ import annotations

import asyncio
import io

from fastapi import APIRouter, Depends, File, Response, UploadFile
from PIL import Image, ImageOps
from sqlmodel import Session

from app.auth import current_member
from app.db import get_session
from app.errors import AppError
from app.models import AppIcon, Member, now_utc
from app.services import settings as settings_svc

router = APIRouter(prefix="/api/appearance", tags=["appearance"])

#: 母版尺寸。各处要的图标都从它缩，够大就行（PWA 最大要 512）
MASTER = 512
#: 允许取的尺寸。不开放任意值 —— 免得有人拿 /icon/99999.png 让服务器去画一张大图
SIZES = {32, 180, 192, 512}
MAX_ICON_BYTES = 5 * 1024 * 1024
#: 只认这几种格式。Pillow 默认什么都敢开，EPS 这类还会转手交给 Ghostscript
IMAGE_FORMATS = ["JPEG", "PNG", "WEBP", "GIF"]
#: 解码前先看像素数。Pillow 自己的炸弹闸在 1.79 亿像素，而 1 亿像素的小 PNG
#: 文件才几百 KB、解开要 1GB 多内存 —— 手机照片也就一两千万像素，4000 万足够宽
MAX_PIXELS = 40_000_000


def _to_master(raw: bytes) -> bytes:
    """把上传的图压成一张 512 的方图。

    和头像那条路同一个套路（按 EXIF 摆正、居中裁方、丢掉元数据），
    只有两处不同：
      * 存 PNG 不存 WebP —— 图标要给 manifest 和 apple-touch-icon 用，
        老一点的 iOS 不认 WebP 的主屏图标；
      * 保留透明通道 —— 圆角/异形图标在深色主屏上不该多一个白方块。
    """
    try:
        img = Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("too many pixels")
        img = ImageOps.exif_transpose(img) or img
        img = img.convert("RGBA")
        img = ImageOps.fit(img, (MASTER, MASTER), method=Image.Resampling.LANCZOS)
    except Exception as e:  # Pillow 认不出的、或者解压炸弹
        raise AppError("icon_not_image", "not an image") from e
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@router.post("/icon")
async def upload_icon(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
) -> dict[str, int]:
    # 多读一个字节：正好等于上限的放过，超一点就拒 —— 不先整个读进内存
    raw = await file.read(MAX_ICON_BYTES + 1)
    if len(raw) > MAX_ICON_BYTES:
        raise AppError(
            "icon_too_big", "icon over the size limit", status=413,
            limit_mb=MAX_ICON_BYTES // 1024 // 1024,
        )
    if not raw:
        raise AppError("icon_empty", "no file received")

    row = session.get(AppIcon, 1) or AppIcon(id=1)
    # 解码/缩放是几百毫秒的 CPU 活：放线程里跑，别卡住整个事件循环（别人的请求）
    row.png = await asyncio.to_thread(_to_master, raw)
    row.updated_at = now_utc()
    session.add(row)
    session.commit()

    # 版本号进设置表：前端靠它知道「有没有自定义图标」，也靠它绕开缓存 ——
    # 主屏图标是浏览器和系统都会死缓存的东西，地址不变就永远不刷新
    version = int(settings_svc.get(session, "app_icon_version") or 0) + 1
    settings_svc.set_(session, "app_icon_version", version)
    return {"version": version}


@router.delete("/icon")
def delete_icon(
    session: Session = Depends(get_session),
    _: Member = Depends(current_member),
) -> dict[str, int]:
    """撤掉自定义图标，回到打包时那个「長」字。"""
    row = session.get(AppIcon, 1)
    if row is not None:
        session.delete(row)
        session.commit()
    settings_svc.set_(session, "app_icon_version", 0)
    return {"version": 0}


@router.get("/icon/{size}.png")
def get_icon(
    size: int,
    session: Session = Depends(get_session),
) -> Response:
    """**不要求登录。** 主屏图标、页签小图、manifest 里的图，
    都是浏览器/系统自己去取的，带不上我们的 Authorization 头。
    图标不是秘密（登录页上本来就印着），但账本数据一个字都不从这儿出去。
    """
    if size not in SIZES:
        raise AppError("not_found", "no such icon size", status=404, what="icon")
    row = session.get(AppIcon, 1)
    if row is None or not row.png:
        raise AppError("not_found", "no custom icon", status=404, what="icon")
    img = Image.open(io.BytesIO(row.png))
    if size != MASTER:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        # 地址里带着版本号（前端拼的 ?v=），所以可以放心长缓存
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/manifest.webmanifest")
def manifest(session: Session = Depends(get_session)) -> Response:
    """PWA 的清单。**同样不要求登录** —— 装到主屏那一下是浏览器自己去取的。

    打包时那份静态 manifest 还在（名字写死成「長屋 nagaya」）；前端启动后把
    `<link rel=manifest>` 指到这里来，于是改完名字下次安装就跟着变。
    走 /api 这条路还有一个好处：service worker 预缓存的是打包产物，
    /api 从来不进缓存，这份清单永远是新的。
    """
    name = str(settings_svc.get(session, "app_name") or "").strip() or "長屋 nagaya"
    version = int(settings_svc.get(session, "app_icon_version") or 0)
    if version:
        icons = [
            {"src": f"/api/appearance/icon/192.png?v={version}", "sizes": "192x192", "type": "image/png"},
            {"src": f"/api/appearance/icon/512.png?v={version}", "sizes": "512x512", "type": "image/png"},
            # 自定义图标没法替用户留出安全区，所以 maskable 那一档用同一张：
            # Android 裁圆时可能切掉边角，但总好过继续用别人家的「長」字
            {"src": f"/api/appearance/icon/512.png?v={version}", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ]
    else:
        icons = [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icons/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ]
    return Response(
        content=__import__("json").dumps(
            {
                "name": name,
                "short_name": name[:12],
                "description": "合租记账",
                # theme_color 是浏览器拿去涂「页面之外」那块的色，跟着页面走 ——
                # 藏青会在 iOS 上变成底栏下面的一大片深蓝（见 index.html 那段注释）。
                # background_color 是启动闪屏的底，那儿要的正是藏青 + 白「長」字
                "theme_color": "#ffffff",
                "background_color": "#3d4785",
                "display": "standalone",
                "orientation": "portrait",
                "start_url": "/",
                "icons": icons,
            },
            ensure_ascii=False,
        ),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )
