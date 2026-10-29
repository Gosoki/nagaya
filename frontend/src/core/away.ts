/**
 * 离家模式：新记「离家时不算的那一类」（设置 away_category_id，默认伙食）、分摊面板没动过时，
 * 离家的人默认不参与（权重 0、调整额去掉），点头像能加回来。
 *
 * **后端 core/rules.skip_members + services/ledger._away_here 是同一条规则** —— 这里算的是
 * 记一笔那屏的预览，没碰过分摊就存时后端按它那份重算一遍，两边必须一样，改一边要改另一边：
 *   * 只动比例规则（老数据里的定额规则原样不动）；
 *   * 剔完一个参与的人都不剩（全员都离家了）就原样返回，不替人定谁担。
 */
import { seedToRatio } from 'src/core/seed'

export function awaySeed(
  seed: Record<string, unknown> | null,
  keys: string[],
  away: string[],
): Record<string, unknown> | null {
  if (!away.length || ((seed?.mode as string | undefined) ?? 'ratio') === 'exact') return seed
  const r = seedToRatio(seed, keys)
  const weights = Object.fromEntries(keys.map((k) => [k, away.includes(k) ? 0 : (r.weights[k] ?? 0)]))
  if (!Object.values(weights).some((w) => w !== 0)) return seed
  const adjustments = Object.fromEntries(Object.entries(r.adjustments).filter(([k]) => !away.includes(k)))
  return {
    mode: 'ratio',
    weights,
    ...(Object.keys(adjustments).length ? { adjustments } : {}),
    ...(seed?.remainder_to ? { remainder_to: seed.remainder_to } : {}),
  }
}
