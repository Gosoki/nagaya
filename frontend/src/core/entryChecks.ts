/**
 * 记一笔那屏保存前「多问一句」的几条判据（AddEntryPage）。
 *
 * 全是**弱证据**：预付（D3）、拖了一轮再还、搬走的人回来还钱、同一天真转了两次 ——
 * 这些都是正当的。所以这里只回答「要不要问」，问法由页面定，而且默认按钮一律是「照记」：
 * 不拦、不改、不替人丢。判错的代价是多点一下，替人做了决定的代价是记错钱。
 * 纯函数、不碰 i18n，和 core/transfers 一个做法，好写单测（test/entry-checks.spec.ts）。
 */
import type { Entry, Member } from 'src/api/types'

/**
 * 一笔转账看着可疑的地方（看此刻的余额和此刻的方案，余额取不到就别问）：
 *   'direction' —— 付款人此刻是被欠钱的、收款人是欠钱的：这一笔会让收款人再多欠一截。
 *                  方向记反（Kan 还了钱，记成了 Go → Kan）就长这样，帮人买东西忘了开「帮买」也是；
 *   'over'      —— 比参考额还多出 tolerance 以上：多打了一个 0，或者是预付。
 * 两样都中时只问方向：方向反了的那笔，金额那句也会一起冒出来，问两遍只会让人点得更快。
 * balances 的正负和后端一样：正 ＝ 别人欠他，负 ＝ 他欠别人。tolerance 0 ＝ 不核金额。
 *
 * planLeft 是**此刻方案**（草稿账单的 transfers）里 payer → to 这一对的额，没有这一对、取不到方案都是 0。
 * 关掉「算最少转账」（按原始债权逐对算）时，一对的额可以比付款人的净欠还大，净被欠钱的人
 * 也可能在方案里欠某一个人 —— 照方案付是正当的。所以：方案里有这一对就不问方向，
 * 金额的参考额取「付款人实欠」和「这一对的额」里大的那个（owe 返回的就是它）。
 * 最少转账模式下这一对不会超过实欠，等于只看实欠，行为不变
 */
export type TransferDoubt =
  | { kind: 'direction'; payerOwed: number; toOwes: number }
  | { kind: 'over'; owe: number; over: number }
  | null

export function transferDoubt(
  balances: Record<string, number>,
  payer: number,
  to: number,
  amount: number,
  tolerance: number,
  planLeft = 0,
): TransferDoubt {
  const p = Number(balances[String(payer)] ?? 0)
  const r = Number(balances[String(to)] ?? 0)
  if (planLeft <= 0 && p > 0 && r < 0) return { kind: 'direction', payerOwed: p, toOwes: -r }
  const owe = Math.max(0, -p, planLeft)
  if (tolerance > 0 && amount > owe + tolerance) return { kind: 'over', owe, over: amount - owe }
  return null
}

/**
 * 后端的时间戳是 naive UTC（不带时区后缀），按 UTC 解析成毫秒。
 * 带了 Z 或 ±hh:mm 的照原样解析
 */
const utcMs = (ts: string): number => Date.parse(/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(ts) ? ts : `${ts}Z`)

/**
 * hours 小时之内**记过**一笔一模一样的转账（同一对人、同方向、同金额）没有：有就是那一笔。
 * 转出方在账单上点了「确认已完成」、转入方又在这儿记了一次，两笔都进账，
 * 余额动两倍 —— 实时方案还会转头叫第三个人去转钱。按记账时刻（created_at）算，不按业务日期：
 * 要防的是「刚才是不是有人记过了」。hours 0 ＝ 不问
 */
export function recentTwin(
  entries: readonly Entry[],
  body: { payer_id: number; to_member_id: number | null; amount_jpy: number },
  hours: number,
  now: number = Date.now(),
): Entry | null {
  if (hours <= 0 || body.to_member_id === null) return null
  const since = now - hours * 3_600_000
  return (
    entries.find(
      (e) =>
        e.kind === 'settlement' &&
        e.payer_id === body.payer_id &&
        e.to_member_id === body.to_member_id &&
        Math.abs(e.amount_jpy) === Math.abs(body.amount_jpy) &&
        utcMs(e.created_at) >= since,
    ) ?? null
  )
}

/**
 * 付款人在这笔的日期当天住不住这儿：'left' ＝ 那天已经搬走，'notYet' ＝ 那天还没入住，null ＝ 在籍。
 * 后端照收（搬走的人那天之后垫的钱，另外两个人要全担）—— 多半是搬走的人自己的手机
 * 默认填了自己，或者日期点错了一年。和 meta.membersOn 同一个口径（两头含当天）
 */
export function payerAbsence(m: Pick<Member, 'joined_on' | 'left_on'>, date: string): 'left' | 'notYet' | null {
  if (date < m.joined_on) return 'notYet'
  if (m.left_on && date > m.left_on) return 'left'
  return null
}
