import { fileURLToPath, URL } from 'node:url'

import { quasar, transformAssetUrls } from '@quasar/vite-plugin'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

/** 打包时刻，印在设置页最底下 —— 手机上装的到底是哪一版，不用再猜 */
const BUILD = new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Tokyo' }).slice(0, 16)

export default defineConfig({
  define: {
    __BUILD__: JSON.stringify(BUILD),
    // vue-i18n 里用不上的几块：老式 API、全局注册的 <i18n-t> 组件、生产环境的调试钩子。
    // 关掉之后框架那一块小 14KB
    __VUE_I18N_LEGACY_API__: false,
    __VUE_I18N_FULL_INSTALL__: false,
    __INTLIFY_PROD_DEVTOOLS__: false,
  },
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
        background_color: '#ffffff',   // 启动闪屏的底，跟图标的白底接上
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

        // 图标字体也进预缓存。不进的话 iOS 把 HTTP 缓存清掉之后，断网冷启动时
        // 底栏和按钮上的图标全是空白，三秒后变成「add_circle」这种英文字
        globPatterns: ['**/*.{js,css,html,woff2}'],

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
            // **只走网络，不按 URL 另存一份壳。** 原来是 NetworkFirst + 'nagaya-shell'：
            // 每个地址各存一份，发版之后 '/' 那份可能还是上一版 —— 断网冷启动拿到它，
            // 入口脚本早就不在新的预缓存里，白屏，离线草稿也记不了。
            // SPA 所有路由都是同一份 index.html，预缓存里本来就有一份和资源同版的。
            //
            // 写成 NetworkFirst 是因为 workbox 只许它带超时（NetworkOnly 不收
            // networkTimeoutSeconds），而超时是在外面用流量、够不着家里局域网时
            // 不干等一分钟的关键。缓存换了个新名字、并且**一份都不让存**
            // （cacheableResponse 的状态码永远对不上）—— 旧的 nagaya-shell 不再被读
            handler: 'NetworkFirst',
            options: {
              cacheName: 'nagaya-nav',
              cacheableResponse: { statuses: [-1] },
              networkTimeoutSeconds: 3,      // 服务器不在就别干等
              // 网络不通：退回预缓存里**同一版**的壳，而不是一张浏览器的断网页。
              // 离线草稿那条路靠的就是能打开
              precacheFallback: { fallbackURL: 'index.html' },
              // **超时**那一支走的是「查缓存」，而这个缓存永远是空的 —— 查不到的话
              // NetworkFirst 会接着干等网络，3 秒的超时形同虚设。查不到就交出预缓存里
              // 同一版的 index.html（这个函数会被原样写进 sw.js，跑在 SW 里）
              plugins: [
                {
                  cachedResponseWillBeUsed: async ({ cachedResponse }) => {
                    if (cachedResponse) return cachedResponse
                    const scope = (self as unknown as { registration: { scope: string } }).registration.scope
                    const cache = await caches.open(`workbox-precache-v2-${scope}`)
                    return (await cache.match(new URL('index.html', scope).href, { ignoreSearch: true })) ?? null
                  },
                },
              ],
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
    outDir: 'dist/pwa',   // 后端 app/spa.py 挂这个目录（main.py 调 spa.mount），单端口部署
    rollupOptions: {
      output: {
        // 框架（Vue、路由、Pinia、vue-i18n）单独一块。原来它和文案、API 客户端打在一起，
        // 改一个字那 200KB 的哈希就变，每台手机都得整块重下
        codeSplitting: {
          groups: [{ name: 'vendor', test: /node_modules[\\/](@vue|vue|pinia|vue-router|vue-i18n|@intlify)[\\/]/ }],
        },
      },
    },
  },
})
