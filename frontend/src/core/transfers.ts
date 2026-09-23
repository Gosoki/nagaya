/**
 * 账单上一笔转账**此刻**还该转多少。BillView 的按钮、大字、进度、复制出去的文本
 * 全经过这一处；后端 bill.pair_left 是同一个口径（「确认已完成」在那边再核一遍）。
 *
 * 两头取小：
 *   * 「这一笔还剩多少」＝ 方案额 − 出账后已经转过的（settled_paid）；
 *   * 「这一对此刻还欠多少」＝ 实时方案（live_transfers）里同一对的金额。
 *     **找不到这一对就是 0**：出账之后大家换了条路结清（现金、并单转、经第三人），
 *     或者被后来的账净额化掉，这一对就再也不会走钱。原来这里退回成「方案剩余额」，
 *     按钮照样亮，一按就凭空造一笔债。
 * 后端压根没给实时方案（老缓存里的账单）时，才退回方案剩余额。
 *
 * 这里也放账单头卡「我这期」的判定（mineOf 和它用的两个小函数）：它们没有后端对应物，
 * 但同样是纯函数、不碰 i18n —— 历次审计里出事最多的就是这一块，放在这儿才写得了单测。
 * 只返回「谁、多少」，文案由 BillView 按 kind 去拼。
 */
import type { Bill, BillTransfer } from 'src/api/types'

type BillLike = Pick<Bill, 'settled_paid' | 'live_transfers'>

export function leftOf(bill: BillLike, tr: BillTransfer, i: number): number {
  const rest = tr.amount - (bill.settled_paid?.[i] ?? 0)
  if (!bill.live_transfers) return Math.max(0, rest)
  const live =
    bill.live_transfers.find((x) => x.from_id === tr.from_id && x.to_id === tr.to_id)?.amount ?? 0
  return Math.max(0, Math.min(rest, live))
}

type Row = { member_id: number; closing: number }

/**
 * 这张单子的方案里有行**永远点不亮了** —— 钱已经绕别的路结清，
 * 或者后来的账把债权重新净额化了。这时候得说一句，否则那张永远挂着「未结清」
 * 而没人知道为什么。
 */
export function supersededIn(
  b: Pick<Bill, 'is_draft' | 'transfers' | 'settled_transfers' | 'settled_paid' | 'live_transfers'>,
): boolean {
  return !b.is_draft && b.transfers.some((tr, i) => !b.settled_transfers[i] && leftOf(b, tr, i) === 0)
}

/**
 * 方案里没有我这条边时，我在这张单子上**此刻**还差多少。和 leftOf 同一个「两头取小」：
 *   * 不超过这张单子自己的数 —— 翻七月那张，不该跳出今天的欠款；
 *   * 此刻已经两清（或者方向反过来了）就是 0 —— 原来直接印这张单子的 closing，
 *     钱早就转过了，大字还写着「你应付 ¥X」
 */
export function effClosing(b: Pick<Bill, 'live_closing'>, row: Row): number {
  const live = Number(b.live_closing?.[String(row.member_id)] ?? row.closing)
  if (Math.sign(live) !== Math.sign(row.closing)) return 0
  return Math.sign(row.closing) * Math.min(Math.abs(row.closing), Math.abs(live))
}

/** 账单头卡「我这期」该说什么。只有谁和多少，没有文案 */
export type Mine =
  | { kind: 'notIn' }
  | { kind: 'settled' }
  | { kind: 'pay'; to: number; amount: number }
  | { kind: 'payMany'; items: { to: number; amount: number }[] }
  | { kind: 'receive'; amount: number }
  | { kind: 'owe'; amount: number }

/**
 * 我在这张单子上此刻该转、该收多少。**按「此刻」说话，不按出账那一刻**（见 leftOf /
 * effClosing），口径限定在这张单子的方案里。分支顺序别动：每一档都是某次审计修出来的。
 */
export function mineOf(
  b: Pick<Bill, 'transfers' | 'settled_paid' | 'live_transfers' | 'live_closing'> | null,
  row: Row | null,
): Mine {
  // 我不在这张单子上（后来才搬进来的人翻旧账单）
  if (!row || !b) return { kind: 'notIn' }
  const me = row.member_id
  const rows = b.transfers
    .map((tr, i) => ({ tr, left: leftOf(b, tr, i) }))
    .filter((x) => (x.tr.from_id === me || x.tr.to_id === me) && x.left > 0)
  const out = rows.filter((x) => x.tr.from_id === me)
  const inc = rows.filter((x) => x.tr.to_id === me)
  if (out.length === 1 && !inc.length) return { kind: 'pay', to: out[0]!.tr.to_id, amount: out[0]!.left }
  if (inc.length && !out.length) return { kind: 'receive', amount: inc.reduce((n, x) => n + x.left, 0) }
  const inPlan = b.transfers.some((tr) => tr.from_id === me || tr.to_id === me)
  if (!out.length && !inc.length && inPlan) return { kind: 'settled' }
  if (!inPlan) {
    const eff = effClosing(b, row)
    if (eff === 0) return { kind: 'settled' }
    return eff > 0 ? { kind: 'receive', amount: eff } : { kind: 'owe', amount: -eff }
  }
  // 要转给好几个人：**得全列出来**（原来只取第一条、却把欠款总额安在那个人头上）。
  // 只转给一个人（同时还有人要转给我）照单笔那一档
  if (out.length === 1) return { kind: 'pay', to: out[0]!.tr.to_id, amount: out[0]!.left }
  if (out.length) return { kind: 'payMany', items: out.map((x) => ({ to: x.tr.to_id, amount: x.left })) }
  return { kind: 'settled' }   // 走不到：上面几档已经把所有情况分完了
}
