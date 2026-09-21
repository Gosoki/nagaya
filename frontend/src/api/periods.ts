import { api } from 'src/api/client'
import type { Period } from 'src/api/types'

/**
 * 「现在这一期」＝ **最早的未关账账期**。
 *
 * 不是「最新的一期」：语义上你现在欠着的就是最早那张没结清的账单，
 * 转账也是挂到它上面的（后端 assign_period 同一条规则）。
 * 另外用「最新」还有个坑——误记一笔未来日期的账就能把整个页面带跑。
 */
export async function currentPeriod(): Promise<Period | null> {
  const periods = await api.get<Period[]>('/api/periods')   // 后端按 start_date 倒序
  return [...periods].reverse().find((p) => p.status === 'open') ?? periods[0] ?? null
}
