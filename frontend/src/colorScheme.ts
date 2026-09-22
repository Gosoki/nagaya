/**
 * 深浅色。默认跟系统走，每个人可以在「设置 → 个人」里钉成浅色或深色。
 *
 * **存在这台设备上（localStorage），不进账号。** 进账号就得给 member 表加一列，
 * 而 D18 之前的约定是不给已有的表加字段（create_all 不补列，老库一开就是
 * `no such column`）。每个人用的是自己的手机，存在本机就等于「归个人」；
 * 同一个人换一台设备要再选一次 —— 这是代价，切 Alembic 之后可以挪进账号。
 *
 * 首帧的深浅在 index.html 里那段小脚本定（读同一个键），这里接手之后的切换：
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

/** 这台设备上选的是哪一档。设置页那个三选一直接绑它 */
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
