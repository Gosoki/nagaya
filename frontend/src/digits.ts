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
