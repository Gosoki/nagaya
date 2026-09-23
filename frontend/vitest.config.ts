import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'

export default defineConfig({
  // 跟 vite.config.ts 一样的别名：被测的模块里写的是 'src/xxx'
  resolve: {
    alias: { src: fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['test/**/*.spec.ts'],
    // 浏览器存储的替身，每个测试文件跑之前各挂一份新的
    setupFiles: ['test/setup.ts'],
  },
})
