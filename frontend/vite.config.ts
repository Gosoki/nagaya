import { fileURLToPath, URL } from 'node:url'

import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue({ template: { transformAssetUrls } }),
    quasar({ sassVariables: 'src/quasar-variables.sass' }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/apple-touch-icon.png', 'icons/favicon.png'],
      manifest: {
        name: '長屋 nagaya',
        short_name: '長屋',
        description: '合租记账',
        theme_color: '#3d4785',
        background_color: '#3d4785',
        display: 'standalone',       // 全屏，没有地址栏 —— 这就是「像个 App」的分界线
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'icons/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // API 一律走网络，绝不能缓存 —— 账本读到旧数据比读不到更糟。
        // 不另写 runtimeCaching 的 NetworkOnly 规则：没匹配上的请求本来就直接走网络，
        // 多一条规则等于多一层可能出问题的东西。
        navigateFallbackDenylist: [/^\/api/],
      },
    }),
  ],
  resolve: {
    alias: { src: fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 9000,
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: {
    outDir: 'dist/pwa',   // 后端 main.py 就挂这个目录，单端口部署
  },
})
