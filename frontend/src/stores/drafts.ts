/**
 * 离线草稿 —— D15。
 *
 * 只做「没网时把这一笔留在本地」，**不做后台自动同步**：
 * 宁可让人点一下补交，也不要「以为存上了其实没有」。钱的事不能悄悄失败。
 *
 * localStorage 在隐私模式/禁用站点数据时会直接抛异常，所有读写都包了 try/catch，
 * 拿不到就当没有草稿 —— 不能因为存不了草稿把整个页面弄崩。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'
import { useAuth } from 'src/stores/auth'
import { useLedger } from 'src/stores/ledger'

const KEY = 'nagaya.drafts'

export interface Draft {
  id: string
  savedAt: string
  payload: EntryPayload
  /**
   * 谁存的。**草稿按人隔离**：退出登录不清草稿（里面是真填过的钱），
   * 但下一个登录这台设备的人不该看见、补交或丢弃上一位的。
   * 老版本存的没有这个字段 —— 那几条谁登录都给看，和原来一样
   */
  memberId?: number | null
}

function read(): Draft[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Draft[]) : []
  } catch {
    return []
  }
}

/** 写进本机。**写没写进去要说出来**（见 add）：别的调用方存不了就算了，至少别把页面弄崩 */
function write(list: Draft[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
    return true
  } catch {
    return false
  }
}

export const useDrafts = defineStore('drafts', () => {
  const auth = useAuth()
  const items = ref<Draft[]>(read())
  /** 当前登录的这个人的草稿（加上没记名的老草稿） */
  // 没记名的（老版本存的、或者存的那一刻还没认出自己是谁 —— 离线冷启动）谁都给看：
  // 按「记名为 null」过滤的话，身份一认出来，这笔钱就既看不见、也交不了、也丢不掉
  const mine = computed(() =>
    items.value.filter((d) => d.memberId == null || d.memberId === auth.me?.id),
  )
  const count = computed(() => mine.value.length)

  /**
   * 存一笔草稿。**写不进本机就返回 false，而且不留只活在内存里的那一份。**
   * 站点存储被整个禁用时（iOS「阻止所有 Cookie」）setItem 会抛：原来照样提示
   * 「先存在本地了」、清空表单，横幅也挂着 —— 可那一笔只在内存里，PWA 被系统杀掉、
   * 或者整页重载换新版之后就没了。现在调用方据此把表单留着，钱还在人眼前
   */
  function add(payload: EntryPayload, memberId: number | null): boolean {
    const next = [
      ...items.value,
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        savedAt: new Date().toISOString(),
        payload,
        memberId,
      },
    ]
    if (!write(next)) return false
    items.value = next
    return true
  }

  function remove(id: string) {
    items.value = items.value.filter((d) => d.id !== id)
    write(items.value)
  }

  /** 丢弃**自己的**草稿。别人的留着不动 */
  function clear() {
    const drop = new Set(mine.value.map((d) => d.id))
    items.value = items.value.filter((d) => !drop.has(d.id))
    write(items.value)
  }

  /**
   * 补交。逐条提交，成功一条删一条 —— 中途再断网也不会重复提交已成功的。
   *
   * **区分「没网」和「后端不收」。** 原来一律算失败、一律报「连不上服务器」：
   * 一条被后端明确拒绝的草稿（金额为 0、分类被归档了）会永远卡在那儿，
   * 横幅一直挂着「有 1 笔没提交」，点多少次都是同一句错话，而真正的原因一个字都看不到。
   * **日期早于上次出账不在其中**：后端照收，这笔进的是当前草稿账单、不是那张已出的
   * （DraftBanner 补交完会说一句）。
   *
   * 被拒的那条照样留着（里面是用户真填过的钱，不能替他扔掉），但要把后端那句话
   * 带回去说清楚，让人知道该去改哪儿。
   */
  async function submitAll(): Promise<{ ok: number; offline: number; rejected: string[]; saved: Entry[] }> {
    const ledger = useLedger()
    let ok = 0
    let offline = 0
    const rejected: string[] = []
    /** 交上去的那几笔（后端回的样子）：横幅逐笔报「已记下 · 日用 ¥1,234」并给撤销 */
    const saved: Entry[] = []
    for (const draft of [...mine.value]) {
      // 补交进行中被丢弃了（点了「丢弃」、或者别的入口清过）：不许再交出去
      if (!items.value.some((d) => d.id === draft.id)) continue
      try {
        // 走 ledger.create 而不是自己打接口：**「写完要刷哪几份缓存」只该有一处定义**。
        // 自己打的话账单缓存一份都不刷，而这个横幅在 /bill 上也挂着 ——
        // 补交完成，账单页原地停在旧数字，一键复制就把错的合计发进群了
        saved.push(await ledger.create(draft.payload))
        remove(draft.id)
        ok += 1
      } catch (e) {
        if (e instanceof ApiError && e.code !== 'network') rejected.push(e.text)
        else offline += 1
      }
    }
    return { ok, offline, rejected, saved }
  }

  return { mine, count, add, remove, clear, submitAll }
})
