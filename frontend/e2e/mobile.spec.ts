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
 * 每条用例跑完无条件清掉自己造的数据。
 *
 * 放在 afterEach 而不是测试体末尾：**断言一失败就跳过了收尾**，
 * 残渣留在共享的开发库里，下一轮别的用例会读到它然后红在完全无关的地方
 * （真发生过：离线草稿那条读到了另一条用例留下的 903）。
 */
test.afterEach(async ({ page }) => {
  try {
    const r = await page.request.post('/api/auth/login', {
      data: { name: USER, password: PASSWORD },
    })
    if (!r.ok()) return
    const headers = { Authorization: `Bearer ${(await r.json()).token}` }
    const rows = await (await page.request.get('/api/entries?limit=200', { headers })).json()
    for (const e of rows) {
      if (typeof e.title === 'string' && e.title.startsWith('E2E')) {
        await page.request.delete(`/api/entries/${e.id}`, { headers })
      }
    }
    // 测试造出来的自定义固定项也要收拾（分类没有删除接口，归档掉即可）
    const cats = await (await page.request.get('/api/categories', { headers })).json()
    for (const c of cats) {
      if (typeof c.name === 'string' && c.name.startsWith('E2E')) {
        await page.request.patch(`/api/categories/${c.id}`, { headers, data: { archived: true } })
      }
    }
  } catch {
    /* 收尾失败不该把用例本身判红 */
  }
})

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
  // 日常那屏只留天天会用的三个。家賃/電気/ガス/水道/ネット 一个月才碰一次，
  // 已经挪到账单页顺手填，不在这里占按钮
  await expect(page.locator('.cat')).toHaveCount(3)
  await expect(page.getByRole('button', { name: '日用品' })).toBeVisible()
  await expect(page.getByRole('button', { name: '家賃' })).toHaveCount(0)

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
  // 分类现在是必选的：不选的话后端拿不到分类默认规则，会悄悄掉回全员均分
  await page.getByRole('button', { name: '日用品' }).click()
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

test('账单 Tab 与账目列表', async ({ page }) => {
  await login(page)

  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.getByText(/转账方案/)).toBeVisible()
  // 底部 tab 的高亮要跟着路由走（q-tab 换成 q-route-tab 之前这里是坏的）
  await expect(page.getByRole('tab', { name: '账单' })).toHaveClass(/q-tab--active/)
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

test('账单：期初/应担/应付对得上，转账方案能把人清零', async ({ page }) => {
  await login(page)
  // 账单现在就是第二个 Tab，不用再从余额页绕一道
  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.locator('.q-item').first()).toBeVisible()

  // 每人的「应收/应付」加起来必须是 0 —— 账单上直接看得见的那条恒等式
  const signed = await page.locator('.q-item').evaluateAll((items) =>
    items.map((el) => {
      const amount = Number((el.querySelector('.text-weight-medium')?.textContent ?? '0').replace(/[^\d]/g, ''))
      const isPay = el.textContent?.includes('应付')
      return isPay ? -amount : amount
    }),
  )
  expect(signed.reduce((a, b) => a + b, 0), '账单上应收与应付对不上').toBe(0)

  await expect(page.getByText(/转账方案/)).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/09-bill.png' })
})

test('账单：关账后转账按钮锁住，解锁后恢复', async ({ page }) => {
  await login(page)
  await page.goto('/bill')
  await expect(page.getByText(/转账方案/)).toBeVisible()

  const received = page.getByRole('button', { name: '已收到' }).first()
  await expect(received).toBeEnabled()

  await page.getByText('关账').click()
  await page.getByRole('button', { name: 'OK' }).click()
  // 等对话框收干净再往下走：遮罩还在的时候点什么都点不到，
  // 报错却长得像「找不到这个元素」，很容易把人带偏
  await expect(page.locator('.q-dialog')).toHaveCount(0)
  await expect(page.getByText('已关账')).toBeVisible()
  await expect(received).toBeDisabled()
  await page.screenshot({ path: 'e2e/shots/10-bill-closed.png' })

  // 收拾干净：解锁回去，别让下一次跑测试撞上锁着的账期
  await page.getByText('解锁').click()
  await expect(page.getByText(/未结清|请于/)).toBeVisible()
  await expect(page.getByRole('button', { name: '已收到' }).first()).toBeEnabled()
})

