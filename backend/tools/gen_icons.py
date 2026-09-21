"""生成 PWA 图标 —— 一次性脚本，产物已落盘，平时不用跑。

需要 Pillow（不在 requirements 里，用时临时装）：
    .venv/bin/pip install pillow
    .venv/bin/python -m tools.gen_icons

图案：深蓝底 + 白色「長」字。加到手机主屏后就靠它认人。
maskable 版留足安全区，免得被 Android 裁成圆形时切掉字。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parents[2] / "frontend" / "public" / "icons"
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BG = (61, 71, 133)      # 深蓝，和界面主色一路
FG = (255, 255, 255)


def draw(size: int, *, safe_ratio: float = 1.0, radius_ratio: float = 0.22) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if radius_ratio:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=BG)
    else:
        d.rectangle([0, 0, size - 1, size - 1], fill=BG)

    font_size = int(size * 0.62 * safe_ratio)
    font = ImageFont.truetype(FONT, font_size)
    box = d.textbbox((0, 0), "長", font=font)
    d.text(
        ((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
        "長",
        font=font,
        fill=FG,
    )
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw(size).save(OUT / f"icon-{size}.png")
    # maskable：整块铺满 + 字缩到安全区内，Android 裁圆也不会切到笔画
    draw(512, safe_ratio=0.66, radius_ratio=0).save(OUT / "icon-maskable-512.png")
    draw(180, radius_ratio=0).save(OUT / "apple-touch-icon.png")   # iOS 自己会切圆角
    draw(64).save(OUT / "favicon.png")
    for p in sorted(OUT.iterdir()):
        print(" ", p.name, p.stat().st_size, "bytes")
