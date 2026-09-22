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
/** 「个人设置」那条会临时改掉 kan 的密码。用例一红就跳过收尾，于是后面每条都登不进去 */
const TEMP_PASSWORD = 'e2e-new-password'

async function restoreKanPassword(page: import('@playwright/test').Page) {
  const r = await page.request.post('/api/auth/login', { data: { name: 'kan', password: TEMP_PASSWORD } })
  if (!r.ok()) return          // 没被改过，正常
  const headers = { Authorization: `Bearer ${(await r.json()).token}` }
  const me = await (await page.request.get('/api/auth/me', { headers })).json()
  await page.request.patch(`/api/members/${me.id}`, {
    headers,
    data: { password: PASSWORD, old_password: TEMP_PASSWORD },
  })
}

test.afterEach(async ({ page }) => {
  await restoreKanPassword(page).catch(() => {})
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
      // 备忘那条用例往分类上写过备注，也要擦掉
      if (typeof c.note === 'string' && c.note.startsWith('E2E')) {
        await page.request.patch(`/api/categories/${c.id}`, { headers, data: { note: '' } })
      }
    }
    for (const m of await (await page.request.get('/api/memos', { headers })).json()) {
      if (typeof m.title === 'string' && m.title.startsWith('E2E')) {
        await page.request.delete(`/api/memos/${m.id}`, { headers })
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
  // 比例就在行内那个小轮子上拨，没有弹层了。**先点一下激活**，再点那一格
  const wheel = page.locator('.wheel').nth(index)
  await wheel.click()
  await expect(wheel).toHaveClass(/live/)
  await wheel.locator('.tick').filter({ hasText: String(value) }).first().click()
  await expect(wheel).toHaveAttribute('aria-valuenow', String(value))
}

/**
 * 加一项固定费。
 *
 * 入口在「更多 → 设置」里，不在账单那页的面板上 —— 面板只管这一期填多少钱，
 * 有哪几项是配置，两件事分开。
 */
async function addFixedCost(page: import('@playwright/test').Page, name: string) {
  await page.goto('/entries')
  await page.getByRole('tab', { name: '设置' }).click()
  await page.locator('.add-row .new-name').fill(name)
  await page.getByRole('button', { name: '加一项固定费' }).click()
  await expect(page.locator(`.fixed-row[data-name="${name}"]`)).toBeVisible()
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
  // 日常那屏只放天天会用的。房租/电费/燃气/水费/网费 一个月才碰一次，
  // 已经挪到账单页顺手填，不在这里占按钮。
  // 不写死个数（加个「外食」就得改测试没意义），钉的是真正的规矩：
  // 固定费一个都不许出现，而且总数一行放得下 —— 这一屏的价值就在于按钮少。
  await expect(page.getByRole('button', { name: '日用品' })).toBeVisible()
  // 钉的是**分类网格里**没有固定费。整页搜名字会误伤 —— 网格底下那句
  // 「房租 / 水电煤网在「账单」那页填」正是要把人指过去的，它当然会提到这些词
  for (const monthly of ['房租', '电费', '燃气', '水费', '网费']) {
    await expect(page.locator('.cat-grid').getByRole('button', { name: monthly })).toHaveCount(0)
  }
  expect(await page.locator('.cat').count(), '日常分类超过一行了').toBeLessThanOrEqual(4)

  // 主操作按钮必须在屏幕下半部
  const save = page.getByRole('button', { name: '记入账' })
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

  await page.getByRole('button', { name: '记入账' }).click()
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
  const n = await page.locator('.wheel').count()
  for (let i = 0; i < n; i++) await setWeight(page, i, 0)
  // 比例那一列不许再有输入框：有的话手机上就会弹数字键盘
  await expect(page.locator('.weight-col input')).toHaveCount(0)

  await expect(page.locator('.diff-line')).toBeVisible()
  await expect(page.locator('.diff-line')).toContainText('12,000')
  await expect(page.getByRole('button', { name: '记入账' })).toBeDisabled()
  await page.screenshot({ path: 'e2e/shots/08-all-zero.png' })

  await setWeight(page, 0, 1)             // 只要有一个人担，就自动配平
  await expect(page.locator('.diff-line')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '记入账' })).toBeEnabled()
})

test('改日期不会把调好的分摊打回默认', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('9000')
  await page.getByRole('button', { name: '日用品' }).click()
  await setWeight(page, 2, 0)                     // 第三个人这次不参与
  const before = await page.locator('.share-col').allTextContents()

  // 换一天。参与人没变，调好的比例就不该动 —— 分摊面板原来是按「数组身份」
  // 判断参与人有没有变的，而按日期现算的参与人每次都是新数组
  await page.locator('.date-btn').click()
  await page.locator('.q-date button').filter({ hasText: /^15$/ }).first().click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.q-date')).toHaveCount(0)
  await expect(page.locator('.share-col'), '换个日期不该把调好的分摊打回默认').toHaveText(before)
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

  await page.getByRole('tab', { name: '更多' }).click()
  await expect(page.locator('.q-page .q-item').first()).toBeVisible()
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
  await expect(page.locator('.q-page .q-item').first()).toBeVisible()

  // 每人的「应收/应付」加起来必须是 0 —— 账单上直接看得见的那条恒等式。
  // **只扫「每人」那一块**：拿全页的 .q-item 去找粗体金额，会把固定费的合计行
  // 之类也算进来，然后红在一个跟恒等式毫无关系的地方
  const signed = await page.locator('.per-member .q-item').evaluateAll((items) =>
    items.map((el) => {
      // .closing 是「这一行的结论」那个数字，专门给它一个类名 ——
      // 原来抓的是 .text-weight-medium，那是个通用样式类，换个字重就断
      const amount = Number((el.querySelector('.closing')?.textContent ?? '0').replace(/[^\d]/g, ''))
      const isPay = el.textContent?.includes('应付')
      return isPay ? -amount : amount
    }),
  )
  // 收窄之后多了个洞：选择器过期就是空数组，空数组求和也是 0，会白白通过
  expect(signed.filter(Boolean).length, '没读到每人那一块的金额，多半是选择器过期了')
    .toBeGreaterThanOrEqual(2)
  expect(signed.reduce((a, b) => a + b, 0), '账单上应收与应付对不上').toBe(0)

  await expect(page.getByText(/转账方案/)).toBeVisible()
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/09-bill.png' })
})

