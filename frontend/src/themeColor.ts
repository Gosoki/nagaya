/**
 * 主题色。每个人自己挑，**跟着账号走**（和服务器对表见 src/prefs.ts）；
 * 这里的 localStorage 只是本机缓存，给首帧用。
 *
 * 管的是「界面的颜色」：底部导航、页签、按钮、链接、选中、聚焦框。
 * **不管三种账目的颜色** —— 支出藏青 / 收入绿 / 转账琥珀是「这一笔是什么」的信号，
 * 跟着主题色变的话，挑了绿色的人支出和收入就是一个颜色，记一笔那条实心色块
 * 防选错类型的作用就没了。所以支出单独一种颜色（--q-expense），固定藏青。
 *
 * **只给一组调过的颜色，不开放随便调**：每个颜色要在四个地方站得住 ——
 * 浅色下当字（白底上 ≥4.5:1）和当按钮底（白字 ≥4.5:1），深色下当字
 * （深色卡片上 ≥4.5:1）和当按钮底（白字 ≥4.5:1、和卡片分得开）。
 * 每一档三个值都算过，test/theme-colors.spec.ts 钉着。
 * 刻意没有红和绿：红是「应付/差额」，绿是「应收/收入」，主题色撞上它们会读错钱。
 */
import { ref, watch } from 'vue'

export interface ThemeColor {
  id: string
  /** 浅色下：字色和按钮底用同一个 */
  light: string
  /** 深色下的按钮底（白字压得住，和深色卡片分得开） */
  darkFill: string
  /** 深色下的字色（链接、选中的页签、聚焦框） */
  darkInk: string
}

export const THEME_COLORS: ThemeColor[] = [
  { id: 'indigo', light: '#3d4785', darkFill: '#5664c8', darkInk: '#a3acf6' },   // 默认，品牌色
  { id: 'blue', light: '#1d5fa8', darkFill: '#2f6fc0', darkInk: '#8cbcf4' },
  { id: 'teal', light: '#00766a', darkFill: '#0e7f72', darkInk: '#6fd6c7' },
  { id: 'purple', light: '#6b3fa0', darkFill: '#7e52b8', darkInk: '#c6a6f2' },
  { id: 'rose', light: '#a8174f', darkFill: '#c0275f', darkInk: '#f79ab9' },
  { id: 'amber', light: '#8f5a0a', darkFill: '#a8680c', darkInk: '#f2c170' },
  { id: 'slate', light: '#46586a', darkFill: '#56697c', darkInk: '#b0c1d2' },
  { id: 'graphite', light: '#33373d', darkFill: '#646b75', darkInk: '#c3c8d0' },
]

const KEY = 'nagaya.themeColor'
/** 首帧那段脚本（index.html）直接读这一份，免得在那儿再抄一遍色板 */
const VARS_KEY = 'nagaya.themeVars'

function read(): string {
  try {
    const v = localStorage.getItem(KEY)
    return THEME_COLORS.some((c) => c.id === v) ? v! : 'indigo'
  } catch {
    return 'indigo'
  }
}

/** 现在用的是哪一个。设置页那排色块显示它，改它走 src/prefs.ts 的 setPref */
export const themeColor = ref<string>(read())

function varsOf(id: string): Record<string, string> {
  const c = THEME_COLORS.find((x) => x.id === id) ?? THEME_COLORS[0]!
  return {
    '--nagaya-theme': c.light,
    '--nagaya-theme-dark-fill': c.darkFill,
    '--nagaya-theme-dark-ink': c.darkInk,
  }
}

function apply(id: string) {
  const root = document.documentElement.style
  for (const [k, v] of Object.entries(varsOf(id))) root.setProperty(k, v)
}

export function installThemeColor() {
  apply(themeColor.value)
  watch(themeColor, (id) => {
    apply(id)
    try {
      if (id === 'indigo') {
        localStorage.removeItem(KEY)
        localStorage.removeItem(VARS_KEY)
      } else {
        localStorage.setItem(KEY, id)
        localStorage.setItem(VARS_KEY, JSON.stringify(varsOf(id)))
      }
    } catch {
      /* 存不了就只管这一次打开 */
    }
  })
}
