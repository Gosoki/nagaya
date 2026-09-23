"""生成 PWA 图标 —— 一次性脚本，产物已落盘，平时不用跑。

用到的 Pillow 已经在 requirements 里（头像、自定义图标也靠它）：
    .venv/bin/python -m tools.gen_icons

图案：白底、红屋顶的小房子，门口一个小人（圆窗是头、门是身子）。加到手机主屏后就靠它认人。

源文件是同目录的 icon.svg。Pillow 画不了 SVG 的渐变和阴影，所以这里只从它渲好的
1024 母版 icon-master.png 缩出各个尺寸。改了 icon.svg 之后先重渲母版
（借前端装好的 Playwright）：
    cd frontend && node -e "
      const {chromium}=require('playwright'),fs=require('fs');(async()=>{const b=await chromium.launch();
      const p=await b.newPage({viewport:{width:512,height:512},deviceScaleFactor:2});
      await p.setContent('<body style=margin:0>'+fs.readFileSync('../backend/tools/icon.svg','utf8'));
      await p.locator('svg').screenshot({path:'../backend/tools/icon-master.png'});await b.close()})()"

房子整个落在安全区里（离中心不到 0.4 个边长），maskable 版直接用整张，Android 裁圆也切不到。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
MASTER = HERE / "icon-master.png"
OUT = Path(__file__).parents[2] / "frontend" / "public" / "icons"


def draw(size: int, *, radius_ratio: float = 0.22) -> Image.Image:
    img = Image.open(MASTER).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    if radius_ratio:
        # 圆角在 4 倍大小上画再缩回来，边缘才不毛
        big = size * 4
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * radius_ratio), fill=255)
        img.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw(size).save(OUT / f"icon-{size}.png")
    # maskable：整块铺满，房子本来就在安全区里
    draw(512, radius_ratio=0).save(OUT / "icon-maskable-512.png")
    draw(180, radius_ratio=0).save(OUT / "apple-touch-icon.png")   # iOS 自己会切圆角
    draw(64).save(OUT / "favicon.png")
    for p in sorted(OUT.iterdir()):
        print(" ", p.name, p.stat().st_size, "bytes")
