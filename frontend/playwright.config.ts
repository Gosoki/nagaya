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
    baseURL: process.env.NAGAYA_URL ?? 'http://127.0.0.1:8000',
    ...devices['iPhone SE'],
    viewport: { width: 375, height: 667 },
    deviceScaleFactor: 2,
  },
  reporter: [['list']],
})
