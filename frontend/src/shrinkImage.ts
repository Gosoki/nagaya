/**
 * 传图之前，先在手机上裁方、缩小。
 *
 * 手机随手拍一张就是三五 MB、一千多万像素。原样传上去：慢网上要走好几秒，
 * 服务器还得花几百毫秒解码一张大图 —— 而最后存下来的只是一张 192（头像）
 * 或 512（App 图标）的小方图。在这儿先缩好，传上去的只剩几十 KB。
 * 服务器那边照样会再解一遍、重新编码（传上来的字节不可信），但那已经是张小图了。
 *
 * 方向不用管：<img> 解码时浏览器已经按 EXIF 摆正（image-orientation 默认 from-image），
 * 画进 canvas 的就是摆正之后的样子。canvas 导出的图不带 EXIF，拍摄地点的 GPS 也就没了。
 */
export async function shrinkSquare(file: File, side: number, type: 'image/jpeg' | 'image/png'): Promise<File> {
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    img.src = url
    await img.decode()

    // 居中裁成正方形：头像是个圆、图标是个方块，直接缩放会把人脸压扁
    let src: CanvasImageSource = img
    let s = Math.min(img.naturalWidth, img.naturalHeight)
    // 没有固有尺寸的（比如不带宽高的 SVG）画出来是一张空白，存成一个黑方块头像
    if (!s) throw new Error('image has no size')
    let sx = (img.naturalWidth - s) / 2
    let sy = (img.naturalHeight - s) / 2

    // 一次缩一半、缩到两倍以内再落到目标尺寸：一步从 3000 缩到 192，
    // 浏览器只采样零星几个点，头像上全是锯齿和摩尔纹
    // 用过的中间画布**当场释放**：iOS Safari 给整页的画布内存有个总上限，
    // 一张 1200 万像素的照片缩一轮就是几十 MB，不放的话同一次打开里多换几次头像，
    // getContext 就开始返回 null
    const used: HTMLCanvasElement[] = []
    while (s >= side * 2) {
      const half = Math.round(s / 2)
      const step = canvas(half)
      used.push(step)
      step.getContext('2d')!.drawImage(src, sx, sy, s, s, 0, 0, half, half)
      src = step
      s = half
      sx = 0
      sy = 0
    }
    const out = canvas(side)
    used.push(out)
    try {
      const ctx = out.getContext('2d')!
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(src, sx, sy, s, s, 0, 0, side, side)

      const blob = await new Promise<Blob | null>((resolve) => out.toBlob(resolve, type, 0.92))
      if (!blob) throw new Error('canvas export failed')
      return new File([blob], type === 'image/png' ? 'image.png' : 'image.jpg', { type })
    } finally {
      for (const c of used) c.width = c.height = 0
    }
  } finally {
    URL.revokeObjectURL(url)
  }
}

function canvas(side: number): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = side
  c.height = side
  return c
}
