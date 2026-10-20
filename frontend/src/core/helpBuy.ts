/**
 * 这笔是不是「帮买」：一笔支出，付款人自己一分不担、全算在**一个**别人头上。是就返回那个人的 id。
 *
 * 帮买不是单独一种账（记一笔那屏是转账页里的一个开关），存下去就是一笔普通支出 ——
 * 余额、转账方案、「已结清」全照支出算，只有显示时要认出来：流水上写「替 Kan 买」、
 * 编辑时停回转账页并把开关点亮。
 * **后端 services/bill.help_buy_for 是同一条规则**，改一边要改另一边（各有单测钉着）。
 */
import type { Entry } from 'src/api/types'

export function helpBuyFor(e: Pick<Entry, 'kind' | 'payer_id' | 'shares'>): number | null {
  if (e.kind !== 'expense') return null
  const bearers = Object.entries(e.shares ?? {})
    .filter(([, v]) => v !== 0)
    .map(([id]) => Number(id))
  return bearers.length === 1 && bearers[0] !== e.payer_id ? bearers[0]! : null
}
