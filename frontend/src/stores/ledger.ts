import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'
import { useBills } from 'src/stores/bills'

/**
 * 账目列表。
 *
 * **写成功就是成功。** 写完之后的那些刷新（账单缓存、列表）一律不许把失败冒泡上来 ——
 * 原来 create/update/remove 都是 `await api.get('/api/balances')` 紧跟在写后面，
 * 于是「账已经记上了、只是后面那个 GET 断网了」会被调用方当成「这笔没记上」，
 * 原样存进离线草稿；补交时再 POST 一遍，账本里就有了两笔一模一样的钱。
 */
export const useLedger = defineStore('ledger', () => {
  const entries = ref<Entry[]>([])
  /** 上一张出过的账单是什么时候切的。用来挡住把日期选回已出账的范围里 */
  const prevCutAt = ref<string | null>(null)
  /**
   * 账目是一次性拉这么多笔。筛选和合计都在前端算，所以**拉少了就筛不全**。
   * 三个人按种子数据的速率大约每年一百笔，500 笔够五年 —— 到那天不能让合计
   * 悄悄少算，得先说出来。truncated 就是「还有更早的没拉到」
   */
  const LIMIT = 500
  const truncated = ref(false)
  /**
   * 防旧响应。开 App 时发出去的那次刷新还在路上，这边已经记了一笔（本地列表
   * 里插进去了）—— 那次刷新回来的是记账之前的列表，照写的话刚记的那笔就被抹掉。
   * seq 认「我是不是最新那一发」，writes 认「我出发之后本地有没有写过」
   */
  let seq = 0
  let writes = 0
  /** 上一次写进来的那份长什么样。改一笔 version 就变，出账 statement_id 就变，删掉就少一条 */
  let lastSig = ''
  const signature = (list: Entry[]) => list.map((x) => `${x.id}.${x.version}.${x.statement_id ?? ''}`).join()

  async function refresh() {
    const my = ++seq
    const w = writes
    // 不拉 /api/balances：它存下来之后没有任何组件读过（余额页早就并进账单页了），
    // 每次开 App、每记一笔都白跑一个来回
    const [e, sts] = await Promise.all([
      // 筛选在前端做，拉少了就筛不全
      api.get<Entry[]>(`/api/entries?limit=${LIMIT}`),
      // 「上一次出账」就是单子列表的第一张。原来为这个去拉整张草稿账单
      // （后端要把整本账算一遍），而账单页切回前台时自己还要再拉一次同一张
      useBills().loadStatements(),
    ])
    if (my !== seq) return                       // 后面还有更新的一发，交给它
    // 我出发之后本地写过（记了一笔、删了一笔）：这份列表里没有它。
    // **别整份丢掉就算了** —— 冷启动慢网时刚记的那一笔会成了流水里唯一的一笔，
    // 日期锁也跟着失效。再取一次，那一笔已经落库，新的列表里就有它
    if (w !== writes) return refresh()
    // 十有八九什么都没变（切回前台就刷一次）：没变就不换数组，
    // 换了的话账目页几百行、账单页每一块都跟着整个重画
    const sig = signature(e)
    if (sig !== lastSig) {
      lastSig = sig
      entries.value = e
    }
    truncated.value = e.length >= LIMIT
    prevCutAt.value = sts[0]?.cut_at ?? null
  }

  /** 存完用**后端返回的 shares 覆盖本地预览值** —— 以后端为准（SPEC §7.3）。 */
  async function create(payload: EntryPayload): Promise<Entry> {
    const saved = await api.post<Entry>('/api/entries', payload)
    writes += 1
    lastSig = ''                 // 本地这份已经和上次拉的不一样了，下次刷新照写
    // 按 id 去重：补交离线草稿时，后端认出幂等键会把**已经在列表里的那一笔**还回来
    entries.value = [saved, ...entries.value.filter((e) => e.id !== saved.id)]
    // 账单那几页缓存着，记完这笔它们就旧了。后台刷，不清空 ——
    // 清空的话下次点过去又要白屏等一遍。**失败也不冒泡**：这笔已经记上了
    useBills().refreshCached(saved)
    return saved
  }

  /** 改一笔。version 是乐观锁：传你读到的那个，被人改过就会被后端挡下来 */
  async function update(id: number, version: number, payload: Partial<EntryPayload>): Promise<Entry> {
    const saved = await api.patch<Entry>(`/api/entries/${id}?version=${version}`, payload)
    writes += 1
    lastSig = ''                 // 本地这份已经和上次拉的不一样了，下次刷新照写
    entries.value = entries.value.map((e) => (e.id === id ? saved : e))
    useBills().refreshCached(saved)
    return saved
  }

  async function remove(entry: Entry) {
    await api.del(`/api/entries/${entry.id}?version=${entry.version}`)
    writes += 1
    lastSig = ''                 // 本地这份已经和上次拉的不一样了，下次刷新照写
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    useBills().refreshCached(entry)
  }

  /**
   * 账单上点「确认已完成」。不直接 POST 一笔转账：带上「打开对话框时看到还差多少」，
   * 后端在锁里重算，对不上就 409（transfer_changed）—— 两个人各点一次、
   * 或者「确定」被连点，都只记得上一笔
   */
  async function confirmTransfer(body: {
    statement_id: number | null
    from_id: number
    to_id: number
    amount: number
    expect_left: number
    date: string
  }): Promise<Entry> {
    const saved = await api.post<Entry>('/api/bill/confirm', body)
    writes += 1
    lastSig = ''                 // 本地这份已经和上次拉的不一样了，下次刷新照写
    entries.value = [saved, ...entries.value.filter((e) => e.id !== saved.id)]
    useBills().refreshCached(saved)
    return saved
  }

  /** 撤销刚才那次删除。后端一直是软删，只是以前前端没接这个入口 */
  async function restore(id: number): Promise<Entry> {
    const back = await api.post<Entry>(`/api/entries/${id}/restore`)
    writes += 1
    lastSig = ''                 // 本地这份已经和上次拉的不一样了，下次刷新照写
    entries.value = [back, ...entries.value.filter((e) => e.id !== id)]
    useBills().refreshCached(back)
    return back
  }

  return {
    entries, truncated, prevCutAt,
    refresh, create, update, remove, restore, confirmTransfer,
  }
})
