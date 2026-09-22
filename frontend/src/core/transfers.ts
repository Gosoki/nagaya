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
