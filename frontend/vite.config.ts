import { fileURLToPath, URL } from 'node:url'

import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

/** 打包时刻，印在设置页最底下 —— 手机上装的到底是哪一版，不用再猜 */
const BUILD = new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Tokyo' }).slice(0, 16)

export default defineConfig({
  define: { __BUILD__: JSON.stringify(BUILD) },
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
        // 多一层规则等于多一层可能出问题的东西。
        navigateFallbackDenylist: [/^\/api/],

        // **导航请求（刷新、点链接、打开 PWA）先问服务器。**
        // 默认行为是把 index.html 预缓存起来、导航一律吃缓存，于是发了新版要刷好几次
        // 才看得到：第一次刷出来的还是缓存里的旧壳子，新 SW 在后台装好、接管、再自己
        // reload 一次，才轮到新版。局域网自托管，先问一下服务器几乎没有代价。
        // 离线时落回缓存，离线草稿那条路不受影响。
        navigateFallback: undefined,
        // 光去掉 navigateFallback 不够：预缓存默认带 directoryIndex: 'index.html'，
        // 于是访问 `/` 会先命中预缓存里那份 index.html，下面这条规则根本轮不到。
        // 症状就是「发了新版，刷几次还是旧画面」——服务器上早就是新的了。
        directoryIndex: null,
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'nagaya-shell',
              networkTimeoutSeconds: 3,      // 服务器不在就别干等
              expiration: { maxEntries: 16 },
              // 网络不通、这个地址也没在 nagaya-shell 里缓存过（刚装到主屏后的
              // 第一次离线启动、或者头一回离线点进某个深链）：退回预缓存里
              // **同一版**的壳，而不是一张浏览器的断网页。离线草稿那条路靠的就是能打开
              precacheFallback: { fallbackURL: 'index.html' },
            },
          },
        ],
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
