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
  },
})
