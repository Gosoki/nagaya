/**
 * 深浅色。默认跟系统走，每个人可以在「设置 → 个人」里钉成浅色或深色。
 *
 * **跟着账号走**（存在服务器的 member_pref 表里，和服务器对表见 src/prefs.ts）。
 * 这里的 localStorage 只是本机缓存：首帧的深浅在 index.html 里那段小脚本定
 * （读同一个键），那会儿 JS 还没起来、更没登录。
 *
 * 这里接手之后的切换：
 * html 上挂不挂 .dark（tokens.css 的深色值挂在它上面）、Quasar 的 Dark 插件
 * （弹窗、菜单、日期选择器这些 Quasar 自己画的东西）、以及 theme-color。
 */
import { Dark } from 'quasar'
import { ref, watch } from 'vue'

export type SchemePref = 'auto' | 'light' | 'dark'

const KEY = 'nagaya.scheme'

function read(): SchemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'auto'
  } catch {
    return 'auto'                       // 隐私模式下读不了：跟系统
  }
}

/** 现在用的是哪一档。设置页那个三选一显示它，改它走 src/prefs.ts 的 setPref */
export const schemePref = ref<SchemePref>(read())

watch(schemePref, (p) => {
  try {
    if (p === 'auto') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, p)
  } catch {
    /* 存不了就只管这一次打开 */
  }
  Dark.set(p === 'auto' ? 'auto' : p === 'dark')
})

/**
 * 把「现在到底是不是深色」同步到页面上。Quasar 插件装好之后调一次。
 *
 * theme-color 也得跟着换：iOS 拿它去填状态栏后面、以及拉过头露出来的那块。
 * 深色模式下还是白的话，一拉就是一道白边。
 */
export function installColorScheme() {
  Dark.set(schemePref.value === 'auto' ? 'auto' : schemePref.value === 'dark')
  watch(
    () => Dark.isActive,
    (on) => {
      document.documentElement.classList.toggle('dark', on)
      const bar = getComputedStyle(document.documentElement)
        .getPropertyValue('--nagaya-bar-solid')
        .trim()
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bar || (on ? '#18191c' : '#f9f9fb'))
    },
    { immediate: true },
  )
}