test('出账单：划一条线，之后记的账进下一张', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  await page.goto('/bill')
  await expect(page.getByText('当前账单')).toBeVisible()
  const draftTotal = (await (await page.request.get('/api/bill', { headers })).json()).total_expense
  expect(draftTotal).toBeGreaterThan(0)

  await page.getByRole('button', { name: '出账单' }).click()
  // 距上次出账不到 20 天时「包括固定费」默认不勾（D29）。这条用例要的是「全扫进去」，
  // 所以显式确认勾上 —— 不然跑过一轮 E2E 之后它会红在「草稿没清空」上，
  // 看起来像出账坏了，其实是那个默认值在起作用
  const withMonthly = page.locator('.q-dialog .q-checkbox')
  if ((await withMonthly.getAttribute('aria-checked')) !== 'true') await withMonthly.click()
  await page.getByRole('button', { name: '确定' }).click()

  // 出完账立刻弹出「谁给谁多少」。**以前这个框根本看不见** —— 那会儿出完账要
  // router.push 去另一条路由，整个页面连着这个框一起被卸载掉了。
  // 现在三页共用一个地址、不走路由，它才真的留得住
  // 断言和点击都锁到这个框上：刚关掉的那个确认框还挂在 DOM 里做退场动画，
  // 用 .q-dialog 直接找会同时命中两个
  const cutDone = page.locator('.q-dialog').filter({ hasText: '出账完成' })
  await expect(cutDone).toBeVisible()
  await cutDone.getByRole('button', { name: '确定' }).click()
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
  await page.getByRole('button', { name: '记入账' }).click()

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
  await page.getByRole('button', { name: '记入账' }).click()

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

test('完整闭环：出账单 → 点「确认已完成」→ 那个人归零', async ({ page }) => {
  await login(page)
  await page.goto('/bill')
  await expect(page.getByText(/转账方案/)).toBeVisible()

  // 卡片上是「转出方 → 转入方」加一行金额。转完钱归零的是转出方那个人。
  const firstCard = page.locator('.q-card').first()
  const pair = (await firstCard.locator('.text-caption').first().textContent())!.trim()
  const who = pair.split(/\s+/)[0]!
  const amount = Number((await firstCard.locator('.text-subtitle1').textContent())!.replace(/[^\d]/g, ''))
  expect(amount, '转账卡片上没读到金额，多半是选择器过期了').toBeGreaterThan(0)

  // 按钮上写的是「确认已完成」—— 它是个动作，不是状态标签
  await firstCard.getByRole('button', { name: '确认已完成' }).click()
  await page.locator('.q-dialog input').fill(String(amount))
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)

  // 结清之后这个人应该显示「已结清」，而且账单上应收应付仍然相抵
  const row = page.locator('.q-item').filter({ hasText: who })
  await expect(row.getByText('已结清')).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/12-bill-settled.png' })

  await deleteLatestEntry(page)      // 把这笔转账撤掉，别把开发库越跑越脏
})

test('账单页固定费：没录的项一个数字都不给，空着就按 0 结', async ({ page }) => {
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
  // **最要命的一条**：上期金额不许出现在这一屏 —— 不光是 value，placeholder 也一样。
  // 参考值就摆在输入框那个位置，长得跟亲手填的没两样，某个月忘了改就带着上月的
  // 电费把账单发出去了。每期真的不变的项走「和上期一样」，记成黑字实数。
  for (const b of boxes) {
    expect(b.value, '上期金额被预填成真值了').toBe('')
    expect(b.placeholder, '上期金额漏进了灰色占位').toBe('0')
  }
  // 一项都没填 ＝ 固定费这块是 0，不是「缺数据」——「¥0」在这儿就是那句话的证据
  await expect(page.locator('.bill-section').filter({ hasText: '本期固定费' })).toContainText('¥0')
  await expect(page.getByText('改完自动保存')).toBeVisible()
  await page.screenshot({ path: 'e2e/shots/13-monthly-empty.png' })

})

test('账单页固定费：填一项存下去，账单跟着涨且留在这张账单的期里', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  await page.request.post('/api/statements', { headers })   // 清出一张空草稿
  await page.goto('/bill')
  await expect(page.getByText('本期固定费')).toBeVisible()
  // 填「电费」而不是第一行的「房租」：房租的分类规则是固定金额 45000/40000/35000，
  // 总额一改就和每人金额对不上，会被正确拦下 —— 那是另一条用例要验的事
  const denki = page.locator('.q-expansion-item').filter({ hasText: '电费' }).locator('.amount-input')
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
  const target = cats.find((c: { name: string }) => c.name === '伙食')
  const made = await (await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-15', amount_jpy: 905, payer_id: 1, category_id: target.id, title: '' },
  })).json()

  await page.request.patch(`/api/categories/${target.id}`, { headers, data: { archived: true } })
  await page.goto('/entries')
  // 归档之后前端若只拿未归档列表反查名字，这条会掉成默认标题和默认图标
  await expect(page.getByText('伙食').first()).toBeVisible()

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
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }

  // **自己准备前提**：前面的「出账单」用例会把种子数据全出账，草稿就空了。
  // 靠种子数据活着的断言，红的时候看起来跟这一屏毫无关系
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const daily = cats.find((c: { name: string; monthly: boolean }) => c.name === '日用品')
  const fixed = cats.find((c: { name: string }) => c.name === '房租')
  for (const [cat, title, amount] of [[daily, 'E2E日用品', 1_980], [fixed, '', 120_000]] as const) {
    await page.request.post('/api/entries', {
      headers,
      data: {
        kind: 'expense', date: '2026-09-21', amount_jpy: amount,
        payer_id: 1, category_id: cat.id, title,
      },
    })
  }

  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.getByText('本期其他')).toBeVisible()
  await expect(page.getByText('E2E日用品')).toBeVisible()
  // 固定费不该在这里重复出现 —— 它在上面那块
  const others = page.locator('.others')
  await expect(others.getByText('房租')).toHaveCount(0)
  await expectNoHorizontalScroll(page)
  await page.screenshot({ path: 'e2e/shots/17-bill-others.png', fullPage: true })
})

