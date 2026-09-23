"""把用户上传的图片安全地解开 —— 头像和 App 图标共用。

解码这一步是安全边界（防解压炸弹、防 Pillow 转手调外部程序），只写在这一处：
两条上传路径各写一遍的话，以后只在一边加了判断，另一边就又能被一张
1 亿像素的小 PNG 撑爆内存。解开之后怎么裁、存成什么格式，各自的路由自己定。
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

#: 只认这几种格式。Pillow 默认什么都敢开，EPS 这类还会转手交给 Ghostscript
IMAGE_FORMATS = ["JPEG", "PNG", "WEBP", "GIF"]
#: 解码前先看像素数。Pillow 自己的炸弹闸在 1.79 亿像素，而 1 亿像素的小 PNG
#: 文件才几百 KB、解开要 1GB 多内存 —— 手机照片也就一两千万像素，4000 万足够宽
MAX_PIXELS = 40_000_000


def open_image(raw: bytes) -> Image:
    """按白名单格式打开、先查像素数、按 EXIF 摆正。认不出或者太大就抛（调用方翻成各自的错误码）。"""
    from PIL import Image as PILImage, ImageOps   # 用到才载：Pillow 常驻要 6MB，而上传图片一年没几次

    img = PILImage.open(io.BytesIO(raw), formats=IMAGE_FORMATS)
    if img.width * img.height > MAX_PIXELS:
        raise ValueError("too many pixels")
    return ImageOps.exif_transpose(img) or img
