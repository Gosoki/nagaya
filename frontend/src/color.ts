/**
 * 颜色的两件小事：这块底色上该用黑字还是白字，以及它的淡底版本。
 *
 * 成员色和分类色都是**用户自己挑的**，浅到 #ffd54f 也完全可能 —— 一律白字
 * 的话对比度掉到 1.5:1，而这两种颜色恰恰是用来分辨「这是谁 / 这是哪一类」的。
 * 所以按亮度算一次，别拍脑袋。
 */

function channels(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
  return [r ?? 0, g ?? 0, b ?? 0]
}

/** WCAG 的相对亮度 */
function luminance(hex: string): number {
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  const [r, g, b] = channels(hex)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** 这块底色上读得更清的那种字色 */
export function inkOn(hex: string): string {
  const L = luminance(hex)
  const onWhite = 1.05 / (L + 0.05)
  const onBlack = (L + 0.05) / 0.05
  return onBlack > onWhite ? '#16181d' : '#ffffff'
}

/**
 * 淡底版本。用来给「可点但没选中」的东西上色 —— 灰底会让一排按钮看着像
 * 三个空盒子，而它自己的颜色淡一层既说得出是哪一类，又看得出能点。
 * 不用 CSS 的 color-mix：那个要 Safari 16.2 起，而这是给手机用的。
 */
export function tint(hex: string, alpha = 0.12): string {
  const [r, g, b] = channels(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
