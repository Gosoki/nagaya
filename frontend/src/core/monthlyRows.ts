/**
 * 固定费面板（MonthlyFixed.vue）一行的几条判定。
 *
 * 这一屏是前端唯一会替人写钱的地方，而出过事的全是行状态的时序：保存还在路上时又改了、
 * 改的被静默吞掉；重建时把没存上的输入悄悄变成 PATCH 室友刚记的那一笔；
 * 「已照上期」拿框里的字当依据说了假话。这些 E2E 盯不住（要卡准毫秒），
 * 写在 SFC 里又 import 不到，所以抽到这里配单测（test/monthly-rows.spec.ts）。
 * .vue 里只留调用；上下文（翻没翻旧账单、今天谁在籍）都靠传参，和 core/transfers 一个做法。
 */
import type { MonthlyRow } from 'src/api/types'
import { digitsOf } from 'src/digits'

/** 框里那串字是多少钱。空的、认不出的都是 0 */
export const amountOf = (text: string): number => Number(digitsOf(text)) || 0

/** 面板上手里的那份状态（MonthlyFixed 的行在结构上满足它） */
interface Typed {
  text: string
  dirty: boolean
}
type CarryRow = Typed & Pick<MonthlyRow, 'entry_id' | 'carry_amount' | 'carry_blocked'>

/**
 * 这一行能不能「照上期」一键记上。正在手填的行不算 —— 人已经在填了，
 * 再给一个按钮只会记出两笔（后端也只记传过去的那几项）
 */
export const isCarryReady = (r: CarryRow, historic: boolean): boolean =>
  !historic && Boolean(r.carry_amount) && r.entry_id === null && !r.dirty && !r.text

/** 开了「和上期一样」却抄不了，而且还空着（填了就不再提醒，见行头那句） */
export const isCarryBlocked = (r: CarryRow, historic: boolean): boolean =>
  !historic && Boolean(r.carry_blocked) && r.entry_id === null && !r.dirty && !r.text

/**
 * 展开区那颗「照上期 ¥…」露不露：开了「和上期一样」、上期有数就一直在 —— 本期填过了也在，
 * 好让人看得见这一期是不是照上期记的。抄不了的（垫付人搬走了、来了新室友、上期有好几笔）
 * 还没填时不露：行头上写着为什么要自己填
 */
export const carryShown = (r: CarryRow & Pick<MonthlyRow, 'last_amount'>, historic: boolean): boolean =>
  !historic && Boolean(r.last_amount) && !(r.entry_id === null && isCarryBlocked(r, historic))

/**
 * 「已照上期」：**库里**这一项就是上期那个数。
 *
 * 原来拿框里的字比：框里打了没存上（红框）、或者存到一半又被改了，都照样写「已照上期」
 * 而且点不动；本期有两笔时也写，和合计对不上。现在只在「存好了、只有这一笔、
 * 金额等于上期」时才这么说 —— 从点按钮到存好那一小段写回「照上期」，那是如实的
 */
export const isAtLast = (
  r: Pick<Typed, 'dirty'> & Pick<MonthlyRow, 'entry_count' | 'amount' | 'last_amount'>,
): boolean => !r.dirty && r.entry_count <= 1 && r.amount !== null && r.amount === r.last_amount

/**
 * 点「照上期」走哪条路：
 *   'carry' —— 还没填（也没在填、也没在存）：后端照上期那一笔的垫付人和分摊记一笔；
 *   'type'  —— 别的情况：等于替人把上期的数敲进框里再存，垫付人和分摊都不动。
 * 这一行正在存（POST 还在路上）时一律走 'type'：再 carry 一次就是同一项两笔
 */
export function lastAction(r: CarryRow, historic: boolean, saving: boolean): 'carry' | 'type' {
  return isCarryReady(r, historic) && !saving ? 'carry' : 'type'
}

/**
 * 这一笔算谁垫的。按「谁最有发言权」排：
 *   1. 本期已经录了 → 就是当初记的那个人（后端随行给的 payer_id），谁也别动它
 *   2. 这一项定过默认垫付人 → 用它（房租永远从同一张卡扣）
 *   3. 上期那一笔是谁垫的（和「和上期一样」同一个口径）
 *   4. 全局的「默认垫付人」设置（他今天还住在这儿的话）—— fallback
 *   5. 当前登录的人 —— 也在 fallback 里
 *
 * 少了第 2 条的话，这一屏就是「谁填的算谁」：别人刷的卡被随手填进去，
 * 账本当场错一整笔房租的钱，而屏幕上一点提示都没有。
 */
export function payerOf(
  row: Pick<MonthlyRow, 'entry_id' | 'default_payer_id' | 'last_payer_id'> & { payer_id: number | null },
  ctx: { historic: boolean; active: readonly number[]; fallback: number | null },
): number | null {
  if (row.payer_id !== null) return row.payer_id
  // 翻旧账单时，已录的那几行**宁可不显示垫付人，也别显示一个猜的**：
  // 后面两级回退给的是「今天的默认垫付人」，跟当初谁真掏的钱没关系 ——
  // 而这一屏正是靠这个名字告诉人「这笔房租是谁垫的」
  if (ctx.historic && row.entry_id !== null) return null
  // 分类上定的默认垫付人已经搬走了：跳过他往下退（和记一笔那边同一个口径）。
  // 照用的话，手填的房租就记成了已经不住这儿的人垫的。设置里他会标红
  const living = (id: number | null | undefined) => (id != null && ctx.active.includes(id) ? id : null)
  return living(row.default_payer_id) ?? row.last_payer_id ?? ctx.fallback
}

