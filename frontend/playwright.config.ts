import { defineConfig, devices } from '@playwright/test'

/**
 * 手机优先的验收基准（SPEC §7.4）。
 *
 * 视口**写死 375×667**，不用 devices['iPhone SE'] —— 那个是初代 SE 的 320px，
 * 设备名哪天改了基准就跟着悄悄变了。引擎仍用 WebKit：日本 iPhone 占比高，
 * 要验就验 Safari 的那套。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    // 没设就打 8765（和 run-e2e.sh 的默认端口一致）：没起测试服务就直接连不上，
    // 绝不会落到 8000 上那个自用服务去 —— 用例会拿开发账号登录、删「最新一笔」
    baseURL: process.env.NAGAYA_URL ?? 'http://127.0.0.1:8765',
    ...devices['iPhone SE'],
    viewport: { width: 375, height: 667 },
    deviceScaleFactor: 2,
    // 测试里关掉 service worker：SW 一旦接管 fetch，请求就不经过 Playwright 的
    // page.route，模拟断网那类测试会静默失效（看起来像"拦截没生效"，很难查）。
    // PWA 本身的产物另有一条用例直接拉 sw.js / manifest 来验。
    serviceWorkers: 'block',
  },
  reporter: [['list']],
})