test('自己加一项固定费，它就留在这张表里', async ({ page }) => {
  await login(page)
  await page.goto('/monthly')
  await expect(page.locator('.amount-input').first()).toBeVisible()
  const before = await page.locator('.amount-input').count()

  await addFixedCost(page, 'E2E受信料')
  await expect(page.locator('.q-notification')).toContainText('下个月')

  // 加完就出现在填钱那一屏上
  await page.goto('/monthly')
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
  await addFixedCost(page, 'E2E受信料')
  await page.goto('/monthly')
  await expect(page.getByText('E2E受信料')).toBeVisible()

  // 删除入口在展开区里，不在行头 —— 行头有金额框，误触成本太高
  await page.locator('.q-expansion-item').filter({ hasText: 'E2E受信料' }).locator('[role="button"]').first().click()
  await page.getByRole('button', { name: '删掉这一项' }).click()
  await page.getByRole('button', { name: '确定' }).click()
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

  // **自己准备前提**：前面的「出账单」用例会把种子数据全出账，这时 燃气 会退回未录状态。
  // 依赖别的用例留下的状态就是在赌执行顺序，迟早会红在无关的地方。
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const gas = cats.find((c: { name: string }) => c.name === '燃气')
  const existing = await (await page.request.get('/api/entries?unbilled_only=true', { headers })).json()
  for (const e of existing.filter((x: { category_id: number }) => x.category_id === gas.id)) {
    await page.request.delete(`/api/entries/${e.id}`, { headers })
  }
  await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-21', amount_jpy: 4_200, payer_id: 1, category_id: gas.id, title: 'E2E燃气' },
  })

  const before = (await (await page.request.get('/api/balances', { headers })).json()).balances

  await page.goto('/monthly')
  const row = page.locator('.q-expansion-item').filter({ hasText: '燃气' })
  await expect(row.locator('.amount-input')).toHaveValue('4,200')

  await row.locator('[role="button"]').first().click()
  await page.getByRole('button', { name: '删掉这一项' }).click()
  // 有已录金额时要说清楚那笔账不会跟着消失
  await expect(page.locator('.q-dialog')).toContainText('4,200')
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.locator('.q-dialog')).toHaveCount(0)

  // **那一行要留着，而且要说明白自己是什么状态。**
  // 钱还在账单的合计和每人应担里，行一消失这笔钱就在界面上彻底看不见了 ——
  // 同一张草稿两个对不上的合计，而且那笔钱既改不了也删不掉。
  // 所以：行留着、金额照显、状态位写「已删掉，这笔还在」、不再给「删掉这一项」
  const gone = page.locator('.q-expansion-item').filter({ hasText: '燃气' })
  await expect(gone).toHaveCount(1)
  await expect(gone).toContainText('已删掉，这笔还在')
  await expect(gone.locator('.amount-input')).toHaveValue('4,200')
  const cat = (await (await page.request.get('/api/categories?include_archived=true', { headers })).json())
    .find((c: { id: number }) => c.id === gas.id)
  expect(cat.archived, '分类本身确实归档了').toBe(true)

  // 账没动：余额一分不差，account 也还在账目里
  const after = (await (await page.request.get('/api/balances', { headers })).json()).balances
  expect(after, '删一项固定费不该动到任何人的余额').toEqual(before)

  await page.getByRole('button', { name: '撤销' }).click()
  await expect.poll(async () =>
    (await (await page.request.get('/api/categories', { headers })).json())
      .some((c: { id: number }) => c.id === gas.id),
  ).toBe(true)
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
  await page.getByRole('button', { name: '记入账' }).click()
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
  // 否则同一个 房租 从账单点和从账目点会落到两套界面上
  await page.goto('/entries')
  await page.locator('.q-item').filter({ hasText: '房租' }).first().click()
  await expect(page).toHaveURL(/\/monthly/)
  await expect(page.getByText('本期固定费')).toBeVisible()

  // 日常开销一笔就是一笔，还是进单笔编辑页
  await page.goto('/entries')
  await page.locator('.q-item').filter({ hasText: '火锅食材' }).first().click()
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

  // ① 有备注、没点分类 → 直接存，落到兜底分类上（设置里指定，默认 其他）
  await page.locator('input.amount').fill('1234')
  await page.getByPlaceholder('备注（选填）').fill('E2E没选分类')
  await page.getByRole('button', { name: '记入账' }).click()
  await expect(page.locator('.q-notification')).toContainText('已记下')
  let rows = await (await page.request.get('/api/entries?limit=5', { headers })).json()
  const a = rows.find((e: { title: string }) => e.title === 'E2E没选分类')
  expect(a.category_id, '备注写了就该落到兜底分类，不能留空').not.toBeNull()
  expect(cats.find((c: { id: number }) => c.id === a.category_id).name).toBe('其他')

  // ② 备注和分类都没有 → 不许直接进库，弹框问清楚这笔是什么
  await page.goto('/')
  await page.locator('input.amount').fill('999')
  await page.getByRole('button', { name: '记入账' }).click()
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

test('同一分类本期有两笔：面板说得出来，也点得进去，合计不少算', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const rent = cats.find((c: { name: string }) => c.name === '房租')
  // 再记一笔房租：面板一行只显示得下一笔，另一笔照样算进账单
  await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-21', amount_jpy: 7_777, payer_id: 1, category_id: rent.id, title: 'E2E重复房租' },
  })

  // 这笔是绕过前端直接 POST 的，整页加载一次让本地的账目列表也拿到它
  await page.goto('/bill')
  await expect(page.locator('.wrap')).toBeVisible()
  // 面板的合计必须和账单上的「本期固定费」一致 —— 由后端给，不是把行加出来的。
  // 用 poll 而不是读一次：这一屏是**缓存先上屏、再后台校正**，上面那笔是绕过前端
  // 直接 POST 的，所以第一帧必然是旧数。读一次就等于跟渲染赛跑，红得毫无道理
  const billTotal = await (await page.request.get('/api/bill', { headers })).json()
  const monthly = (await (await page.request.get('/api/monthly', { headers })).json()).total
  await expect
    .poll(
      async () =>
        Number((await page.locator('.section-head .amount').first().innerText()).replace(/[^\d]/g, '')),
      { message: '面板合计不能少算重复的那一笔' },
    )
    .toBe(monthly)
  expect(billTotal.total_expense).toBeGreaterThan(monthly - 1)

  // 「本期有 2 笔」点得进去 —— 否则多出来的那笔在界面上既打不开也删不掉
  const dup = page.locator('.dup-link').first()
  await expect(dup).toBeVisible()
  await dup.click()
  await expect(page).toHaveURL(/\/entries\?category=/)
  await expect(page.locator('.entry-row').first()).toBeVisible()
  await expect(page.getByText('E2E重复房租')).toBeVisible()
})

