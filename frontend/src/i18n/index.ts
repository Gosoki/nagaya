/**
 * 中日双语 —— SPEC §7.5。
 *
 * 规矩：
 *   * 界面文案全在这里，`.vue` 里只写 t('xxx')，不许出现裸中日文字符串
 *   * **用户数据不翻译**：分类名、备注是用户自己录的，录什么显示什么
 *   * 语言跟人走（member.lang），没登录时看浏览器语言
 */
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

export function setLang(lang: Lang) {
  i18n.global.locale.value = lang
  localStorage.setItem('nagaya.lang', lang)
  document.documentElement.lang = lang
}

/** 金额显示随语言变：中文 ¥12,345 / 日语 12,345円 */
export function formatYen(n: number): string {
  const abs = Math.abs(n).toLocaleString('en-US')
  const sign = n < 0 ? '-' : ''
  return i18n.global.locale.value === 'ja' ? `${sign}${abs}円` : `${sign}¥${abs}`
}
