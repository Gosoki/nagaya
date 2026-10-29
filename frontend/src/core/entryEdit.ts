/**
 * 改一笔账时的两条路（审计 R28）：固定费去哪一屏改、单笔编辑页撞上量级闸怎么问。
 * 抽出来是为了写得了单测（test/entry-edit.spec.ts）—— 写在 SFC 里 import 不到。
 */
import { ApiError } from 'src/api/client'

export type EditRoute =
  | { name: 'monthly'; params?: { statementId: string } }
  | { name: 'entry-edit'; params: { id: string } }

/**
 * 账单页点一条账去改它，去哪一屏（BillView.editEntry；账目页 EntriesPage.openEntry 是同一条规则）。
 *
 * **固定费走那张单子的固定费那一屏**：「出账后被改过」「待核对」两张列表都会列固定费，
 * 进了单笔编辑页撞上量级闸（和上期差出好几倍）原来只有一句红字、没有确认的路。
 * 草稿（statementId 为 null）去本期那一屏
 */
export function editRoute(id: number, monthly: boolean, statementId: number | null): EditRoute {
  if (!monthly) return { name: 'entry-edit', params: { id: String(id) } }
  return statementId === null ? { name: 'monthly' } : { name: 'monthly', params: { statementId: String(statementId) } }
}

/**
 * 发一次改动；撞上量级闸（409 amount_jump）就问人一句，人确认了带着 confirm_jump 再发一次。
 * 返回 null ＝ 人选了「回去改」，什么都没写。别的错原样抛（版本冲突由调用方接）。
 * 单笔编辑页用（AddEntryPage.saveEdit）：直接输地址进来改一笔房租会撞上它 ——
 * 原来只有一句「确认一下是不是多打或少打了一个 0」，这一页上没有确认的路，真就是这么多的金额存不进去
 */
export async function sendConfirmingJump<T>(
  send: (extra: { confirm_jump?: true }) => Promise<T>,
  ask: (jump: { ratio?: unknown; direction?: unknown }) => Promise<boolean>,
): Promise<T | null> {
  try {
    return await send({})
  } catch (e) {
    if (!(e instanceof ApiError && e.code === 'amount_jump')) throw e
    if (!(await ask(e.detail))) return null
    return send({ confirm_jump: true })
  }
}