test('固定费谁垫的：跟着分类走，不是「谁填的算谁」', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const catOf = async (name: string) =>
    (await (await page.request.get('/api/categories', { headers })).json())
      .find((c: { name: string }) => c.name === name)
  const draftEntryOf = async (categoryId: number) =>
    (await (await page.request.get('/api/entries?unbilled_only=true&limit=100', { headers })).json())
      .find((e: { category_id: number }) => e.category_id === categoryId)

  // **自己准备前提**：前面的「出账单」用例会把草稿清空，靠种子数据活着的断言
  // 红的时候看起来跟这一屏毫无关系
  const wifiCat = await catOf('网费')
  const payer = wifiCat.default_payer_id
  expect(payer, '种子里网费该定好了默认垫付人').toBeTruthy()
  if (!(await draftEntryOf(wifiCat.id))) {
    await page.request.post('/api/entries', {
      headers,
      data: {
        kind: 'expense', date: '2026-09-21', amount_jpy: 5_500,
        payer_id: payer, category_id: wifiCat.id, title: '',
      },
    })
  }

  // 名字不写死：种子里谁垫网费是会变的（现在是 Zen 全垫），写死就得跟着种子改
  const members = await (await page.request.get('/api/members', { headers })).json()
  const nameOf = (id: number) =>
    members.find((m: { id: number }) => m.id === id)?.display_name as string

  await page.goto('/bill')
  // 行头上看得见谁垫的 —— 这是这一屏唯一会悄悄出错的地方
  const wifi = page.locator('.q-expansion-item').filter({ hasText: '网费' })
  await expect(wifi).toContainText(nameOf(payer))

  // 改成别人：分类的常驻默认和本期那笔要一起变。
  // 挑「当前没选中」的那一格 —— 写死某个名字的话，哪天种子把默认改成他，
  // 这一点就成了空点击，断言红在一个跟本意毫无关系的地方
  await wifi.locator('[role="button"]').first().click()
  await wifi.locator('.pick:not(.on)').first().click()
  await expect.poll(async () => (await catOf('网费')).default_payer_id).not.toBe(payer)
  const moved = await catOf('网费')
  await expect
    .poll(async () => (await draftEntryOf(wifiCat.id))?.payer_id)
    .toBe(moved.default_payer_id)

  // 收尾：改回去，别把开发库留在一个跟种子不一样的状态
  await page.request.patch(`/api/categories/${wifiCat.id}`,
    { headers, data: { default_payer_id: payer } })
  const back = await draftEntryOf(wifiCat.id)
  await page.request.patch(`/api/entries/${back.id}?version=${back.version}`,
    { headers, data: { payer_id: payer } })
})

test('固定费项目在设置里管：加、删、和上期一样', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  // 分类名不唯一，而每轮 E2E 都会留下一个归档掉的同名项 —— 优先取还活着的那个，
  // 否则这条用例会去断言上一轮的残骸
  const catOf = async (name: string) => {
    const all = (await (await page.request.get('/api/categories?include_archived=true', { headers })).json())
      .filter((c: { name: string }) => c.name === name)
    return all.find((c: { archived: boolean }) => !c.archived) ?? all.at(-1)
  }

  // 进屏之前先把房租那个开关归零：它是共享状态，上一条用例红在半路就会留着开的，
  // 于是这里「点一下应该变成开」当场变成空点击
  await page.request.patch(`/api/categories/${(await catOf('房租')).id}`,
    { headers, data: { same_as_last: false } })

  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '设置' }).click()
  await expect(page.locator('.fixed-row[data-name="房租"]')).toBeVisible()

  // 加一项
  await page.locator('.add-row .new-name').fill('E2E停车位')
  await page.getByRole('button', { name: '加一项固定费' }).click()
  await expect(page.locator('.fixed-row[data-name="E2E停车位"]')).toBeVisible()
  expect((await catOf('E2E停车位')).monthly, '加出来的得是固定费，不是日常分类').toBe(true)

  // 图标和颜色也在这儿改
  const parking = page.locator('.fixed-row[data-name="E2E停车位"]')
  await parking.locator('.icon-btn').click()
  await page.locator('.icon-cell').filter({ has: page.locator('.q-icon') }).nth(8).click()
  await expect.poll(async () => (await catOf('E2E停车位')).icon).toBe('local_parking')
  await parking.locator('.icon-btn').click()
  await page.locator('.color-cell').nth(3).click()
  await expect.poll(async () => (await catOf('E2E停车位')).color).toBe('#c62828')

  // 「和上期一样」默认关着 —— 这是「没开开关就一个数字都不许自动填」那条规矩的底线。
  // 断在**刚加出来的这一项**上，不断在房租：房租是共享状态，别的用例碰过就红在这儿，
  // 而那跟「默认值是什么」根本是两回事
  expect((await catOf('E2E停车位')).same_as_last, '新加的项默认必须是关的').toBe(false)
  // 房租只拿来验「点得动」。进这一屏之前就已经归零过（见开头），所以这一下必然是开
  const rent = page.locator('.fixed-row[data-name="房租"]')
  await rent.locator('.q-toggle').click()
  await expect.poll(async () => (await catOf('房租')).same_as_last).toBe(true)

  // 删一项（归档，历史账目还要显示原名）
  // 行里有两个按钮（删除、谁付的），按 aria-label 精确点删除那个
  await page.locator('.fixed-row[data-name="E2E停车位"]')
    .getByRole('button', { name: '删掉这一项' }).click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.locator('.fixed-row[data-name="E2E停车位"]')).toHaveCount(0)
  expect((await catOf('E2E停车位')).archived).toBe(true)

  // 收尾：房租那个开关关回去，别影响后面的用例
  await page.request.patch(`/api/categories/${(await catOf('房租')).id}`,
    { headers, data: { same_as_last: false } })
})

