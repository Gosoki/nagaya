/**
 * 出账确认框（BillView 的 doCut）里讲固定费的那几句，按哪几行来拼。
 *
 * 出账是不可逆的那一步，确认框是最后一道人工核对：空着的、能照上期替人记的、
 * 本期记了不止一笔的，都得在这儿说出来。纯函数、不碰 i18n（test/cut-hints.spec.ts）。
 */
import type { MonthlyRow } from 'src/api/types'

type Row = Pick<
  MonthlyRow,
  'amount' | 'archived' | 'carry_amount' | 'entry_count' | 'cuts_since_last' | 'typical_gap'
>

/**
 * 还空着的这一项是不是「隔几期才来一次、这期还没轮到」（隔月收的水费）。
 *
 * 只认后端给的节奏：typical_gap 只在历史够、而且最近两个间隔都等于它时才给（见后端
 * monthly._rhythm），看不出节奏一律当「该有」。**猜对了也只是换个颜色、换句话说，照样列出来**：
 * 账单晚到一期的水费会被画成这一类（实测千分之几），要是藏起来，那笔就按 0 出账了
 */
export const offCycle = (r: Row): boolean =>
  r.cuts_since_last != null && r.typical_gap != null && r.cuts_since_last < r.typical_gap

export interface CutRows<R extends Row> {
  /** 开了「和上期一样」、这期还没记：勾上「先按上期记上」就替人记 */
  carryable: R[]
  /** 还空着、按往常这期该有（或者看不出节奏）—— 警示 */
  due: R[]
  /** 还空着、上次记过之后还没到它往常的间隔 —— 灰字。**也列着**，只是换句话 */
  waiting: R[]
  /** 本期记了不止一笔（可能记重了，也可能真是两张账单）—— 只提示 */
  multi: R[]
}

export function cutRows<R extends Row>(rows: readonly R[]): CutRows<R> {
  const blank = rows.filter((r) => !r.archived && !r.amount && !r.carry_amount)
  return {
    carryable: rows.filter((r) => Boolean(r.carry_amount) && !r.amount),
    due: blank.filter((r) => !offCycle(r)),
    waiting: blank.filter(offCycle),
    multi: rows.filter((r) => r.entry_count > 1),
  }
}

/**
 * 出账框里「先按上期记上」回来之后，还出不出账。**没全记上就停**：带着一个空的房租把账单出掉
 * （房租按 0 冻结进一张已经发出去的单子），比晚一步出账糟糕得多。
 *
 * 不只看 failed：后端静默跳过的（刚被关掉「和上期一样」、刚归档、室友刚在面板上记过或删过）
 * 既不进 created 也不进 failed —— 按「问的每一项都记上了没有」逐项对。
 * skipped ＝ 静默跳过的那几项（提示里单说一句）
 */
export function shouldStopAfterCarry<R extends { category_id: number }>(
  asked: readonly R[],
  created: readonly { category_id: number }[],
  failed: readonly { category_id: number }[],
): { stop: boolean; skipped: R[] } {
  const made = new Set(created.map((x) => x.category_id))
  const failedIds = new Set(failed.map((x) => x.category_id))
  const skipped = asked.filter((r) => !made.has(r.category_id) && !failedIds.has(r.category_id))
  return { stop: failed.length > 0 || asked.some((r) => !made.has(r.category_id)), skipped }
}

/**
 * 「先按上期记上」的请求体、出账的 query 里带的 after_statement_id（弹框那一刻看到的最近一张，0 ＝ 一张都没出过）。
 * 两台手机同时出账时，后到的那台撞 409 bill_changed、什么都不动 —— 不带的话它会把房租再记一遍，
 * 多出一张只有房租的单子。老后端不给这个字段（undefined）就两边都不带，行为和原来一样
 */
export function cutParams(after: number | undefined): { carry: { after_statement_id?: number }; query: string } {
  return after === undefined
    ? { carry: {}, query: '' }
    : { carry: { after_statement_id: after }, query: `&after_statement_id=${after}` }
}
