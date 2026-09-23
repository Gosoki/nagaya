/**
 * 一笔账在列表里长什么样：分类、颜色、图标、名字。流水页和账单页的明细共用这一份。
 *
 * 原来两边各写一套，已经分叉过一处：账单页那份少了转账的图标。它的列表恰好把转账
 * 滤掉了，所以界面上看不出来 —— 看不出来的分叉才最容易越走越远。
 */
import { useI18n } from 'vue-i18n'

import type { Entry } from 'src/api/types'
import { FALLBACK } from 'src/palette'
import { useMeta } from 'src/stores/meta'
import { KIND_COLOR } from 'src/theme'

export function useEntryLook() {
  const meta = useMeta()
  const { t } = useI18n()

  // 用含归档的反查表：归档过的分类，它名下的历史账目也要能显示原来的名字和图标
  const categoryOf = (e: Entry) => (e.category_id === null ? undefined : meta.categoryById[e.category_id])
  // 收入、转账没有分类，得有自己的图标色，否则跟「分类丢了」长得一模一样
  const colorOf = (e: Entry) => (e.kind === 'expense' ? (categoryOf(e)?.color ?? FALLBACK) : KIND_COLOR[e.kind])
  const iconOf = (e: Entry) =>
    e.kind === 'settlement' ? 'swap_horiz' : e.kind === 'income' ? 'savings' : (categoryOf(e)?.icon ?? 'receipt_long')
  /** 名字：自己写的备注 → 分类名 → 类型名 */
  const labelOf = (e: Entry) => e.title || categoryOf(e)?.name || t(`kind.${e.kind}`)

  return { categoryOf, colorOf, iconOf, labelOf }
}
