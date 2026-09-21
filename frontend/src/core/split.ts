/**
 * 分摊引擎（前端实现）—— SPEC §4.1〜§4.3。
 *
 * 这份和后端 `app/core/split.py` 是**同一个算法的两份实现**：
 * 前端要做「改权重立刻看到每人金额」，不能每敲一下就往返服务器；
 * 后端落库时必须自己再算一遍，永远不信任客户端传来的金额。
 *
 * 两份靠 `tests/fixtures/split_cases.json` 这一份共享用例锁住。
 * **改这里 → 必须同步改 split.py，并让两边的用例都绿。**
 *
 * 一个 JS 特有的注意点：这里全程整数运算，连小数部分的比较都是拿
 * 「同分母下的分子」直接比整数，所以不存在浮点误差。
 */

export type RemainderTo = 'payer' | 'order' | 'rotate'

export class SplitError extends Error {
  constructor(
    public code: string,
    message: string,
    public detail: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'SplitError'
  }
}

export interface RatioRule {
  mode?: 'ratio'
  weights: Record<string, number>
  adjustments?: Record<string, number>
  remainder_to?: RemainderTo
}

export interface ExactRule {
  mode: 'exact'
  exact: Record<string, number>
}

export type SplitRule = RatioRule | ExactRule

export interface SplitOptions {
  order?: string[]
  payer?: string | null
  rotateSeed?: number
}

/** 向下取整的除法 + 余数，全整数、自我纠正浮点误差。b 必须为正。 */
function floorDivMod(a: number, b: number): { q: number; r: number } {
  let q = Math.trunc(a / b)
  let r = a - q * b // a、q、b 都是安全整数，这一步是精确的
  while (r < 0) {
    q -= 1
    r += b
  }
  while (r >= b) {
    q += 1
    r -= b
  }
  return { q, r }
}

function requireInt(value: unknown, field: string, member: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    throw new SplitError('not_integer', `${field}[${member}] 必须是整数，收到 ${String(value)}`, {
      field,
      member,
    })
  }
  return value
}

function resolveMembers(source: Record<string, number>, order?: string[]): string[] {
  if (!order) return Object.keys(source)
  const a = [...order].sort()
  const b = Object.keys(source).sort()
  if (a.length !== b.length || a.some((k, i) => k !== b[i])) {
    throw new SplitError('unknown_member', '参与人和顺序表对不上', { order, source: b })
  }
  return [...order]
}

/** 固定金额模式：合计必须等于总额，对不上就拒绝并给出差额。 */
export function splitExact(
  amount: number,
  exact: Record<string, number>,
  order?: string[],
): Record<string, number> {
  const members = resolveMembers(exact, order)
  const shares: Record<string, number> = {}
  for (const m of members) shares[m] = requireInt(exact[m] ?? 0, 'exact', m)

  const total = members.reduce((sum, m) => sum + shares[m], 0)
  if (total !== amount) {
    const diff = amount - total
    throw new SplitError(
      'sum_mismatch',
      `各人合计 ${total} 円 ≠ 总额 ${amount} 円，差 ${diff > 0 ? '+' : ''}${diff} 円`,
      { diff, total, amount },
    )
  }
  return shares
}

/** 比例 ＋ 调整额模式（自动配平，SPEC §4.2）。 */
export function splitRatio(
  amount: number,
  weights: Record<string, number>,
  opts: SplitOptions & {
    adjustments?: Record<string, number>
    remainderTo?: RemainderTo
  } = {},
): Record<string, number> {
  const { order, payer = null, rotateSeed = 0, adjustments = {}, remainderTo = 'payer' } = opts
  const members = resolveMembers(weights, order)

  for (const m of members) {
    const w = requireInt(weights[m] ?? 0, 'weights', m)
    if (w < 0) throw new SplitError('negative_weight', `权重不能是负数：${m}=${w}`, { member: m, weight: w })
  }
  const unknown = Object.keys(adjustments).filter((m) => !members.includes(m))
  if (unknown.length) {
    throw new SplitError('unknown_member', `调整额给了不在参与人里的人：${unknown.join(', ')}`, {
      members: unknown,
    })
  }
  for (const m of Object.keys(adjustments)) requireInt(adjustments[m], 'adjustments', m)

  const adjTotal = Object.values(adjustments).reduce((s, v) => s + v, 0)
  const base = amount - adjTotal
  const totalW = members.reduce((s, m) => s + (weights[m] ?? 0), 0)

  const shares: Record<string, number> = {}
  if (totalW === 0) {
    if (base !== 0) {
      throw new SplitError('weights_all_zero', `所有权重都是 0，没人分摊这 ${base} 円`, { base })
    }
    for (const m of members) shares[m] = 0
  } else {
    // 各人的小数部分＝ r/totalW，分母相同 → 直接比 r 这个整数，不碰浮点
    const rem: Record<string, number> = {}
    for (const m of members) {
      const { q, r } = floorDivMod(base * (weights[m] ?? 0), totalW)
      shares[m] = q
      rem[m] = r
    }
    let remainder = base - members.reduce((s, m) => s + shares[m], 0)
    if (remainder) {
      const ranked = [...members].sort((x, y) => {
        if (rem[x] !== rem[y]) return rem[y] - rem[x] // 小数部分大的先拿
        return compareTiebreak(x, y, members, remainderTo, payer, rotateSeed)
      })
      for (let i = 0; i < remainder; i++) shares[ranked[i]] += 1
    }
  }

  for (const [m, adj] of Object.entries(adjustments)) shares[m] += adj

  const total = members.reduce((s, m) => s + shares[m], 0)
  if (total !== amount) {
    throw new SplitError('sum_mismatch', `内部错误：分摊结果 ${total} ≠ 总额 ${amount}`, { total, amount })
  }
  return shares
}

function tiebreakKey(
  member: string,
  members: string[],
  remainderTo: RemainderTo,
  payer: string | null,
  rotateSeed: number,
): number[] {
  const idx = members.indexOf(member)
  if (remainderTo === 'payer') return [member === payer ? 0 : 1, idx]
  if (remainderTo === 'order') return [idx]
  if (remainderTo === 'rotate') return [(idx + rotateSeed) % members.length]
  throw new SplitError('unknown_remainder_to', `未知的余数规则：${remainderTo}`, { remainderTo })
}

function compareTiebreak(
  x: string,
  y: string,
  members: string[],
  remainderTo: RemainderTo,
  payer: string | null,
  rotateSeed: number,
): number {
  const a = tiebreakKey(x, members, remainderTo, payer, rotateSeed)
  const b = tiebreakKey(y, members, remainderTo, payer, rotateSeed)
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d !== 0) return d
  }
  return 0
}

/** 按 split_rule_json 分发。和后端 `split()` 一一对应。 */
export function split(rule: SplitRule, amount: number, opts: SplitOptions = {}): Record<string, number> {
  const mode = (rule as ExactRule).mode ?? 'ratio'
  if (mode === 'exact') {
    return splitExact(amount, (rule as ExactRule).exact ?? {}, opts.order)
  }
  if (mode === 'ratio') {
    const r = rule as RatioRule
    return splitRatio(amount, r.weights ?? {}, {
      ...opts,
      adjustments: r.adjustments,
      remainderTo: r.remainder_to ?? 'payer',
    })
  }
  throw new SplitError('unknown_mode', `未知的分摊模式：${mode}`, { mode })
}
