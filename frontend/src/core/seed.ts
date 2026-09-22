/**
 * 一条「起步规则」（分类默认、上期那一笔、这笔自己存下的）在分摊面板上长什么样：
 * 每人的比例 + 调整额。**SplitEditor 的预览和「没碰过分摊就存」必须走同一份** ——
 * 原来固定费面板上没录的行按上期分摊预览，存的时候却发 rule=null，
 * 后端落成分类默认：屏幕上 45,000/40,000/35,000，库里是均分。
 *
 * 老数据里还有 mode:'exact' 的规则（界面上已经没有这个模式了）。原样换算成
 * 「权重全 1 + 调整额」：基数取 floor(总额/人数)，调整额就是各人金额减掉基数 ——
 * 加回去一分不差。总额取规则自己的和，不依赖当前金额；所以金额变了也照样能分，
 * 而原样发 exact 的话，金额一变后端就按「合计对不上」拒收。
 */
export interface RatioSeed {
  weights: Record<string, number>
  adjustments: Record<string, number>
}

export function seedToRatio(seed: Record<string, unknown> | null | undefined, keys: string[]): RatioSeed {
  const mode = (seed?.mode as string) ?? 'ratio'
  if (seed && mode === 'exact') {
    const exact = (seed.exact ?? {}) as Record<string, number>
    const total = keys.reduce((sum, k) => sum + Number(exact[k] ?? 0), 0)
    const base = Math.floor(total / (keys.length || 1))
    return {
      weights: Object.fromEntries(keys.map((k) => [k, 1])),
      adjustments: Object.fromEntries(
        keys.map((k) => [k, Number(exact[k] ?? 0) - base] as const).filter(([, v]) => v !== 0),
      ),
    }
  }
  const seededW = (seed?.weights ?? null) as Record<string, number> | null
  const equal = Number(seed?.equal_weight ?? 1)
  const seededAdj = (seed?.adjustments ?? {}) as Record<string, number>
  return {
    weights: Object.fromEntries(keys.map((k) => [k, seededW ? Number(seededW[k] ?? 0) : equal])),
    adjustments: Object.fromEntries(
      Object.entries(seededAdj).filter(([k, v]) => keys.includes(k) && Number(v) !== 0),
    ),
  }
}
