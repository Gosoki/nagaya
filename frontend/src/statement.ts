/**
 * 账单叫什么名字。
 *
 * 后端以前会拼一个「8/30 出账」存进 statement 表 —— 简体中文，日文界面上
 * 原样显示，而且**已经写进数据库了**，改代码救不了历史那几张。
 * 现在后端不给名字时留空，这里按出账日期用 i18n 渲染；
 * 库里那种「M/D 出账」的老名字也认出来重渲，不用写迁移。
 * 用户自己起的名字（「搬家那次」）照原样显示。
 */
import { jstDateOf } from 'src/date'
import { i18n } from 'src/i18n'

/** 后端当年自动拼的那种名字，认出来就别照着印 */
const AUTO = /^\s*(\d{1,2})\/(\d{1,2})\s*出账\s*$/

export function statementLabel(st: {
  label?: string | null
  cut_at?: string | null
} | null | undefined): string {
  if (!st) return ''
  const t = i18n.global.t
  const label = (st.label ?? '').trim()
  const auto = label ? AUTO.exec(label) : null
  if (label && !auto) return label
  // cut_at 是 naive UTC：按**日本时间**取那一天。原来拿 new Date() 当本地时间解析，
  // 日本时间 0〜9 点出的账，名字会写成前一天（标题、LINE 文本、流水时间线都跟着错）
  const jst = st.cut_at ? jstDateOf(st.cut_at).split('-') : null
  const [m, d] = auto
    ? [auto[1]!, auto[2]!]
    : jst
      ? [String(Number(jst[1])), String(Number(jst[2]))]
      : ['', '']
  return m ? t('bill.cutLabel', { m, d }) : label
}
