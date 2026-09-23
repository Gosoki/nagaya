/**
 * 头像图片。成员列表里只带地址（`/api/members/3/avatar?v=2`），图在这儿单取。
 *
 * **按地址缓存，存在本机**：地址里带着版本号，谁换了头像版本号就加一、地址就变 ——
 * 下一次拉成员列表（冷启动、切回前台）一看地址对不上，取新的那张；
 * 没换过的一张都不重下。原来头像是 base64 塞在成员列表里的，每次切回前台
 * 三个人的头像整个重传一遍。
 *
 * 为什么不直接 <img src="/api/…">：<img> 带不了 Bearer token，那个端点要登录。
 * 所以 fetch 下来转成 data: 地址，顺手存进 localStorage —— 冷启动第一帧就有图，
 * 断网也在（后端给了一年的 immutable，浏览器自己的 HTTP 缓存再兜一层）。
 */
import { reactive } from 'vue'

import { api } from 'src/api/client'

const KEY = 'nagaya.avatars'

function read(): Record<string, string> {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

/** 地址 → data: 地址 */
const cache = reactive<Record<string, string>>(read())
const loading = new Set<string>()

/** `?v=` 前面那段：同一个人的头像，不管哪个版本 */
const base = (path: string) => path.split('?')[0]

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(cache))
  } catch {
    /* 存不了就只是下次冷启动要重新取 */
  }
}

async function load(path: string) {
  if (loading.has(path)) return
  loading.add(path)
  try {
    const blob = await api.blob(path)
    const data = await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(r.result as string)
      r.onerror = () => reject(r.error)
      r.readAsDataURL(blob)
    })
    cache[path] = data
    // 同一个人的旧版本扔掉，只留最新这张
    for (const k of Object.keys(cache)) if (k !== path && base(k) === base(path)) delete cache[k]
    save()
  } catch {
    /* 没取到：先显示色圆，下次再试 */
  } finally {
    loading.delete(path)
  }
}

/**
 * 这个地址现在能显示什么。新版本还没取到时**先用旧的那张顶着**，
 * 取到了再换 —— 别让头像在两张图之间闪一下色圆。
 */
export function avatarSrc(path: string | null | undefined): string | null {
  if (!path) return null
  if (path.startsWith('data:')) return path     // 升级前本机缓存的成员列表里还是整张图
  const hit = cache[path]
  if (hit) return hit
  void load(path)
  const b = base(path)
  const old = Object.keys(cache).find((k) => base(k) === b)
  return old ? cache[old]! : null
}

/** 换人登录之前清掉 */
export function forgetAvatars() {
  for (const k of Object.keys(cache)) delete cache[k]
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* 删不了就算了 */
  }
}
