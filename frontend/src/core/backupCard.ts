/**
 * 设置页「备份」那一块的两条判定（BackupCard.vue）。纯函数、不碰 i18n（test/backup-card.spec.ts）。
 */
import type { BackupStatus } from 'src/api/types'

/**
 * 底栏红点该亮什么：拿这一屏刚探到的状态现算，不再另问一次 /api/backup/alert ——
 * 那一问在后端又是一整遍探目录、验最新那份（审计 R17），设置页一开就跑两遍。
 * **和后端 services/backup.alert 是同一条规则**：status 报的错都算；自动备份开着、
 * 有过备份、却已经太久没出新的 —— backup_stale。一份都还没有、自动备份自己关了的「太久没备」都不算。
 * 那边改了口径，这里跟着改
 */
export function alertOf(st: Pick<BackupStatus, 'error' | 'every_hours' | 'last_at' | 'stale'>): string | null {
  if (st.error !== null) return st.error
  if (st.every_hours > 0 && st.last_at !== null && st.stale) return 'backup_stale'
  return null
}

/**
 * 手点「立即备份」失败的那句还挂不挂（只在这一屏的组件状态里，不存进后端）。
 *
 * 失败时 .part 当场删掉，重探一遍目录照样「能写、没报错」—— 原来卡片立刻回到灰字
 * 「这个目录里还没有备份」，失败原因只在 6 秒的 toast 里。所以挂着，直到**之后真备上了一份**：
 * 再点一次成功了（调用方直接清），或者重探时最新那份已经不是失败那一刻看到的那份（每小时那次自动备份成了）。
 * lastName ＝ 失败那一刻卡片上最新那份的名字（一份都没有是 null；状态还没取到、不知道是 undefined ——
 * 那就没法认「之后备上了」，只等再点一次成功）
 */
export function failureStands(lastName: string | null | undefined, st: Pick<BackupStatus, 'last_name'>): boolean {
  return lastName === undefined || st.last_name === null || st.last_name === lastName
}
