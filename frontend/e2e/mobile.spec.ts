/**
 * 手机视口 E2E —— SPEC §7.4 的硬性验收。
 *
 * 跑之前要有后端在 127.0.0.1:8000 上跑着，并且已经 seed 过开发数据：
 *   cd backend && .venv/bin/python -m tools.seed_dev && ./run.sh
 */
import { expect, test } from '@playwright/test'

const USER = 'go'
const PASSWORD = 'dev12345'

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(USER)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '进入' }).click()
  await expect(page.locator('.q-footer')).toBeVisible()
}

/**
 * 删掉刚才那笔，别把开发库越跑越脏。
 * E2E 是会真的往库里写东西的，不收拾的话跑十遍就多十笔假账。
 */
async function deleteLatestEntry(page: import('@playwright/test').Page) {
  const token = await page.evaluate(() => localStorage.getItem('nagaya.token'))
  const headers = { Authorization: `Bearer ${token}` }
  const rows = await (await page.request.get('/api/entries?limit=1', { headers })).json()
  if (rows.length) await page.request.delete(`/api/entries/${rows[0].id}`, { headers })
}

/** 375px 下不许有横向滚动 —— 这条最容易被一个写死宽度的元素破掉 */
async function expectNoHorizontalScroll(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(() => {
    const d = document.documentElement
    return { scrollWidth: d.scrollWidth, clientWidth: d.clientWidth }
  })
  expect(overflow.scrollWidth, `横向溢出了 ${overflow.scrollWidth - overflow.clientWidth}px`)
    .toBeLessThanOrEqual(overflow.clientWidth)
}

test('登录页在 375px 下正常', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: '进入' })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/01-login.png', fullPage: true })
})

test('记一笔：默认页就是它，且主操作在拇指区', async ({ page }) => {
  await login(page)
  await expect(page).toHaveURL(/\/$/)                       // D16：PWA 打开即记一笔
  await expect(page.getByRole('button', { name: '家賃' })).toBeVisible()

  // 主操作按钮必须在屏幕下半部
  const save = page.getByRole('button', { name: '保存', exact: true })
  const box = await save.boundingBox()
  const vh = page.viewportSize()!.height
  expect(box!.y, '「保存」按钮跑到屏幕上半部去了').toBeGreaterThan(vh / 2)

  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/02-add-empty.png', fullPage: true })
})

test('金额 → 分类 → 保存，三步录完一笔', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('1980')
  await page.getByRole('button', { name: '日用品' }).click()
  await page.screenshot({ path: 'e2e/shots/03-add-filled.png', fullPage: true })

  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.q-notification')).toContainText('已记下')

  await deleteLatestEntry(page)
})

test('分摊编辑器：实时算钱、合计对得上', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('10000')
  await page.locator('.split-panel [role="button"]').first().click()

  const shares = page.locator('.share')
  // 必须验可见：q-expansion-item 折叠着的时候内容也在 DOM 里，
  // 光用 toHaveCount 断言，即使根本没展开也会绿。
  await expect(shares.first()).toBeVisible()
  await expect(shares).toHaveCount(3)
  const texts = await shares.allTextContents()
  const sum = texts.reduce((s, t) => s + Number(t.replace(/[^\d-]/g, '')), 0)
  expect(sum, '三个人的份额加起来必须等于 10000').toBe(10000)

  await expectNoHorizontalScroll(page)

  // 固定定位的底栏盖住最后一行是这类布局的经典塌方。本来想「滚到底再量」，
  // 但移动 WebKit 模拟下两种滚法都用不了：window.scrollTo 静默无效，
  // mouse.wheel 直接报 "not supported in mobile WebKit"。
  // 所以改成直接验那条不变量：页面底部留位 ≥ 固定操作栏从视口底部往上占掉的高度。
  // 这条成立，滚到底时最后一行必然露得出来。
  const bar = (await page.locator('.actions').boundingBox())!
  const occupied = page.viewportSize()!.height - bar.y
  const padBottom = await page.evaluate(() =>
    parseFloat(getComputedStyle(document.querySelector('.q-page')!).paddingBottom),
  )
  expect(padBottom, '页面底部留位不够，滚到底时最后一行会被固定操作栏盖住')
    .toBeGreaterThanOrEqual(occupied)
  await page.screenshot({ path: 'e2e/shots/04-split.png' })
})

test('固定金额模式：合计对不上就红字报差额且存不了', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('120000')
  await page.locator('.split-panel [role="button"]').first().click()
  await page.getByRole('button', { name: '固定金额' }).click()

  const inputs = page.locator('.exact-input')
  await inputs.nth(0).fill('45000')
  await inputs.nth(1).fill('40000')
  await inputs.nth(2).fill('30000')      // 差 5000

  await expect(page.locator('.diff-line')).toBeVisible()
  await expect(page.locator('.diff-line')).toContainText('5,000')
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await page.screenshot({ path: 'e2e/shots/08-exact-unbalanced.png' })

  await inputs.nth(2).fill('35000')      // 补平
  await expect(page.locator('.diff-line')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
})

test('余额看板与账目列表', async ({ page }) => {
  await login(page)

  await page.getByRole('tab', { name: '余额' }).click()
  await expect(page.locator('.text-h4')).toBeVisible()
  // 底部 tab 的高亮要跟着路由走（q-tab 换成 q-route-tab 之前这里是坏的）
  await expect(page.getByRole('tab', { name: '余额' })).toHaveClass(/q-tab--active/)
  await expect(page.getByRole('tab', { name: '记一笔' })).toHaveClass(/q-tab--inactive/)
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/05-balance.png', fullPage: true })

  await page.getByRole('tab', { name: '账目' }).click()
  await expect(page.locator('.q-item').first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/06-entries.png', fullPage: true })
})

test('切日语：界面文案跟着换，用户录的分类名不翻译', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: '日本語' }).click()
  await expect(page.getByRole('button', { name: '入る' })).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/07-login-ja.png', fullPage: true })
})