type Sendable = { text: string; rule_override: Record<string, unknown> | null }

/**
 * 这一次保存发出去的是什么。**比内容，不比引用**：SplitEditor 只要碰过，
 * 金额一变就会重新 emit 一个内容相同的新对象 —— 比引用的话每次都多存一遍
 */
export const saveSig = (r: Sendable): string => JSON.stringify([r.text, r.rule_override])

/**
 * 存成功之后清不清「没存上」。**只有发出去之后这一行没再被改过才清。**
 *
 * 原来存完无条件清：请求在路上时又改了金额（或者打完数直接点「照上期」，
 * 失焦先把打了一半的数发出去、click 再改框），排在后面的那次保存一看「不 dirty」就走了 ——
 * 屏幕上是新数、库里是旧数，框不红、「改完自动保存」照写。展开区里改的分摊同样被吞。
 * 现在改过就留着 dirty：排着的那次接着存（POST 回来已经有 entry_id，下一次走 PATCH，
 * 不会多记一笔）；没排着的（只改了分摊）照常标红，收起、离屏、出账时 flush 存上
 */
export function settleSaved(r: Sendable & { dirty: boolean }, sent: string): boolean {
  if (saveSig(r) !== sent) return false
  r.dirty = false
  r.rule_override = null
  return true
}

/**
 * 面板重建（拿到新的 /monthly）时，手里那一行怎么办：
 *   'server'   —— 手里没什么要留的，照服务器的来；
 *   'keep'     —— 留着没存上的输入（服务器那边这一项没动过）；
 *   'taken'    —— 手里那一笔被出账带走了：输入丢掉、说一声（留着的话下一次失焦把它记进下一期）；
 *   'same'     —— 服务器这一项在我没看见时变了，但和我填的一样：采用服务器的，不再写；
 *   'conflict' —— 变了而且不一样：**不许自动写**，标出来让人选用哪个。
 *
 * 「变了」是：我这行是新的、服务器上却已经有了一笔（室友记了，或者我自己的 POST
 * 其实成功了、只是回应丢在路上）；或者同一笔的 version 被推高了（被人改过）。
 * 原来只认第一种情况里的「被出账带走」，于是没存上的新值换上室友那笔的 entry_id/version，
 * 下一次失焦就 PATCH 过去覆盖了他的金额；version 被推高的那种更隐蔽 ——
 * 换上新 version 再 PATCH，乐观锁在这一屏上等于没有。
 * 自己存成功时 entry_id/version 已经写回手里这一行，所以自己的写入不会被认成「变了」
 */
export type Merge = 'server' | 'keep' | 'taken' | 'same' | 'conflict'

export function mergeHeld(
  held:
    | (Typed &
        Pick<MonthlyRow, 'entry_id' | 'version'> & {
          rule_override: Record<string, unknown> | null
          conflict: unknown
        })
    | undefined,
  r: Pick<MonthlyRow, 'entry_id' | 'version' | 'amount'>,
): Merge {
  if (!held?.dirty) return 'server'
  if (held.entry_id !== null && held.entry_id !== r.entry_id) return 'taken'
  const moved = held.entry_id === null ? r.entry_id !== null : held.version !== r.version
  // 没变：还挂着没选的冲突就接着挂着
  if (!moved) return held.conflict ? 'conflict' : 'keep'
  // 我这边本来就没要记什么（新的一行、框是空的）：没什么可冲突的
  if (held.entry_id === null && amountOf(held.text) === 0) return 'server'
  return amountOf(held.text) === (r.amount ?? 0) && held.rule_override === null ? 'same' : 'conflict'
}

/**
 * 量级闸（409 amount_jump）回来的倍数，换成给人看的「约 N 倍 / 约 N 分之一」里那个 N。
 * 后端给的可能是「本期 ÷ 上期」（往下跳时小于 1），也可能已经翻成 ≥1 的倍数 —— 两种都认。
 * 10 倍以上取整，以下留一位小数。认不出的给 null，调用方退回不带数字的那句
 */
export function jumpFactor(ratio: unknown): number | null {
  const r = Number(ratio)
  if (!Number.isFinite(r) || r <= 0) return null
  const n = r >= 1 ? r : 1 / r
  return n >= 10 ? Math.round(n) : Math.round(n * 10) / 10
}

/**
 * 按 category_id 逐行做 fn，**每一步都现取那一行**（面板的 flush / leave 用）。
 *
 * 循环开头拿到的那个数组会过期：前一行撞 409 之后面板 load() 重建，或者量级闸的框开着时
 * 切回前台、账单页重取了固定费（watch bills.monthly），build() 把不在保存中的行全换成新对象。
 * 接着存旧对象的话，钱存上了、屏幕上那份副本却还 dirty —— 出账被「N 项没存上」误拦，
 * 离开这一屏还留下一条不会自己消失的「没存上」。重建之后不见了的行（项被删掉了）跳过
 */
export async function eachLive<R extends { category_id: number }>(
  rows: () => readonly R[],
  fn: (row: R) => Promise<unknown>,
): Promise<void> {
  for (const id of rows().map((r) => r.category_id)) {
    const row = rows().find((r) => r.category_id === id)
    if (row) await fn(row)
  }
}
