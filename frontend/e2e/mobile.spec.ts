/**
 * 手机视口 E2E —— SPEC §7.4 的硬性验收。
 *
 * 跑之前要有后端在 127.0.0.1:8000 上跑着，并且已经 seed 过开发数据：
 *   cd backend && .venv/bin/python -m tools.seed_dev && ./run.sh
 */
import { expect, test } from '@playwright/test'

const USER = 'go'
const PASSWORD = 'dev12345'

async function login(page: import('@playwright/test').Page, who: string = USER) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(who)
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

/**
 * 设某个人的比例。比例是「点药丸 → 在弹层里选数字」，不是输入框 ——
 * 真机 iOS 上输入框会弹出数字键盘挡半屏，为一个只在 0/1 之间变的值不值当。
 */
async function setWeight(page: import('@playwright/test').Page, index: number, value: number) {
  await page.locator('.weight-pill').nth(index).click()
  await page.locator('.weight-pick .pick').filter({ hasText: String(value) }).first().click()
  // 等弹层真的关掉再往下走：它的遮罩会吃掉下一次点击，而报错跟「找不到元素」长得一样
  await expect(page.locator('.weight-pick')).toHaveCount(0)
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
  // 日常那屏只放天天会用的。家賃/電気/ガス/水道/ネット 一个月才碰一次，
  // 已经挪到账单页顺手填，不在这里占按钮。
  // 不写死个数（加个「外食」就得改测试没意义），钉的是真正的规矩：
  // 固定费一个都不许出现，而且总数一行放得下 —— 这一屏的价值就在于按钮少。
  await expect(page.getByRole('button', { name: '日用品' })).toBeVisible()
  for (const monthly of ['家賃', '電気', 'ガス', '水道', 'ネット']) {
    await expect(page.getByRole('button', { name: monthly })).toHaveCount(0)
  }
  expect(await page.locator('.cat').count(), '日常分类超过一行了').toBeLessThanOrEqual(4)

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

  const shares = page.locator('.member-row .share-col')
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

test('权重全填 0：把缺口报出来，而且存不了', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('12000')
  // 分类是必选的：不选的话后端拿不到分类默认规则，会悄悄掉回全员均分
  await page.getByRole('button', { name: '日用品' }).click()

  // 比例模式几乎永远自动配平 —— 调整额再怎么填都会从基数里扣回来。
  // 唯一的例外就是所有人权重都 0：这笔钱没人担，整笔悬空，必须当场说清缺多少
  const n = await page.locator('.weight-pill').count()
  for (let i = 0; i < n; i++) await setWeight(page, i, 0)
  // 比例那一列不许再有输入框：有的话手机上就会弹数字键盘
  await expect(page.locator('.weight-col input')).toHaveCount(0)

  await expect(page.locator('.diff-line')).toBeVisible()
  await expect(page.locator('.diff-line')).toContainText('12,000')
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await page.screenshot({ path: 'e2e/shots/08-all-zero.png' })

  await setWeight(page, 0, 1)             // 只要有一个人担，就自动配平
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

test('出账单：划一条线，之后记的账进下一张', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  await page.goto('/bill')
  await expect(page.getByText('当前账单（未出）')).toBeVisible()
  const draftTotal = (await (await page.request.get('/api/bill', { headers })).json()).total_expense
  expect(draftTotal).toBeGreaterThan(0)

  await page.getByRole('button', { name: '出账单' }).click()
  await page.getByRole('button', { name: 'OK' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)

  // 出完账草稿就空了，之后记的账进下一张
  const after = await (await page.request.get('/api/bill', { headers })).json()
  expect(after.total_expense, '出账之后草稿应当清空').toBe(0)
  const statements = await (await page.request.get('/api/statements', { headers })).json()
  expect(statements.length).toBeGreaterThan(0)
  const cut = await (await page.request.get(`/api/statements/${statements[0].id}/bill`, { headers })).json()
  expect(cut.total_expense, '那张单子上的金额应当还是出账时的').toBe(draftTotal)

  // **不锁定**：已出账的账目照样能改，钱不会算错，只是会被标出来
  const entries = await (await page.request.get(`/api/entries?statement_id=${statements[0].id}`, { headers })).json()
  const e = entries[0]
  const patched = await page.request.patch(`/api/entries/${e.id}?version=${e.version}`, {
    headers, data: { amount_jpy: e.amount_jpy + 1000 },
  })
  expect(patched.ok(), '已出账的账目应当仍然可改').toBe(true)
  const flagged = await (await page.request.get(`/api/statements/${statements[0].id}/bill`, { headers })).json()
  expect(flagged.edited_after_cut, '出账后被改过，账单必须自己说出来').not.toBeNull()

  await page.request.patch(`/api/entries/${e.id}?version=${patched.json ? (await patched.json()).version : e.version + 1}`, {
    headers, data: { amount_jpy: e.amount_jpy },
  })
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

test('完整闭环：出账单 → 点「已完成」→ 那个人归零', async ({ page }) => {
  await login(page)
  await page.goto('/bill')
  await expect(page.getByText(/转账方案/)).toBeVisible()

  // 卡片上是「转出方 → 转入方」加一行金额。转完钱归零的是转出方那个人。
  const firstCard = page.locator('.q-card').first()
  const pair = (await firstCard.locator('.text-caption').first().textContent())!.trim()
  const who = pair.split(/\s+/)[0]!
  const amount = Number((await firstCard.locator('.text-subtitle1').textContent())!.replace(/[^\d]/g, ''))
  expect(amount, '转账卡片上没读到金额，多半是选择器过期了').toBeGreaterThan(0)

  await firstCard.getByRole('button', { name: '已完成' }).click()
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

  // 先把当前草稿出掉，这样固定费就都回到「没录」的状态 —— 正是要验的
  await page.request.post('/api/statements', { headers })

  await page.goto('/bill')
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
  await expect(page.getByText('改完自动保存')).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/13-monthly-hint.png' })

})

test('账单页固定费：填一项存下去，账单跟着涨且留在这张账单的期里', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  await page.request.post('/api/statements', { headers })   // 清出一张空草稿
  await page.goto('/bill')
  await expect(page.getByText('本期固定费')).toBeVisible()
  // 填「電気」而不是第一行的「家賃」：家賃的分类规则是固定金额 45000/40000/35000，
  // 总额一改就和每人金额对不上，会被正确拦下 —— 那是另一条用例要验的事
  const denki = page.locator('.q-expansion-item').filter({ hasText: '電気' }).locator('.amount-input')
  await denki.fill('9100')
  await denki.blur()                                  // 离开输入框就存，没有保存按钮
  await expect(page.getByText('改完自动保存')).toBeVisible({ timeout: 10_000 })

  // 草稿账单的总额跟着涨 —— 这笔确实进了当前这张，没跑到别处
  const bill = await (await page.request.get('/api/bill', { headers })).json()
  expect(bill.total_expense).toBe(9100)

  for (const e of await (await page.request.get('/api/entries?unbilled_only=true', { headers })).json()) {
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

test('固定费不必等到出账单：账单 Tab 一点就到', async ({ page }) => {
  await login(page)
  // 记一笔那屏不再放固定费入口 —— 账单已经是 Tab，一点就到，再放一个是重复
  await expect(page.getByText('本期固定费')).toHaveCount(0)
  await expect(page.locator('.cat')).toHaveCount(3)

  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.getByText('本期固定费')).toBeVisible()
  await expect(page.locator('.amount-input').first()).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/14-monthly-standalone.png' })
})

test('记一笔：分摊一直摆在那儿，不用点开', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('3000')
  // 没有折叠这回事：每人分多少直接看得见
  await expect(page.locator('.member-row .share-col').first()).toBeVisible()
  const texts = await page.locator('.member-row .share-col').allTextContents()
  expect(texts.reduce((s, t) => s + Number(t.replace(/[^\d-]/g, '')), 0)).toBe(3000)
})

test('账单页在固定费下面也列出本期其他开销', async ({ page }) => {
  await login(page)
  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.getByText('本期其他')).toBeVisible()
  // 种子数据里有日用品和返现，都不是固定费，应当出现在这一块
  await expect(page.getByText('トイレットペーパー')).toBeVisible()
  // 固定费不该在这里重复出现
  const others = page.locator('.others')
  await expect(others.getByText('家賃')).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/17-bill-others.png', fullPage: true })
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

  // **自己准备前提**：前面的「出账单」用例会把种子数据全出账，这时 ガス 会退回未录状态。
  // 依赖别的用例留下的状态就是在赌执行顺序，迟早会红在无关的地方。
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const gas = cats.find((c: { name: string }) => c.name === 'ガス')
  const existing = await (await page.request.get('/api/entries?unbilled_only=true', { headers })).json()
  for (const e of existing.filter((x: { category_id: number }) => x.category_id === gas.id)) {
    await page.request.delete(`/api/entries/${e.id}`, { headers })
  }
  await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-21', amount_jpy: 4_200, payer_id: 1, category_id: gas.id, title: 'E2Eガス' },
  })

  const before = (await (await page.request.get('/api/balances', { headers })).json()).balances

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

test('点一条账目进去改：金额改得动，自定义分摊不会被打回默认', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  // 自备前提：记一笔带「调整」的账（3000，有人少担 600）
  await page.locator('input.amount').fill('3000')
  await page.getByRole('button', { name: '日用品' }).click()
  await page.getByPlaceholder('备注（选填）').fill('E2E改这笔')
  await page.locator('.adj-col .num-input').first().fill('-600')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.q-notification')).toContainText('已记下')

  // 从账目列表点进去
  await page.goto('/entries')
  await page.getByText('E2E改这笔').click()
  await expect(page.getByText('改这一笔')).toBeVisible()
  await expect(page.locator('input.amount')).toHaveValue('3,000')

  // **这条是要害**：分摊要从这笔自己的规则起步。
  // 从分类默认值起步的话，一打开就被悄悄改回 1:1:1，按下保存才发现钱变了。
  await expect(page.locator('.adj-col .num-input').first()).toHaveValue('-600')
  const shares = await page.locator('.member-row .share-col').allTextContents()
  expect(shares.map((s) => Number(s.replace(/[^\d-]/g, ''))).sort((a, b) => a - b))
    .toEqual([600, 1200, 1200])

  // 改金额存回去
  await page.locator('input.amount').fill('4500')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.q-notification')).toContainText('已记下')

  await page.goto('/entries')
  await expect(page.locator('.q-item').filter({ hasText: 'E2E改这笔' })).toContainText('4,500')

  // 分摊照旧按「少担 600」算：(4500+600)/3 = 1700，那个人 1100
  const rows = await (await page.request.get('/api/entries?limit=20', { headers })).json()
  const saved = rows.find((e: { title: string }) => e.title === 'E2E改这笔')
  expect(saved.amount_jpy).toBe(4500)
  expect(Object.values(saved.shares as Record<string, number>).sort((a, b) => a - b))
    .toEqual([1100, 1700, 1700])
})

test('账目里点固定费去固定费那一屏，点日常开销才进单笔编辑', async ({ page }) => {
  await login(page)

  // 固定费是一整屏一起看的东西 —— 从账目点开也得是那一屏，
  // 否则同一个 家賃 从账单点和从账目点会落到两套界面上
  await page.goto('/entries')
  await page.locator('.q-item').filter({ hasText: '家賃' }).first().click()
  await expect(page).toHaveURL(/\/monthly/)
  await expect(page.getByText('本期固定费')).toBeVisible()

  // 日常开销一笔就是一笔，还是进单笔编辑页
  await page.goto('/entries')
  await page.locator('.q-item').filter({ hasText: '鍋の材料' }).first().click()
  await expect(page).toHaveURL(/\/entry\/\d+/)
  await expect(page.getByText('改这一笔')).toBeVisible()
})

test('调整额输得进负数，比例点一下就能选', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('9000')
  await page.getByRole('button', { name: '日用品' }).click()

  // **一个键一个键地敲**：光打一个减号时数值还是 0，原来输入框会被重绘成空，
  // 负号当场消失，于是「a 少担 1000」根本输不进去 —— 而它正是这个字段的用途。
  // 注意不能用 fill()：那是整串一次性塞进去，绕过了出问题的那条路。
  const adj = page.locator('.adj-col .num-input').first()
  await adj.click()
  await page.keyboard.type('-')
  await expect(adj, '减号被吃掉了').toHaveValue('-')
  await page.keyboard.type('1500')
  await expect(adj).toHaveValue('-1,500')

  const shares = () =>
    page.locator('.member-row .share-col').allTextContents()
      .then((ts) => ts.map((t) => Number(t.replace(/[^\d-]/g, ''))))
  expect((await shares()).sort((a, b) => a - b)).toEqual([2000, 3500, 3500])

  // 比例点一下弹出 0/1/2/3
  await setWeight(page, 2, 0)
  expect((await shares()).sort((a, b) => a - b)).toEqual([0, 3750, 5250])
})

test('支出 / 收入 / 转账 三等分，选中的是实心色块且三种颜色各不相同', async ({ page }) => {
  await login(page)
  const segs = page.locator('.kind-toggle .q-btn')
  await expect(segs).toHaveCount(3)
  const widths = await segs.evaluateAll((els) =>
    els.map((e) => Math.round(e.getBoundingClientRect().width)),
  )
  expect(new Set(widths).size, '三段宽度应当一样').toBe(1)

  // 顶到屏幕边缘，不许有圆角
  const radii = await segs.evaluateAll((els) =>
    els.map((e) => getComputedStyle(e).borderRadius),
  )
  expect([...new Set(radii)], '顶部三段不该有圆角').toEqual(['0px'])

  // 量的是**选中那一段的背景色** —— 量金额的颜色没用，那是另一条线，
  // 把 toggle-color 写死也照样能绿。
  // 注意 Quasar 不给选中段加 q-btn--active，它是直接挂 bg-xxx 类，所以按文字定位
  const fills = new Set<string>()
  const amountInk = new Set<string>()
  for (const label of ['支出', '收入', '转账']) {
    const seg = page.getByRole('button', { name: label, exact: true })
    await seg.click()
    await page.waitForTimeout(200)
    fills.add(await seg.evaluate((el) => getComputedStyle(el).backgroundColor))
    amountInk.add(
      await page.locator('input.amount').evaluate((el) => getComputedStyle(el).color),
    )
  }
  expect(fills.size, '选中色块应当是三种颜色').toBe(3)
  expect(amountInk.size, '金额也该跟着换三种颜色').toBe(3)
})


test('自己排第一位：谁付的默认选自己，分摊里自己也在最上面', async ({ page }) => {
  // 换个人登录才测得出来 —— 用种子里的第一个人登录的话，
  // 「按 display_order 排」和「自己排第一」看起来是一样的，测了等于没测
  await login(page, 'kan')

  const chips = await page.locator('.pick').allTextContents()
  expect(chips[0], '谁付的第一个应当是自己').toBe('Kan')
  await expect(page.locator('.pick.on'), '默认应当选中自己').toHaveText('Kan')

  const rows = await page.locator('.member-row .name').allTextContents()
  expect(rows[0], '分摊第一行也应当是自己').toBe('Kan')

  // 一排按钮要够大，三个挨着时拇指不容易点错
  const h = await page.locator('.pick').first().evaluate((el) => el.getBoundingClientRect().height)
  expect(h, '谁付的按钮太小了').toBeGreaterThanOrEqual(40)
})

test('没选分类：写了备注就记成兜底分类，两样都没有才弹框问', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const cats = await (await page.request.get('/api/categories', { headers })).json()

  // ① 有备注、没点分类 → 直接存，落到兜底分类上（设置里指定，默认 その他）
  await page.locator('input.amount').fill('1234')
  await page.getByPlaceholder('备注（选填）').fill('E2E没选分类')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.q-notification')).toContainText('已记下')
  let rows = await (await page.request.get('/api/entries?limit=5', { headers })).json()
  const a = rows.find((e: { title: string }) => e.title === 'E2E没选分类')
  expect(a.category_id, '备注写了就该落到兜底分类，不能留空').not.toBeNull()
  expect(cats.find((c: { id: number }) => c.id === a.category_id).name).toBe('その他')

  // ② 备注和分类都没有 → 不许直接进库，弹框问清楚这笔是什么
  await page.goto('/')
  await page.locator('input.amount').fill('999')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.q-dialog')).toContainText('这笔是什么')
  // 顺带验一下 Quasar 自带的按钮也是中文的（默认是英文 CANCEL / OK）
  await expect(page.locator('.q-dialog')).toContainText('取消')
  await page.locator('.q-dialog input').fill('E2E弹框补的')
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)
  await expect(page.locator('.q-notification')).toContainText('已记下')

  rows = await (await page.request.get('/api/entries?limit=5', { headers })).json()
  const bEntry = rows.find((e: { title: string }) => e.title === 'E2E弹框补的')
  expect(bEntry.amount_jpy).toBe(999)
  expect(bEntry.category_id).toBe(a.category_id)
})