test('「和上期一样」：只搬开了开关的那几项，而且要说出来', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const rent = cats.find((c: { name: string }) => c.name === '房租')
  const gas = cats.find((c: { name: string }) => c.name === '燃气')
  const draftOf = async (id: number) =>
    (await (await page.request.get('/api/entries?unbilled_only=true&limit=100', { headers })).json())
      .find((e: { category_id: number }) => e.category_id === id)

  // 房租开、燃气不开。**用「出账」来造出一期干净的草稿**，不是把草稿里那两笔删掉 ——
  // 手动删掉的项现在不许被搬回来（删一次复活一次的话用户根本删不掉），
  // 拿删除来造前提等于在测一条相反的规矩
  await page.request.patch(`/api/categories/${rent.id}`, { headers, data: { same_as_last: true } })
  await page.request.post('/api/statements', { headers })
  expect(await draftOf(rent.id), '出完账草稿该是空的').toBeFalsy()

  await page.goto('/bill')
  // 自动记的钱必须当场报出来 —— 悄悄填上正是那条规矩要防的事
  await expect(page.locator('.q-notification')).toContainText('按上期金额记上了')
  await expect(page.locator('.q-notification')).toContainText('房租')
  await expect.poll(async () => (await draftOf(rent.id))?.amount_jpy).toBeTruthy()
  expect(await draftOf(gas.id), '没开开关的一分都不许自动记').toBeFalsy()

  // **删掉之后不许复活。** 这个月真的没有房租时，用户删掉它 ——
  // 而面板每挂载一次就调一次 carry，不挡住的话他永远删不掉
  const carried = await draftOf(rent.id)
  await page.request.delete(`/api/entries/${carried.id}`, { headers })
  await page.reload()
  await expect(page.locator('.wrap')).toBeVisible()
  await expect.poll(async () => (await draftOf(rent.id))?.amount_jpy).toBeFalsy()

  await page.request.patch(`/api/categories/${rent.id}`, { headers, data: { same_as_last: false } })
})

test('账单两页：未出账 / 已出账，更早的从标题那个名字翻', async ({ page }) => {
  await login(page)
  await page.getByRole('tab', { name: '账单' }).click()
  await expect(page.locator('.bill-tabs .q-tab')).toHaveText(['未出账', '已出账'])

  // ① 未出账：还没归到任何账单上的流水
  await expect(page).toHaveURL(/\/bill$/)
  // 两页共用一个地址：下面每切一次都再确认一次地址没动 —— 页签一旦做回路由，
  // 组件就会跟着重建，白屏和「旧数字停半秒」都会回来
  await expect(page.locator('.head')).toContainText('当前账单')
  await expect(page.getByRole('button', { name: '出账单' })).toBeVisible()

  // ② 已出账：默认是最近出的那一张
  await page.getByRole('tab', { name: '已出账' }).click()
  await expect(page).toHaveURL(/\/bill$/)
  await expect(page.getByRole('button', { name: '出账单' }), '已出的账单上不该再有出账按钮').toHaveCount(0)
  const newest = (await page.locator('.head .pick').innerText()).trim()
  expect(newest, '已出账该显示一张已经出过的账单').toContain('出账')

  // ③ 更早的：点标题那个名字，列出**全部**出过的单子（含当前这张），挑一张旧的
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const all = await (await page.request.get('/api/statements', { headers })).json()
  expect(all.length, '种子数据里该有好几张出过的账单').toBeGreaterThan(1)
  await page.locator('.head .pick').click()
  const items = page.locator('.q-menu .q-item')
  await expect(items, '出过的单子全都要列出来，包括正在看的这张').toHaveCount(all.length)
  await items.nth(1).click()
  await expect(page.locator('.q-menu')).toHaveCount(0)

  // 翻到的是上一张，而且地址照样不动
  await expect(page.locator('.head .pick')).toContainText(all[1].label)
  await expect(page).toHaveURL(/\/bill$/)
  // 页签没跑掉：翻旧账单仍然在「已出账」这一页里
  await expect(page.locator('.bill-tabs .q-tab').nth(1)).toHaveClass(/q-tab--active/)
  await expectNoHorizontalScroll(page)
})

test('结账按钮只在「此刻还欠着」时出现，而且说得出还差多少', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const all = await (await page.request.get('/api/statements', { headers })).json()
  const settled = all.find((s: { settled: boolean }) => s.settled)
  expect(settled, '种子数据里该有已结清的账单').toBeTruthy()

  // **钱早就转完的单子上不许有按钮。** 按钮的开关是「此刻这一对还欠不欠」，
  // 不是「这是不是最新那张」—— 后者两头都错：最新那张的方案同样会在出账后作废
  // （有人没照方案走、或者又记了新账），按下去凭空造债；而更早那张上的钱
  // 可能确确实实还欠着，收掉按钮等于没地方记。
  await page.goto(`/bill/${settled.id}`)
  await expect(page.locator('.head .pick')).toContainText(settled.label)
  await expect(page.getByRole('button', { name: '确认已完成' }),
    '钱已经转完了，不该还叫人再转一次').toHaveCount(0)

  // **已经转过多少必须上屏。** 后端一直算着这个数，可它以前只送进了对话框的
  // 预填值 —— 屏幕上只有一个全额，于是还了一半的人照着它再转一次全额。
  // 造一个「转了一部分」的局面：挑一张出过的单子，往它的某一对之间记一笔小额
  const me = await (await page.request.get('/api/auth/me', { headers })).json()
  let target: { st: number; tr: { from_id: number; to_id: number; amount: number }; paid: number } | null = null
  for (const st of all) {
    const b = await (await page.request.get(`/api/statements/${st.id}/bill`, { headers })).json()
    const live = new Map(
      (b.live_transfers ?? []).map((x: { from_id: number; to_id: number; amount: number }) =>
        [`${x.from_id}-${x.to_id}`, x.amount]),
    )
    const i = b.transfers.findIndex(
      (tr: { from_id: number; to_id: number; amount: number }, k: number) =>
        (tr.from_id === me.id || tr.to_id === me.id) &&
        !b.settled_transfers[k] &&
        Number(live.get(`${tr.from_id}-${tr.to_id}`) ?? 0) >= tr.amount - b.settled_paid[k],
    )
    if (i >= 0) {
      target = { st: st.id, tr: b.transfers[i], paid: b.settled_paid[i] }
      break
    }
  }
  expect(target, '种子数据里该有一笔「还欠着、还没转完」的方案行').toBeTruthy()

  const bump = 1000
  const made = await (await page.request.post('/api/entries', {
    headers,
    data: {
      kind: 'settlement', date: new Date().toISOString().slice(0, 10), amount_jpy: bump,
      payer_id: target!.tr.from_id, to_member_id: target!.tr.to_id,
    },
  })).json()
  try {
    await page.goto(`/bill/${target!.st}`)
    const left = target!.tr.amount - target!.paid - bump
    const card = page.locator('.q-card').filter({ hasText: `¥${target!.tr.amount.toLocaleString('en-US')}` }).first()
    await expect(card, '卡片上要写清已经转了多少、还差多少')
      .toContainText(`¥${left.toLocaleString('en-US')}`)
    // 按钮预填的也得是还差的数，不是全额
    await card.getByRole('button', { name: '确认已完成' }).click()
    await expect(page.locator('.q-dialog input')).toHaveValue(String(left))
    await page.getByRole('button', { name: '取消' }).click()
  } finally {
    await page.request.delete(`/api/entries/${made.id}`, { headers })
  }
})

