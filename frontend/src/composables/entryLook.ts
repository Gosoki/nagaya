/**
 * 一笔账在列表里长什么样：分类、颜色、图标、名字。流水页和账单页的明细共用这一份。
 *
 * 原来两边各写一套，已经分叉过一处：账单页那份少了转账的图标。它的列表恰好把转账
 * 滤掉了，所以界面上看不出来 —— 看不出来的分叉才最容易越走越远。
 * 「帮买」（付款人不担、全算一个别人的支出，见 core/helpBuy）也在这儿认：琥珀色、购物袋、「替 Kan 买」。
 */
import { useI18n } from 'vue-i18n'

import type { Entry } from 'src/api/types'
import { helpBuyFor } from 'src/core/helpBuy'
import { FALLBACK } from 'src/palette'
import { useMeta } from 'src/stores/meta'
import { KIND_COLOR } from 'src/theme'

export function useEntryLook() {
  const meta = useMeta()
  const { t } = useI18n()

  // 用含归档的反查表：归档过的分类，它名下的历史账目也要能显示原来的名字和图标
  const categoryOf = (e: Entry) => (e.category_id === null ? undefined : meta.categoryById[e.category_id])
  const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)
  /** 帮谁买的（不是帮买就是 null）。帮买在记一笔那屏是转账页里的开关，所以颜色跟转账走 */
  const helpedOf = (e: Entry) => helpBuyFor(e, categoryOf(e)?.monthly === true)
  // 收入、转账没有分类，得有自己的图标色，否则跟「分类丢了」长得一模一样
  const colorOf = (e: Entry) =>
    helpedOf(e) !== null
      ? KIND_COLOR.settlement
      : e.kind === 'expense' ? (categoryOf(e)?.color ?? FALLBACK) : KIND_COLOR[e.kind]
  const iconOf = (e: Entry) =>
    helpedOf(e) !== null
      ? 'shopping_bag'
      : e.kind === 'settlement' ? 'swap_horiz' : e.kind === 'income' ? 'savings' : (categoryOf(e)?.icon ?? 'receipt_long')
  /** 名字：自己写的备注 → 「替 Kan 买」→ 分类名 → 类型名 */
  const labelOf = (e: Entry) => {
    const helped = helpedOf(e)
    return (
      e.title ||
      (helped !== null ? t('entry.helpBuyFor', { name: nameOf(helped) }) : '') ||
      categoryOf(e)?.name ||
      t(`kind.${e.kind}`)
    )
  }
  /** 流水那一行的小字：「Go 替 Kan 买」。不是帮买就是空串，调用方照原样写付款人和分摊 */
  const helpCaptionOf = (e: Entry) => {
    const helped = helpedOf(e)
    return helped === null ? '' : t('entry.helpBy', { payer: nameOf(e.payer_id), name: nameOf(helped) })
  }

  return { categoryOf, colorOf, iconOf, labelOf, helpCaptionOf }
}
