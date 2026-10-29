/**
 * 「已记下 · 日用 ¥1,234」那条提示，带「撤销」。记一笔那屏和离线草稿补交（DraftBanner）共用这一份。
 *
 * **说清记的是哪一笔，并给一次后悔的机会。** 原来只有一句「已记下」、1.2 秒就没了：
 * 连着录一串小票时，点错分类、多打一个 0，要翻去流水里找出来再删。
 * 草稿补交原来也只有一句「已记下」：凭记忆重记过一遍的那笔再盲交上去就是两笔，当场看不出来。
 *
 * **付款人不是自己时把他写出来**（D5：设了默认垫付人，别人三下记完的账默认算成他付的），
 * 转账一律写方向 —— 要紧的是谁给谁，「已记下 · 转账 ¥5,000」看不出记反了没有。
 * 撤销走的是软删（和编辑页的删除同一条路），流水和账单缓存一并刷新
 */
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

import { errorText } from 'src/api/client'
import type { Entry } from 'src/api/types'
import { useEntryLook } from 'src/composables/entryLook'
import { formatYen } from 'src/i18n'
import { useAuth } from 'src/stores/auth'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

export function useSavedNotice() {
  const $q = useQuasar()
  const { t } = useI18n()
  const auth = useAuth()
  const meta = useMeta()
  const ledger = useLedger()
  const { labelOf } = useEntryLook()

  const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)

  /** 名字后面那半句：转账写方向，别人付的支出写「Go 付」、别人收的收入写「Go 收」，自己的不写 */
  function whoOf(e: Entry): string {
    if (e.kind === 'settlement') {
      return e.to_member_id === null ? '' : t('entry.savedDirection', { from: nameOf(e.payer_id), to: nameOf(e.to_member_id) })
    }
    if (e.payer_id === auth.me?.id) return ''
    const name = nameOf(e.payer_id)
    return e.kind === 'income' ? t('entry.savedReceiver', { name }) : t('entry.savedPayer', { name })
  }

  function notifySaved(saved: Entry): void {
    // 和流水同一套名字：备注 → 「替 Kan 买」→ 分类 → 类型
    const what = labelOf(saved)
    $q.notify({
      type: 'positive',
      message: t('entry.savedWhat', { what, amount: formatYen(Math.abs(saved.amount_jpy)) }) + whoOf(saved),
      timeout: 3500,
      actions: [
        {
          label: t('common.undo'),
          color: 'white',
          handler: async () => {
            try {
              await ledger.remove(saved)
              $q.notify({ type: 'info', message: t('entry.undone'), timeout: 1500 })
            } catch (e) {
              $q.notify({ type: 'negative', message: errorText(e) })
            }
          },
        },
      ],
    })
  }

  return { notifySaved }
}