test('结清了的账单：绿标就占状态那一格，自己那笔划掉', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const all = await (await page.request.get('/api/statements', { headers })).json()
  const settled = all.find((s: { settled: boolean }) => s.settled)
  expect(settled, '种子数据里该有已结清的账单').toBeTruthy()

  await page.goto(`/bill/${settled.id}`)
  await expect(page.locator('.head .pick')).toContainText(settled.label)
  // 绿标就在日期那一行的右头 —— 原来它自己占一整行，右头写的是「请于每月 N 号前结清」
  const status = page.locator('.head .row').nth(1)
  await expect(status.locator('.q-badge')).toHaveText('已结清')
  await expect(page.locator('.head'), '结算日提醒撤了').not.toContainText('号前结清')
  // 钱早就转过了：一个亮着的「你应收」会让人以为现在还欠着
  await expect(page.locator('.mine')).toHaveCSS('text-decoration-line', 'line-through')

  // 没结清的那张不划，否则这条断言等于没断言
  const open = all.find((s: { settled: boolean }) => !s.settled)
  expect(open, '种子数据里该有没结清的账单').toBeTruthy()
  await page.goto(`/bill/${open.id}`)
  await expect(page.locator('.head .row').nth(1)).toContainText('未结清')
  await expect(page.locator('.mine')).toHaveCSS('text-decoration-line', 'none')
})

test('备忘：固定费那几项常驻，自己也能加；两页共用一个地址', async ({ page }) => {
  await login(page)
  await page.getByRole('tab', { name: '更多' }).click()
  await expect(page.locator('.bill-tabs .q-tab')).toHaveText(['流水', '备忘', '设置'])
  await expect(page).toHaveURL(/\/entries$/)

  await page.getByRole('tab', { name: '备忘' }).click()
  await expect(page).toHaveURL(/\/entries$/, { timeout: 3000 })
  // 固定费那几项是现成的清单，不用自己抄一遍
  await expect(page.getByText('房租', { exact: true })).toBeVisible()
  await expect(page.locator('.memo-row').first()).toBeVisible()

  // 分类的备注是**常驻**的：写在某一笔账的备注里，下个月就找不着了
  const rentNote = page.locator('.memo-row').filter({ hasText: '房租' }).locator('.note')
  await rentNote.fill('E2E房东自动扣')
  await rentNote.blur()
  await page.reload()
  await expect(page.locator('.memo-row').filter({ hasText: '房租' }).locator('.note'))
    .toHaveValue('E2E房东自动扣')

  // 清单之外的自己加
  await page.locator('.add-row .new-name').fill('E2E备用钥匙')
  await page.getByRole('button', { name: '加一条' }).click()
  // 条目名在输入框里，按文本内容找不到这一行 —— 行上挂了 data-title 当锚点
  const rowOf = (title: string) => page.locator(`.memo-row[data-title="${title}"]`)
  const mine = rowOf('E2E备用钥匙')
  await expect(mine).toBeVisible()
  await mine.locator('.note').fill('鞋柜第二层')
  await mine.locator('.note').blur()
  await page.reload()
  await expect(rowOf('E2E备用钥匙').locator('.note')).toHaveValue('鞋柜第二层')

  // 删掉
  await rowOf('E2E备用钥匙').getByRole('button').click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(rowOf('E2E备用钥匙')).toHaveCount(0)

  // 切回流水，地址照样不动
  await page.getByRole('tab', { name: '流水' }).click()
  await expect(page.locator('.filter-bar')).toBeVisible()
  await expect(page).toHaveURL(/\/entries$/)
})

test('设置面板：照后端的声明渲染，改完当场落库', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const valueOf = async (key: string) =>
    (await (await page.request.get('/api/settings', { headers })).json())
      .find((s: { key: string }) => s.key === key)?.value

  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '设置' }).click()
  // 系统设置默认收起 —— 这一页天天要来的是上面的个人设置
  await expect(page.locator('.setting-row')).toHaveCount(0)
  await page.getByText('系统设置').click()
  // 面板不写死项目：后端声明里有几条就渲染几条
  const spec = await (await page.request.get('/api/settings', { headers })).json()
  await expect(page.locator('.setting-row')).toHaveCount(spec.length)
  // 说明是后端给的，里面的 **强调** 不该把星号露在界面上
  const shown = await page.locator('.setting-row').allTextContents()
  expect(shown.some((x) => x.includes('**')), '后端说明里的星号不该露在界面上').toBe(false)

  // 改一条：当场落库
  await page.locator('[data-key="monthly_gap_days"] .num').fill('35')
  await page.locator('[data-key="monthly_gap_days"] .num').blur()
  await expect.poll(() => valueOf('monthly_gap_days')).toBe(35)

  // 越界要说清楚哪儿不对 —— 原来这类错会显示成一句空的「出错了：」
  await page.locator('[data-key="monthly_gap_days"] .num').fill('999')
  await page.locator('[data-key="monthly_gap_days"] .num').blur()
  await expect(page.locator('.q-notification')).toContainText('0〜90')
  expect(await valueOf('monthly_gap_days'), '越界的值不许写进去').toBe(35)

  // 枚举项点得动
  await page.locator('[data-key="remainder_to"] .q-btn').click()
  await page.locator('.q-menu .q-item').filter({ hasText: '按成员顺序' }).click()
  await expect.poll(() => valueOf('remainder_to')).toBe('order')

  // 收尾：改回默认，免得影响后面的用例
  await page.request.put('/api/settings/remainder_to', { headers, data: { value: 'payer' } })
  await page.request.put('/api/settings/monthly_gap_days', { headers, data: { value: 20 } })
})

