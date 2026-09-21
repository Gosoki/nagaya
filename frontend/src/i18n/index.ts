/**
 * 中日双语 —— SPEC §7.5。
 *
 * 规矩：
 *   * 界面文案全在这里，`.vue` 里只写 t('xxx')，不许出现裸中日文字符串
 *   * **用户数据不翻译**：分类名、备注是用户自己录的，录什么显示什么
 *   * 语言跟人走（member.lang），没登录时看浏览器语言
 */
import { Lang as QuasarLang } from 'quasar'
import quasarJa from 'quasar/lang/ja'
import quasarZh from 'quasar/lang/zh-CN'
import { createI18n } from 'vue-i18n'

import ja from './ja'
import zh from './zh'

export type Lang = 'zh' | 'ja'

export function detectLang(): Lang {
  const saved = localStorage.getItem('nagaya.lang')
  if (saved === 'zh' || saved === 'ja') return saved
  return navigator.language.startsWith('ja') ? 'ja' : 'zh'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLang(),
  fallbackLocale: 'zh',
  messages: { zh, ja },
})

/**
 * Quasar 自带的文案（弹框的取消/确定、日历的星期）是另一套，得跟着一起切。
 *
 * 两个包都静态引进来（各几 KB）。用动态 import 踩过两个坑：
 *   1. 拼出来的路径 Vite 分析不了，运行时报「does not resolve to a valid URL」
 *   2. main.ts 里的 app.use(Quasar, { lang }) 是同步的，会把异步设好的值盖回去
 *
 * 类型这里断言一次：Quasar 导出的语言包类型和 Lang.set 的签名对不上
 * （formatNumber 一个收必填参数、一个收可选参数），是库自己的类型 bug。
 */
// 不给返回值标类型：让它保持语言包自己的类型，main.ts 那边的插件选项才认。
// Lang.set 期望的又是另一个（互不兼容的）类型，所以在调用处单独断言
export const quasarLang = (lang: Lang) => (lang === 'ja' ? quasarJa : quasarZh)

export function setLang(lang: Lang) {
  i18n.global.locale.value = lang
  localStorage.setItem('nagaya.lang', lang)
  document.documentElement.lang = lang
  QuasarLang.set(quasarLang(lang) as Parameters<typeof QuasarLang.set>[0])
}

/** 金额显示随语言变：中文 ¥12,345 / 日语 12,345円 */
export function formatYen(n: number): string {
  const abs = Math.abs(n).toLocaleString('en-US')
  const sign = n < 0 ? '-' : ''
  return i18n.global.locale.value === 'ja' ? `${sign}${abs}円` : `${sign}¥${abs}`
}
