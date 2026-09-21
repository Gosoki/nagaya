/**
 * 底栏「账单」那一格代表一整个分区，不是 /bill 那一页。
 *
 * 原来用 q-route-tab，高亮跟着 vue-router 的 matched 链走；而 /bill/current
 * 和 /bill/past 是跟 /bill **平级**的路由（不是子路由），站在那两页上底栏
 * 三格一个都不亮。改成自己算分区之后，风险变成「新加了一条账单路由却忘了
 * 登记」—— 症状一模一样，所以这里盯着它。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), 'utf8')

const routerSrc = read('../src/router/index.ts')
const layoutSrc = read('../src/layouts/MainLayout.vue')

/** 路由表里每条 { path: 'x', name: 'y' } */
const routes = [...routerSrc.matchAll(/path:\s*'([^']*)',\s*name:\s*'([^']+)'/g)].map(
  ([, path, name]) => ({ path: path!, name: name! }),
)

const section = layoutSrc.match(/const BILL_SECTION = \[([^\]]*)\]/)
const billSection = [...(section?.[1] ?? '').matchAll(/'([^']+)'/g)].map((m) => m[1]!)

describe('底栏高亮覆盖到整个分区', () => {
  it('路由表和分区表都读得到', () => {
    expect(routes.length).toBeGreaterThan(5)
    expect(billSection).toContain('bill')
  })

  it('每一条账单路由都登记在「账单」这一格下面', () => {
    const billRoutes = routes.filter((r) => r.path.startsWith('bill')).map((r) => r.name)
    expect(billRoutes.length).toBeGreaterThanOrEqual(3)
    for (const name of billRoutes) expect(billSection).toContain(name)
  })

  it('固定费那一屏也算账单分区 —— 它只能从账单页进去', () => {
    expect(billSection).toContain('monthly')
  })

  it('登记的都是真实存在的路由，别留下改名后的死名字', () => {
    const names = new Set(routes.map((r) => r.name))
    for (const name of billSection) expect(names).toContain(name)
  })
})