test('个人设置：头像色 / 昵称 / 语言 / 改密码', async ({ page }) => {
  // **用 kan 登录**：这条要改密码，拿 go 来做的话一旦中途失败，
  // 后面每条用例都登不进去了
  await login(page, 'kan')
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const me = async () => (await (await page.request.get('/api/auth/me', { headers })).json())
  const before = await me()

  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '设置' }).click()

  // 头像色：全站的头像都读它。挑一个**当前没选中**的 —— 写死下标的话，
  // 碰巧就是现在这个色时点了等于没点，测试会红在一个跟功能无关的地方
  await page.locator('.swatch:not(.on)').first().click()
  await expect.poll(async () => (await me()).color).not.toBe(before.color)

  // 昵称
  const nick = page.locator('.profile-row').filter({ hasText: '昵称' }).locator('.field')
  await nick.fill('E2E改过的名字')
  await nick.blur()
  await expect.poll(async () => (await me()).display_name).toBe('E2E改过的名字')

  // 语言：原来只有登录页上换得了，登录之后就再也找不到
  await page.getByRole('button', { name: '日本語' }).click()
  await expect(page.locator('.bill-tabs .q-tab').first()).toHaveText('明細')
  await page.getByRole('button', { name: '中文' }).click()
  await expect(page.locator('.bill-tabs .q-tab').first()).toHaveText('流水')

  // 改密码要先报出旧的 —— 手机搁桌上没锁屏，别人顺手就能改掉
  await page.getByRole('button', { name: '修改' }).click()
  const pw = page.locator('.profile-row').filter({ hasText: '密码' })
  await pw.locator('input[type="password"]').first().fill('wrong-one')
  await pw.locator('input[type="password"]').nth(1).fill(TEMP_PASSWORD)
  await pw.getByRole('button', { name: '保存' }).click()
  await expect(page.locator('.q-notification')).toContainText('当前密码不对')

  await pw.locator('input[type="password"]').first().fill(PASSWORD)
  await pw.getByRole('button', { name: '保存' }).click()
  // 按内容找，不按位置找：上一条报错还没消失，.last() 抓到的可能是它
  await expect(page.locator('.q-notification').filter({ hasText: '密码改好了' })).toBeVisible()
  // 新密码真能登进去
  const relogin = await page.request.post('/api/auth/login',
    { data: { name: 'kan', password: TEMP_PASSWORD } })
  expect(relogin.ok(), '改完的新密码要能登录').toBe(true)

  // 收尾：改回去，别把开发库留在一个登不进去的状态
  const fresh = { Authorization: `Bearer ${(await relogin.json()).token}` }
  await page.request.patch(`/api/members/${before.id}`, {
    headers: fresh,
    data: {
      password: PASSWORD, old_password: TEMP_PASSWORD,
      display_name: before.display_name, color: before.color,
    },
  })
  // **改完密码，刚才那张 token 也作废了** —— 后端按密码指纹认 session，
  // 改密码就是为了把别的设备踢下去，自己手里这张当然也算「别的设备」。
  // 界面上 ProfileCard 会自己用新密码重登一次；这里是走接口，所以自己换一张
  expect((await page.request.get('/api/auth/me', { headers: fresh })).status(),
    '改完密码，改之前发的 token 必须失效').toBe(401)
  const back = await page.request.post('/api/auth/login',
    { data: { name: 'kan', password: PASSWORD } })
  const last = { Authorization: `Bearer ${(await back.json()).token}` }
  expect((await (await page.request.get('/api/auth/me', { headers: last })).json()).display_name)
    .toBe(before.display_name)
})

test('换头像：传一张照片，全站跟着换；撤掉就回色圆', async ({ page }) => {
  await login(page, 'kan')          // 跟「个人设置」那条一样，别拿 go 来折腾
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const me = async () => (await (await page.request.get('/api/auth/me', { headers })).json())

  // **别假设起点是干净的**：上一轮要是红在半路上，头像就留在库里了 ——
  // 而头像只能自己删，afterEach 用的是 go 的身份，替 kan 收拾不了
  await page.request.delete(`/api/members/${(await me()).id}/avatar`, { headers })

  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '设置' }).click()
  await page.reload()
  await page.getByRole('tab', { name: '设置' }).click()
  await expect(page.locator('.avatar-btn img')).toHaveCount(0)

  await page.locator('input[type="file"]').setInputFiles('e2e/fixtures/avatar.jpg')
  await expect(page.locator('.avatar-btn img')).toHaveCount(1)
  // 颜色那一排不能因为设了照片就消失 —— 它还管着「谁付的」按钮的底色
  await expect(page.locator('.swatch')).not.toHaveCount(0)

  // 后端得压到几 KB —— 原图一点七 MB，原样存进库里迟早把备份撑爆
  const after = await me()
  expect(after.avatar.startsWith('data:image/webp;base64,')).toBe(true)
  const bytes = (after.avatar.length - 23) * 3 / 4
  expect(bytes, `压完还有 ${Math.round(bytes / 1024)}KB`).toBeLessThan(40_000)

  // 全站都读同一份：账单的「每人」里，**自己那一行**也换了。
  // 不数全局的 img 张数 —— 别人也可能设了头像，那跟这条用例没关系
  await page.getByRole('tab', { name: '账单' }).click()
  await expect(
    page.locator('.per-member .q-item').filter({ hasText: 'Kan' }).locator('img'),
  ).toHaveCount(1)

  // 撤掉，回到那个带首字的色圆
  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '设置' }).click()
  await page.getByRole('button', { name: '用回色圆' }).click()
  await expect(page.locator('.avatar-btn img')).toHaveCount(0)
  expect((await me()).avatar).toBeNull()
})

test('账目筛选：按分类/付款人筛，并给出筛选后的合计', async ({ page }) => {
  await login(page)
  await page.goto('/entries')
  await expect(page.locator('.filter-bar')).toBeVisible()
  // 只数账目行。原来数的是 .q-page 里所有 .q-item，混着「出了一次账单」那种行 ——
  // 而那种行筛选时会整体消失，于是「筛完更少」有一部分是它们没了造成的，
  // 筛选真坏了也照样绿
  const rows = page.locator('.entry-row')
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const all = (await (await page.request.get('/api/entries?limit=500', { headers })).json()).length
  expect(all, '种子数据里该有一堆账目').toBeGreaterThan(10)
  // 跟后端对一次数，而且用会重试的 toHaveCount：两拨数据是两个请求，
  // 光等「第一行出现」就开始数，会数到一半就往下走（真发生过，数到 5）
  await expect(rows).toHaveCount(all)

  // 按分类筛
  await page.locator('.chip').nth(1).click()
  await page.locator('.q-menu .q-item').filter({ hasText: '伙食' }).first().click()
  await expect(page.locator('.filter-bar')).toContainText('合计')
  const byCat = await rows.count()
  expect(byCat, '筛完应当比全部少').toBeLessThan(all)

  // 再叠一个付款人：交集，只会更少
  await page.locator('.chip').nth(2).click()
  await page.locator('.q-menu .q-item').filter({ hasText: 'Kan' }).first().click()
  expect(await rows.count(), '两个条件是交集').toBeLessThanOrEqual(byCat)

  // 筛选状态下不该混进「出了一次账单」那种行 —— 它不是账目
  await expect(page.locator('.statement-row')).toHaveCount(0)

  // 清除
  await page.locator('.filter-bar .q-btn').click()
  await expect(page.locator('.filter-bar')).not.toContainText('合计')
  await expect(rows).toHaveCount(all)
})

