import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from 'src/api/client'
import type { Category, Member, Setting } from 'src/api/types'
import { forgetAvatars } from 'src/avatars'
import { useAuth } from 'src/stores/auth'

/** 成员、分类、配置 —— 变得少，登录后拉一次就够。 */
export const useMeta = defineStore('meta', () => {
  const auth = useAuth()
  const members = ref<Member[]>([])
  const categories = ref<Category[]>([])
  const settings = ref<Setting[]>([])

  const activeMembers = computed(() => members.value.filter((m) => m.is_active))

  /**
   * 自己排第一位。记账的人十有八九记的是自己付的那笔，也最常在分摊里找自己 ——
   * 让它总在最左边/最上面，眼睛不用每次重新找。
   */
  const activeMembersSelfFirst = computed(() => {
    const me = auth.me?.id
    const mine = activeMembers.value.filter((m) => m.id === me)
    return [...mine, ...activeMembers.value.filter((m) => m.id !== me)]
  })
  const byId = computed(() => Object.fromEntries(members.value.map((m) => [m.id, m])))

  /**
   * **某一天**在籍的人，自己排第一。
   *
   * 记一笔可以把日期往回调（调到上次出账那天为止），而后端是按**这笔账的日期**
   * 挑参与人的（ledger.active_members(on)）。前端要是拿「今天在籍」去算预览，
   * 日期一旦跨过谁的入住日/退出日，预览和落库就分到了不同的人头上 —— 差的是
   * 整整一份钱，界面上一声不吭。
   */
  function membersOn(date: string): Member[] {
    const on = members.value.filter((m) => date >= m.joined_on && (!m.left_on || date <= m.left_on))
    const me = auth.me?.id
    return [...on.filter((m) => m.id === me), ...on.filter((m) => m.id !== me)]
  }

  /** 日常记账那屏的分类：不含每月一次的固定项，也不含归档的 */
  const dailyCategories = computed(() =>
    categories.value.filter((c) => !c.monthly && !c.archived),
  )
  /** 出账单时顺手填的固定项 */
  const monthlyCategories = computed(() =>
    categories.value.filter((c) => c.monthly && !c.archived),
  )
  /**
   * 按 id 反查分类，**含归档的**。
   * 历史账目要靠它显示名字和图标 —— 只拿未归档列表去反查的话，
   * 归档掉一个分类，它名下所有历史账目当场掉成「支出」两个字加默认图标。
   */
  const categoryById = computed(() =>
    Object.fromEntries(categories.value.map((c) => [c.id, c])),
  )

  function setting<T>(key: string, fallback: T): T {
    const row = settings.value.find((s) => s.key === key)
    return row === undefined || row.value === null ? fallback : (row.value as T)
  }

  /**
   * 这三样是整个界面的地基（布局要等 members 到齐才渲染），所以**存一份在本地**。
   *
   * 离线冷启动原来是死的：meta.load() 一抛，布局那句 v-if="meta.members.length"
   * 永远不成立，整个 app 停在转圈上 —— 而「断网也能填完、回来补交」（D15）
   * 正是这个 App 的卖点之一，偏偏在最需要它的时候用不了。
   */
  const CACHE_KEY = 'nagaya.meta'

  /** 换人用之前把本地这份忘掉 —— 上一位的成员/分类/设置不该留给下一位 */
  function forget(): void {
    members.value = []
    categories.value = []
    settings.value = []
    forgetAvatars()
    try {
      localStorage.removeItem(CACHE_KEY)
    } catch {
      /* 隐私模式下删不了就算了 */
    }
  }

  function useCached(): boolean {
    try {
      const raw = localStorage.getItem(CACHE_KEY)
      if (!raw) return false
      const cached = JSON.parse(raw) as { m: Member[]; c: Category[]; s: Setting[] }
      if (!cached.m?.length) return false
      members.value = cached.m
      categories.value = cached.c ?? []
      settings.value = cached.s ?? []
      return true
    } catch {
      return false
    }
  }

  async function load() {
    try {
      const [m, c, s] = await Promise.all([
        api.get<Member[]>('/api/members'),
        // 拉全量（含归档）：展示用的列表自己过滤，反查名字要用全量，
        // 否则归档一个分类会让它名下的历史账目失名
        api.get<Category[]>('/api/categories?include_archived=true'),
        api.get<Setting[]>('/api/settings'),
      ])
      members.value = m
      categories.value = c
      settings.value = s
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({ m, c, s }))
      } catch {
        /* 隐私模式下存不了就算了，只是下次离线启动没得回退 */
      }
    } catch (e) {
      // 有缓存就照常开门；一次都没成功过（新装的 PWA 首次就离线）才认输
      if (!useCached()) throw e
    }
  }

  /**
   * 记新账时默认算谁付的：设置里的「默认垫付人」—— **前提是他那天还住在这儿**。
   * 人搬走之后这条设置往往没人记得去改，照用的话，新记的日用品都算成已经不住
   * 这儿的人垫的，账单反过来叫留下的人给他转账。不在籍就退回自己
   */
  function defaultPayerOn(date: string): number | null {
    const set = setting<number | null>('default_payer_id', null)
    if (set !== null && membersOn(date).some((m) => m.id === set)) return set
    return auth.me?.id ?? null
  }

  return {
    members, categories, settings,
    activeMembers, activeMembersSelfFirst, membersOn, byId, defaultPayerOn,
    dailyCategories, monthlyCategories, categoryById,
    setting, load, forget,
  }
})
