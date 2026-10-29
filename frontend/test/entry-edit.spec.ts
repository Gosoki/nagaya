/**
 * 改一笔账的两条路（core/entryEdit，审计 R28）：
 *   * 账单页「出账后被改过」「待核对」里点固定费，去那张单子的固定费那一屏，不进单笔编辑页；
 *   * 单笔编辑页撞上量级闸（409 amount_jump）：问一句，确认了带着 confirm_jump 再发 —— 原来只有一句红字、没有确认的路。
 */
import { describe, expect, it } from 'vitest'

import { ApiError } from '../src/api/client'
import { editRoute, sendConfirmingJump } from '../src/core/entryEdit'

describe('点一条账去哪一屏改', () => {
  it('固定费：已出的单子去那一张的固定费面板，草稿去本期那一屏', () => {
    expect(editRoute(38, true, 5)).toEqual({ name: 'monthly', params: { statementId: '5' } })
    expect(editRoute(38, true, null)).toEqual({ name: 'monthly' })
  })

  it('日常的账：单笔编辑页', () => {
    expect(editRoute(41, false, 5)).toEqual({ name: 'entry-edit', params: { id: '41' } })
  })
})

describe('单笔编辑页撞上量级闸', () => {
  const jump = new ApiError('amount_jump', '差了好几倍', { ratio: 4.5, direction: 'up' }, 409)

  it('人确认了：带着 confirm_jump 再发一次，存上', async () => {
    const sent: object[] = []
    const asked: unknown[] = []
    const got = await sendConfirmingJump(
      async (extra) => {
        sent.push(extra)
        if (!extra.confirm_jump) throw jump
        return 'saved'
      },
      async (j) => {
        asked.push(j)
        return true
      },
    )
    expect(got).toBe('saved')
    expect(sent).toEqual([{}, { confirm_jump: true }])
    expect(asked, '问的时候带上后端给的倍数和方向').toEqual([{ ratio: 4.5, direction: 'up' }])
  })

  it('人选「回去改」：什么都不再发，返回 null（不报红字）', async () => {
    let calls = 0
    const got = await sendConfirmingJump(
      async () => {
        calls += 1
        throw jump
      },
      async () => false,
    )
    expect(got).toBeNull()
    expect(calls).toBe(1)
  })

  it('别的错（版本冲突之类）原样抛，不问', async () => {
    const conflict = new ApiError('version_conflict', 'x', {}, 409)
    let asked = false
    await expect(
      sendConfirmingJump(
        async () => {
          throw conflict
        },
        async () => (asked = true),
      ),
    ).rejects.toBe(conflict)
    expect(asked).toBe(false)
  })
})