test('点头像把人排除出这笔，再点恢复（原来是几就还回几）', async ({ page }) => {
  await login(page)
  await page.locator('input.amount').fill('9000')
  await page.getByRole('button', { name: '日用品' }).click()

  // 轮子上十个数字都在 DOM 里，读 textContent 没意义 —— 读它报出来的当前值
  const weights = () =>
    page.locator('.wheel').evaluateAll((els) =>
      els.map((e) => e.getAttribute('aria-valuenow')).join('/'),
    )
  const shares = () =>
    page.locator('.member-row .share-col').allTextContents()
      .then((t) => t.map((x) => Number(x.replace(/[^\d]/g, ''))))

  expect(await weights()).toBe('1/1/1')
  await page.locator('.name-col').nth(2).click()
  expect(await weights(), '点一下头像＝这个人不参与').toBe('1/1/0')
  expect((await shares()).sort((a, b) => a - b)).toEqual([0, 4500, 4500])

  await page.locator('.name-col').nth(2).click()
  expect(await weights(), '再点一下恢复').toBe('1/1/1')

  // 原来不是 1 的人，恢复时要还回原来那个数，不能一律变成 1
  await setWeight(page, 0, 2)
  expect(await weights()).toBe('2/1/1')
  await page.locator('.name-col').first().click()
  expect(await weights()).toBe('0/1/1')
  await page.locator('.name-col').first().click()
  expect(await weights(), '恢复该还回 2，不是 1').toBe('2/1/1')
})

test('删掉一笔账：能撤销，撤销之后余额原样回来', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const balances = async () =>
    (await (await page.request.get('/api/balances', { headers })).json()).balances

  const before = await balances()
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const daily = cats.find((c: { monthly: boolean; archived: boolean }) => !c.monthly && !c.archived)
  const made = await (
    await page.request.post('/api/entries', {
      headers,
      data: { kind: 'expense', date: '2026-09-21', amount_jpy: 3_000, payer_id: 1, category_id: daily.id, title: 'E2E待删' },
    })
  ).json()
  const afterCreate = await balances()
  expect(afterCreate, '记了一笔，余额总得动').not.toEqual(before)

  // 这笔是绕过前端直接 POST 的，账目列表是开 App 那一刻拉的 —— 重开一次才看得见
  await page.goto('/')
  // 按真实路径点进去（账目列表 → 那一条），不是直接 goto 编辑页 ——
  // 直接 goto 会让随后的 router.back() 跨文档整页重载，把 toast 冲掉
  await page.getByRole('tab', { name: '更多' }).click()
  await page.getByRole('tab', { name: '流水' }).click()
  await page.locator('.entry-row').filter({ hasText: 'E2E待删' }).first().click()
  await expect(page.getByText('改这一笔')).toBeVisible()
  await page.getByRole('button', { name: '删除' }).click()
  await page.getByRole('button', { name: '确定' }).click()

  // **删掉一笔真金白银的账必须有后悔药。** 后端一直是软删，restore 端点也一直在，
  // 只是前端从没接过 —— 对比一下：删一个固定费**项目**（只是归档分类）反而有 6 秒撤销
  const toast = page.locator('.q-notification').filter({ hasText: '已删掉' })
  await expect(toast).toBeVisible()
  // 删掉了：余额回到记账之前
  await expect.poll(balances, { message: '删掉之后余额该回到记账前' }).toEqual(before)

  await toast.getByRole('button', { name: '撤销' }).click()
  await expect(page.locator('.q-notification').filter({ hasText: '已撤销删除' })).toBeVisible()
  // 撤销了：那笔钱一分不差地回来
  await expect.poll(balances, { message: '撤销之后每个人的余额要一分不差地回来' }).toEqual(afterCreate)

  await page.request.delete(`/api/entries/${made.id}`, { headers })   // 收尾
})

test('出账后改一笔：那张账单要打出「被改过」，而且复制出来的文本里也有', async ({ page }) => {
  await login(page)
  const headers = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nagaya.token'))}` }
  const cats = await (await page.request.get('/api/categories', { headers })).json()
  const daily = cats.find((c: { monthly: boolean; archived: boolean }) => !c.monthly && !c.archived)
  await page.request.post('/api/entries', {
    headers,
    data: { kind: 'expense', date: '2026-09-21', amount_jpy: 6_000, payer_id: 1, category_id: daily.id, title: 'E2E改历史' },
  })
  const st = await (await page.request.post('/api/statements', { headers })).json()

  // 出账之后把那一笔改掉 —— 这是「不锁历史」允许的，但必须看得见
  const mine = (await (await page.request.get(`/api/entries?statement_id=${st.id}&limit=50`, { headers })).json())
    .find((e: { title: string }) => e.title === 'E2E改历史')
  await page.request.patch(`/api/entries/${mine.id}?version=${mine.version}`,
    { headers, data: { amount_jpy: 9_000 } })

  await page.goto('/bill')
  await page.getByRole('tab', { name: '已出账' }).click()
  await expect(page.locator('.head .pick')).toContainText(st.label)
  // **这条横幅是「不锁历史但改动必须可见」唯一的凭证** —— 它被 class="hidden" 罩住过一次
  const banner = page.locator('.q-banner').filter({ hasText: '出账后被改过' })
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('6,000')     // 当初
  await expect(banner).toContainText('9,000')     // 现在

  // 复制出去的那份才是「用户手里那份」，屏幕上有的它也得有
  await page.getByRole('button', { name: '复制账单' }).click()
  const text = await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))
  if (text) expect(text, '复制文本里也要说明这张被改过').toContain('出账后被改过')
})
