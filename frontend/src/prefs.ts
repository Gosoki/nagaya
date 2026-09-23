/**
 * 个人偏好（深浅色、主题色）**跟着账号走**：换台手机登录，还是自己挑的那一套。
 *
 * 服务器上那份是准的（member_pref 表）。本机 localStorage 那份（src/colorScheme.ts、
 * src/themeColor.ts 各管各的键）只是缓存 —— 首帧要靠它在 JS 起来之前就上色
 * （index.html 那段小脚本），断网冷启动也靠它。
 *
 * 什么时候对表：
 *   * 登录那一下：整套换成这个人的。服务器上没有的项退回默认 ——
 *     这台设备上现有的可能是上一位留下的；
 *   * 冷启动、切回前台：服务器上有的就用服务器的（别的设备上改过）。
 *     服务器上**还没有**、本机却挑过的，传上去 —— 这两项原来只存在本机，
 *     升级后第一次对表别把人挑好的颜色冲掉。
 */
import { api } from 'src/api/client'
import { schemePref, type SchemePref } from 'src/colorScheme'
import { THEME_COLORS, themeColor } from 'src/themeColor'

type Key = 'scheme' | 'theme_color'
type Prefs = Partial<Record<Key, string>>

const DEFAULTS: Record<Key, string> = { scheme: 'auto', theme_color: 'indigo' }
const KEYS = Object.keys(DEFAULTS) as Key[]

function current(key: Key): string {
  return key === 'scheme' ? schemePref.value : themeColor.value
}

/** 换上。认不出的值（比如以后删掉了某个颜色）退回默认 */
function put(key: Key, value: string | undefined) {
  if (key === 'scheme') {
    schemePref.value = (value === 'light' || value === 'dark' ? value : 'auto') as SchemePref
  } else {
    themeColor.value = THEME_COLORS.some((c) => c.id === value) ? value! : DEFAULTS.theme_color
  }
}

/** 和服务器对一次表。`adopt` 见文件头：登录时 false，冷启动/切回前台时 true */
export async function syncPrefs(adopt: boolean): Promise<void> {
  const server = await api.get<Prefs>('/api/prefs')
  const up: Prefs = {}
  for (const key of KEYS) {
    if (server[key] !== undefined) put(key, server[key])
    else if (adopt && current(key) !== DEFAULTS[key]) up[key] = current(key)
    else put(key, undefined)
  }
  if (Object.keys(up).length) await api.patch('/api/prefs', up)
}

/** 设置页上点了一下：先换上，再存进账号；存不上就换回去，让调用方报错 */
export async function setPref(key: Key, value: string): Promise<void> {
  const before = current(key)
  put(key, value)
  try {
    await api.patch('/api/prefs', { [key]: value })
  } catch (e) {
    put(key, before)
    throw e
  }
}
