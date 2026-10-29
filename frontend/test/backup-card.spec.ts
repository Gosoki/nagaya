/**
 * 设置页「备份」那一块（core/backupCard）：红点拿这一屏的状态现算（审计 R17），
 * 手点「立即备份」失败的那句挂到之后真备上一份为止（审计 R11）。
 */
import { describe, expect, it } from 'vitest'

import { alertOf, failureStands } from '../src/core/backupCard'

describe('红点：和后端 backup.alert 同一条规则', () => {
  const ok = { error: null, every_hours: 24, last_at: '2026-10-29T03:00:00', stale: false }

  it('status 报的错都算', () => {
    expect(alertOf({ ...ok, error: 'backup_not_writable' })).toBe('backup_not_writable')
  })

  it('自动备份开着、有过备份、太久没出新的：backup_stale', () => {
    expect(alertOf({ ...ok, stale: true })).toBe('backup_stale')
  })

  it('一份都还没有、自动备份自己关了：不亮（否则红点常亮，真出事那天没人当回事）', () => {
    expect(alertOf({ ...ok, last_at: null, stale: true })).toBeNull()
    expect(alertOf({ ...ok, every_hours: 0, stale: true })).toBeNull()
    expect(alertOf(ok)).toBeNull()
  })
})

describe('手点「立即备份」失败的那句', () => {
  it('重探之后目录照样「没报错」、还是一份都没有：接着挂（原来卡片立刻回到灰字）', () => {
    expect(failureStands(null, { last_name: null })).toBe(true)
  })

  it('最新那份还是失败那一刻看到的那份：接着挂', () => {
    expect(failureStands('nagaya-20261028-030000.db', { last_name: 'nagaya-20261028-030000.db' })).toBe(true)
  })

  it('点的时候状态还没取到（不知道最新那份是哪个）：重探认不出「之后备上了」，只等再点一次成功', () => {
    expect(failureStands(undefined, { last_name: 'nagaya-20261028-030000.db' })).toBe(true)
  })

  it('重探时一份都没了（目录被改了、被清了）：之后并没有备上过，接着挂', () => {
    expect(failureStands('nagaya-20261028-030000.db', { last_name: null })).toBe(true)
  })

  it('之后真备上了一份（每小时那次自动备份成了）：撤掉', () => {
    expect(failureStands(null, { last_name: 'nagaya-20261029-040000.db' })).toBe(false)
    expect(failureStands('nagaya-20261028-030000.db', { last_name: 'nagaya-20261029-040000.db' })).toBe(false)
  })
})
