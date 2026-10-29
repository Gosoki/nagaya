<!-- 没提交的草稿横幅。压在页面顶部，点一下补交；点开看是哪几笔，单条也丢得掉。 -->
<template>
  <!-- 颜色和离线那条细带同一套（--nagaya-warn*）：原来是琥珀底白字，对比度 2.6:1，
       太阳底下看不清；深色模式下也不跟着变 -->
  <q-banner v-if="drafts.count" dense class="draft-banner">
    <template #avatar>
      <q-icon name="cloud_off" />
    </template>
    <!-- 只写「有 N 笔没提交」的话，人判断不了这几笔是什么：凭记忆在别处重记过一遍的那笔，
         再盲点「补交」就是两笔。点这一句展开，逐条看得见 -->
    <button class="draft-toggle" type="button" :aria-expanded="open" @click="open = !open">
      {{ t('draft.pending', { n: drafts.count }) }}
      <q-icon :name="open ? 'expand_less' : 'expand_more'" size="18px" />
    </button>
    <template #action>
      <q-btn flat dense no-caps :loading="busy" :label="t('draft.submit')" @click="submit" />
      <q-btn flat dense no-caps :disable="busy" :label="t('draft.discard')" @click="discard" />
    </template>
  </q-banner>
  <!-- 展开的清单：每条一行（存的日期、是什么、多少钱、谁付的），各自丢得掉。
       不给单条补交：「补交」本来就是逐条交、成一条删一条 -->
  <div v-if="drafts.count && open" class="draft-list">
    <div v-for="d in drafts.mine" :key="d.id" class="draft-row row items-center no-wrap">
      <div class="col ellipsis">{{ describe(d) }}</div>
      <q-btn
        flat dense round size="sm" icon="delete_outline"
        :disable="busy"
        :aria-label="t('draft.discardOne')"
        @click="discardOne(d)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSavedNotice } from 'src/composables/savedNotice'
import { jstDateOf } from 'src/date'
import { escapeHtml } from 'src/html'
import { formatYen } from 'src/i18n'
import { statementLabel } from 'src/statement'
import { type Draft, useDrafts } from 'src/stores/drafts'
import { useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const drafts = useDrafts()
const ledger = useLedger()
const meta = useMeta()
const bills = useBills()
const { notifySaved } = useSavedNotice()
const busy = ref(false)
const open = ref(false)

/**
 * 一条草稿长什么样：存的那天、是什么（帮买 / 分类 / 备注 / 类型）、多少钱、谁付的（转账写谁 → 谁）。
 * 草稿是还没进库的请求体，没有 shares，所以不走流水那套 labelOf
 */
function describe(d: Draft): string {
  const p = d.payload
  const name = (id: number | null | undefined) => (id == null ? '' : (meta.byId[id]?.display_name ?? String(id)))
  // 帮买存下去是一笔只算一个人的支出（AddEntryPage 的 helpBuyBody：member_ids 只有那个人）
  const helped = p.kind === 'expense' && p.member_ids?.length === 1 && p.member_ids[0] !== p.payer_id
    ? p.member_ids[0]!
    : null
  const what =
    p.title ||
    (helped !== null ? t('entry.helpBuyFor', { name: name(helped) }) : '') ||
    (p.category_id != null ? meta.categoryById[p.category_id]?.name : '') ||
    t(`kind.${p.kind}`)
  const who = p.kind === 'settlement' ? `${name(p.payer_id)} → ${name(p.to_member_id)}` : name(p.payer_id)
  return t('draft.item', { date: p.date.slice(5), what, amount: formatYen(Math.abs(p.amount_jpy)), who })
}

async function submit() {
  busy.value = true
  try {
    const { ok, offline, rejected, saved } = await drafts.submitAll()
    if (ok) await ledger.refresh().catch(() => {})
    // 被后端明确拒绝的，把它那句话原样说出来 —— 那条草稿会一直卡在这儿，
    // 而「连不上服务器」既是错的，也不告诉人该去改哪儿
    if (rejected.length) {
      // 一行一条，还要说清是几条。Quasar 的 message 是纯文本节点，`\n` 在 HTML 里
      // 折叠成一个空格 —— 几句原因于是挤成一长串，看不出是几笔、哪笔。
      // 同一个原因的多条草稿也别重复说，数出来更清楚
      const times = new Map<string, number>()
      for (const text of rejected) times.set(text, (times.get(text) ?? 0) + 1)
      $q.notify({
        type: 'negative',
        timeout: 8000,
        multiLine: true,
        html: true,
        message: [...times]
          .map(([text, n]) => escapeHtml(n > 1 ? t('draft.rejectedTimes', { text, n }) : text))
          .join('<br>'),
      })
    } else if (offline) {
      $q.notify({ type: 'negative', message: t('errors.network') })
    }
    // **交上去的每一笔都说出来，带撤销**（和记一笔那屏同一条提示）：原来只有一句「已记下」，
    // 凭记忆重记过一遍的那笔盲交上去就是两笔，当场看不出来
    for (const e of saved) notifySaved(e)
    // 离线期间有人出了账：日期在那之前的这几笔，进的是**当前这张草稿**，不是那张已经出了的。
    // 照实说一句，不改日期、不拦。比的是刚刷新过的「上次出账」（上面 ledger.refresh 刚取过），
    // 用离线时手里那份旧值会漏报。响应丢在路上、其实出账前就记上了的那种已经在那张单子里
    // （statement_id 不空），不算
    const cut = ledger.prevCutAt ? jstDateOf(ledger.prevCutAt) : null
    if (cut && saved.some((e) => e.statement_id === null && e.date < cut)) {
      const label = statementLabel(bills.statements?.[0]) || cut
      $q.notify({ type: 'info', timeout: 8000, message: t('draft.beforeCut', { label }) })
    }
  } finally {
    busy.value = false
  }
}

/** 全部丢弃：确认框里逐行列出要丢的每一笔 —— 那是真填过的钱，丢之前得看清是哪几笔 */
function discard() {
  $q.dialog({
    title: t('draft.discard'),
    message: [t('draft.pending', { n: drafts.count }), ...drafts.mine.map(describe)].map(escapeHtml).join('<br>'),
    html: true,
    cancel: true,
  }).onOk(() => drafts.clear())
}

/** 丢一笔：确认框里写清是哪一笔 */
function discardOne(d: Draft) {
  $q.dialog({ title: t('draft.discardOne'), message: describe(d), cancel: true })
    .onOk(() => drafts.remove(d.id))
}
</script>

<style scoped>
/* 安全区由顶栏统一让（MainLayout），这里再让一次就是让两遍 */
.draft-banner {
  background: var(--nagaya-warn-bg);
  color: var(--nagaya-warn);
}
.draft-banner :deep(.q-btn) { color: var(--nagaya-warn); font-weight: 600; }
/* 横幅上那句话本身就是展开的开关：看着还是那一行字，旁边多一个小箭头 */
.draft-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
}
/* 展开的清单也在顶栏里：草稿多的时候别把整屏顶下去，自己滚 */
.draft-list {
  max-height: 40vh;
  overflow-y: auto;
  padding: 0 8px 6px 16px;
  background: var(--nagaya-warn-bg);
  color: var(--nagaya-warn);
  font-size: var(--nagaya-fs-meta);
}
.draft-row { min-height: 32px; }
.draft-row :deep(.q-btn) { color: var(--nagaya-warn); }
</style>
