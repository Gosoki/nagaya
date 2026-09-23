/**
 * 金额框里打进来的字 → 数字。
 *
 * **全角要先转成半角。** 日文输入法开着时，数字键打出来的是「１２００」，
 * 原来一律 `replace(/\D/g, '')` —— 全角数字不算 \d，整串被吞成空，当 0 处理。
 * 固定费那一格「清空＝删掉这一笔」，于是在已录的行里用输入法改个金额，
 * 一失焦就把那笔账删了。
 */
export function toHalfWidth(text: string): string {
  return text
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[－−ー]/g, '-')
    .replace(/[，、]/g, ',')
}

/** 只留数字（先转半角） */
export function digitsOf(text: string): string {
  return toHalfWidth(text).replace(/\D/g, '')
}

/**
 * 金额框的上限。最长的「99,999,999」正好把那一格占满（见 AmountInput），
 * 一千万円以上基本是多打了一个 0。这是**输入框的防手滑**，不是业务阈值 ——
 * 真正的闸在后端（ledger.MAX_AMOUNT），所以它不进设置表，留成代码常量
 */
export const MAX_YEN = 99_999_999

/** 金额框里打的字 → 日元整数。超过上限就按上限（框里当场就看得见，不是悄悄截断） */
export function yenOf(text: string): number {
  return Math.min(Number(digitsOf(text) || 0), MAX_YEN)
}

/**
 * 对话框里手打的金额 → 日元整数，认不出就是 NaN（调用方负责说出来，别静默不记）。
 *
 * 整屏的金额都写成 ¥10,000，照着屏幕打回去是最自然的动作，所以千分位的逗号（和点）
 * 要擦掉；但**别的小数点不当千分位** —— 日元没有小数，「5000.00」原来会被擦成
 * 500,000。整串是「1,234,567 / 1.234.567」这种分组时才擦点
 */
export function parseTypedYen(text: string): number {
  const raw = toHalfWidth(text).replace(/[\s．]/g, (c) => (c === '．' ? '.' : ''))
  const grouped = /^\d{1,3}([.,]\d{3})+$/.test(raw)
  const plain = /^\d+$/.test(raw.replace(/,/g, ''))
  return grouped || plain ? Number(raw.replace(/[.,]/g, '')) : NaN
}