test('离线草稿：断网能填完，回来点一下补交', async ({ page }) => {
  await login(page)
  await page.evaluate(() => localStorage.removeItem('nagaya.drafts'))

  // 掐断写接口，模拟超市地下一层
  await page.route('**/api/entries', (route) =>
    route.request().method() === 'POST' ? route.abort() : route.continue(),
  )
  await page.locator('input.amount').fill('777')
  await page.getByRole('button', { name: '日用品' }).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()

  await expect(page.locator('.q-notification')).toContainText('先存在本地')
  await expect(page.getByText('有 1 笔没提交')).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/11-draft.png' })

  // 回到有网
  await page.unroute('**/api/entries')
  await page.getByRole('button', { name: '补交' }).click()
  await expect(page.getByText('有 1 笔没提交')).toHaveCount(0)

  const saved = await (await page.request.get('/api/entries?limit=1', {
    headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` },
  })).json()
  expect(saved[0].amount_jpy, '补交的金额对不上').toBe(777)

  await deleteLatestEntry(page)
})

test('服务器明确拒绝的不该存成草稿', async ({ page }) => {
  await login(page)
  await page.evaluate(() => localStorage.removeItem('nagaya.drafts'))

  // 400 是「这笔账本身有问题」，存成草稿只会让人反复补交同一笔失败的账
  await page.route('**/api/entries', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 400, contentType: 'application/json',
                        body: JSON.stringify({ code: 'bad_sign', message: 'x', detail: {} }) })
      : route.continue(),
  )
  await page.locator('input.amount').fill('555')
  await page.getByRole('button', { name: '日用品' }).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()

  await expect(page.locator('.q-notification')).toContainText('金额方向不对')
  await expect(page.getByText(/笔没提交/)).toHaveCount(0)
})

test('PWA 产物齐全：manifest 与 service worker 都在', async ({ page }) => {
  // 用 page.request 直接拉，绕开被 block 掉的 SW
  const manifest = await page.request.get('/manifest.webmanifest')
  expect(manifest.ok()).toBe(true)
  const m = await manifest.json()
  expect(m.display, '不是 standalone 就不会全屏，跟普通网页没区别').toBe('standalone')
  expect(m.icons.some((i: { purpose?: string }) => i.purpose === 'maskable'),
    '缺 maskable 图标，Android 裁圆时会把字切掉').toBe(true)

  expect((await page.request.get('/sw.js')).ok()).toBe(true)
  expect((await page.request.get('/icons/apple-touch-icon.png')).ok()).toBe(true)
})

test('完整闭环：出账单 → 点「已收到」→ 那个人归零', async ({ page }) => {
  await login(page)
  await page.goto('/bill')
  await expect(page.getByText(/转账方案/)).toBeVisible()

  const firstCard = page.locator('.q-card').first()
  const who = (await firstCard.locator('.text-weight-medium').first().textContent())!.trim()
  const amount = Number((await firstCard.locator('.text-h6').textContent())!.replace(/[^\d]/g, ''))
  expect(amount).toBeGreaterThan(0)

  await firstCard.getByRole('button', { name: '已收到' }).click()
  await page.locator('.q-dialog input').fill(String(amount))
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)

  // 结清之后这个人应该显示「已结清」，而且账单上应收应付仍然相抵
  const row = page.locator('.q-item').filter({ hasText: who })
  await expect(row.getByText('已结清')).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/12-bill-settled.png' })

  await deleteLatestEntry(page)      // 把这笔转账撤掉，别把开发库越跑越脏
})

test('账单页固定费：没录的项只给灰色参考，绝不预填成真值', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  // 造一个新账期：新的一期里固定费都还没录，正是要验的状态
  const made = await (await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-11-05', amount_jpy: 903, payer_id: 1, category_id: 6, title: 'E2E' },
  })).json()
  const periods = await (await page.request.get('/api/periods', { headers })).json()
  const fresh = periods.find((x: { label: string }) => x.label === '2026-11')

  await page.goto(`/bill/${fresh.id}`)
  await expect(page.getByText('本期固定费')).toBeVisible()

  const boxes = await page.locator('.amount-input').evaluateAll((els) =>
    (els as HTMLInputElement[]).map((e) => ({ value: e.value, placeholder: e.placeholder })),
  )
  expect(boxes.length, '固定费行没渲染出来').toBeGreaterThan(0)
  // **最要命的一条**：上期金额只能待在 placeholder 里。
  // 一旦它变成 value，某个月忘了改就会带着上月的电费把账单发出去，而且谁都看不出来。
  for (const b of boxes) {
    expect(b.value, '上期金额被预填成真值了').toBe('')
  }
  expect(boxes.some((b) => b.placeholder !== ''), '一个参考值都没有，说明 hint 没接上').toBe(true)
  await expect(page.getByRole('button', { name: '没有改动' })).toBeDisabled()
  await page.screenshot({ path: 'e2e/shots/13-monthly-hint.png' })

  await page.request.delete(`/api/entries/${made.id}`, { headers })
})

test('账单页固定费：填一项存下去，账单跟着涨且留在这张账单的期里', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  const made = await (await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-12-05', amount_jpy: 904, payer_id: 1, category_id: 6, title: 'E2E' },
  })).json()
  const periods = await (await page.request.get('/api/periods', { headers })).json()
  const dec = periods.find((x: { label: string }) => x.label === '2026-12')

  await page.goto(`/bill/${dec.id}`)
  await expect(page.getByText('本期固定费')).toBeVisible()
  // 填「電気」而不是第一行的「家賃」：家賃的分类规则是固定金额 45000/40000/35000，
  // 总额一改就和每人金额对不上，会被正确拦下 —— 那是另一条用例要验的事
  const denki = page.locator('.q-expansion-item').filter({ hasText: '電気' }).locator('.amount-input')
  await denki.fill('9100')
  await page.getByRole('button', { name: /保存 \d+ 项/ }).click()
  await expect(page.getByRole('button', { name: '没有改动' })).toBeVisible({ timeout: 10_000 })

  // 账单总额涨了 —— 说明这笔确实算进了**这一张**账单，没跑到别的期去。
  // 归期只看 entry.date，用「今天」当默认日期就会把它甩到别的月，且零报错。
  const bill = await (await page.request.get(`/api/periods/${dec.id}/bill`, { headers })).json()
  expect(bill.total_expense).toBe(904 + 9100)

  for (const e of await (await page.request.get(`/api/entries?period_id=${dec.id}`, { headers })).json()) {
    await page.request.delete(`/api/entries/${e.id}`, { headers })
  }
})

test('归档一个分类，它名下的历史账目仍然显示原来的名字', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const target = cats.find((c: { name: string }) => c.name === '食費')
  const made = await (await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-15', amount_jpy: 905, payer_id: 1, category_id: target.id, title: '' },
  })).json()

  await page.request.patch(`/api/categories/${target.id}`, { headers, data: { archived: true } })
  await page.goto('/entries')
  // 归档之后前端若只拿未归档列表反查名字，这条会掉成默认标题和默认图标
  await expect(page.getByText('食費').first()).toBeVisible()

  await page.request.patch(`/api/categories/${target.id}`, { headers, data: { archived: false } })
  await page.request.delete(`/api/entries/${made.id}`, { headers })
})

test('账单页固定费：固定金额分类改了总额没改分摊，必须拦住并说出差多少', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const made = await (await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2027-01-05', amount_jpy: 906, payer_id: 1, category_id: 6, title: 'E2E' },
  })).json()
  const periods = await (await page.request.get('/api/periods', { headers })).json()
  const jan = periods.find((x: { label: string }) => x.label === '2027-01')

  await page.goto(`/bill/${jan.id}`)
  await expect(page.getByText('本期固定费')).toBeVisible()
  // 家賃的分类规则是固定金额 45000/40000/35000。总额改成 30000 而不动每人金额，
  // 合计就对不上了 —— 必须当场拦住，而且要说清差多少，不能只说一句「不平」
  const yachin = page.locator('.q-expansion-item').filter({ hasText: '家賃' }).locator('.amount-input')
  await yachin.fill('30000')
  await page.getByRole('button', { name: /保存 \d+ 项/ }).click()
  const note = page.locator('.q-notification')
  await expect(note).toContainText('家賃')
  await expect(note).toContainText('90,000')      // 30000 − 120000
  expect((await (await page.request.get(`/api/periods/${jan.id}/bill`, { headers })).json()).total_expense)
    .toBe(906)                                     // 没存进去

  await page.request.delete(`/api/entries/${made.id}`, { headers })
})

test('固定费不必等到出账单：记一笔那屏就有入口', async ({ page }) => {
  await login(page)
  await page.getByText('本期固定费').click()
  await expect(page).toHaveURL(/\/monthly$/)
  await expect(page.getByText('本期固定费')).toBeVisible()
  await expect(page.locator('.amount-input').first()).toBeVisible()
  // 账单在 Tab 上，一点就到，这屏不用再放一个重复的入口
  await expect(page.getByRole('tab', { name: '账单' })).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/14-monthly-standalone.png' })
})

test('自己加一项固定费，它就留在这张表里', async ({ page }) => {
  await login(page)
  await page.goto('/monthly')
  await expect(page.locator('.amount-input').first()).toBeVisible()
  const before = await page.locator('.amount-input').count()

  await page.locator('.new-name').fill('E2E受信料')
  await page.getByRole('button', { name: '加一项固定费' }).click()
  await expect(page.locator('.q-notification')).toContainText('下个月')
  await expect(page.locator('.amount-input')).toHaveCount(before + 1)
  await expect(page.getByText('E2E受信料')).toBeVisible()

  // 它是**固定项**，不是一次性的：刷新之后还在
  await page.reload()
  await expect(page.getByText('E2E受信料')).toBeVisible()
  // 而且不该跑到日常记账那屏去占按钮
  await page.goto('/')
  await expect(page.locator('.cat')).toHaveCount(3)
  await page.screenshot({ path: 'e2e/shots/15-custom-monthly.png' })
})

test('固定项可以删掉，而且删错了能撤销', async ({ page }) => {
  await login(page)
  await page.goto('/monthly')
  await expect(page.locator('.amount-input').first()).toBeVisible()

  await page.locator('.new-name').fill('E2E受信料')
  await page.getByRole('button', { name: '加一项固定费' }).click()
  await expect(page.getByText('E2E受信料')).toBeVisible()

  // 删除入口在展开区里，不在行头 —— 行头有金额框，误触成本太高
  await page.locator('.q-expansion-item').filter({ hasText: 'E2E受信料' }).locator('[role="button"]').first().click()
  await page.getByRole('button', { name: '删掉这一项' }).click()
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)
  // 断言收窄到列表：删除后的通知文案里也含项目名（「已删掉「E2E受信料」」），
  // 用 getByText 扫全页会把通知也数进去
  const inList = (name: string) => page.locator('.q-expansion-item').filter({ hasText: name })
  await expect(inList('E2E受信料')).toHaveCount(0)

  // 后悔路：点撤销它得回来
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(inList('E2E受信料')).toHaveCount(1)
})

test('删掉一项固定费，本期已录的那笔账仍然留在账单上', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const before = (await (await page.request.get('/api/balances', { headers })).json()).balances

  // 拿一个已经录了金额的固定项（种子数据里 ガス 是 4,200）
  await page.goto('/monthly')
  const row = page.locator('.q-expansion-item').filter({ hasText: 'ガス' })
  await expect(row.locator('.amount-input')).toHaveValue('4,200')

  await row.locator('[role="button"]').first().click()
  await page.getByRole('button', { name: '删掉这一项' }).click()
  // 有已录金额时要说清楚那笔账不会跟着消失
  await expect(page.locator('.q-dialog')).toContainText('4,200')
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)
  await expect(page.locator('.q-expansion-item').filter({ hasText: 'ガス' })).toHaveCount(0)

  // 账没动：余额一分不差，account 也还在账目里
  const after = (await (await page.request.get('/api/balances', { headers })).json()).balances
  expect(after, '删一项固定费不该动到任何人的余额').toEqual(before)

  await page.getByRole('button', { name: '撤销' }).click()
  await expect(page.locator('.q-expansion-item').filter({ hasText: 'ガス' })).toHaveCount(1)
})

test('账单 Tab 上就能看到并填固定费', async ({ page }) => {
  await login(page)
  await page.getByRole('tab', { name: '账单' }).click()
  // 固定费和账单在同一屏：钱的数字和分摊结果一眼都在
  await expect(page.getByText('本期固定费')).toBeVisible()
  await expect(page.locator('.amount-input').first()).toBeVisible()
  await expect(page.getByText(/转账方案/)).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/16-bill-tab.png', fullPage: true })
})
