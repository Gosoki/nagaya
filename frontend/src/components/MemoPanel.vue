<!--
  备忘 —— 账目页的第二页。

  装的是**不随某一笔账走**的事：水费隔月收、网费合同哪天到期、备用钥匙在哪。
  这些写进某一笔的备注里，下个月就找不着了。

  分两块：
    * 固定费那几项是一份现成的清单，直接摆出来，各带一条常驻备注（存在分类上）
    * 清单之外的自己加（存在 memo 表里）

  没有保存按钮 —— 和固定费面板一个规矩：离开输入框就存。
-->
<template>
  <div ref="root">
    <div class="bill-section">
      <q-item dense class="section-head">
        <q-item-section>{{ t('memo.fixed') }}</q-item-section>
        <q-item-section side class="text-caption" :class="failed ? 'text-negative' : 'text-grey-6'">
          <div class="row items-center">
            <q-spinner v-if="busy" size="14px" class="q-mr-xs" />
            {{ busy ? t('monthly.saving') : failed ? t('monthly.unsaved', { n: failed }) : t('monthly.autoSaved') }}
          </div>
        </q-item-section>
      </q-item>

      <q-list separator>
        <q-item v-for="c in meta.monthlyCategories" :key="c.id" class="memo-row">
          <q-item-section avatar>
            <q-avatar size="30px" :style="{ background: c.color }" text-color="white">
              <q-icon :name="c.icon" size="16px" />
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <!-- 这一屏只管备注，不出现金额 —— 钱在账单那边，
                 同一个数在两处显示，迟早有一天对不上 -->
            <q-item-label>{{ c.name }}</q-item-label>
            <textarea
              class="note"
              rows="1"
              :value="c.note"
              :placeholder="t('memo.notePlaceholder')"
              @input="grow"
              @blur="saveCategory(c, ($event.target as HTMLTextAreaElement).value)"
            />
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <div class="bill-section">
      <q-item dense class="section-head">
        <q-item-section>{{ t('memo.others') }}</q-item-section>
      </q-item>

      <q-list v-if="memos.items.length" separator>
        <!-- data-title 是 E2E 的锚点：名字在输入框里，按文本内容找不到这一行 -->
        <q-item v-for="m in memos.items" :key="m.id" class="memo-row" :data-title="m.title">
          <q-item-section>
            <q-item-label class="row items-center no-wrap">
              <input
                class="memo-title col"
                :value="m.title"
                :placeholder="t('memo.namePlaceholder')"
                @blur="saveTitle(m, ($event.target as HTMLInputElement).value)"
              />
              <q-btn
                dense flat round size="sm" icon="delete_outline" color="grey-6"
                :aria-label="t('memo.removeItem')"
                @click="removeMemo(m)"
              />
            </q-item-label>
            <textarea
              class="note"
              rows="1"
              :value="m.body"
              :placeholder="t('memo.notePlaceholder')"
              @input="grow"
              @blur="saveBody(m, ($event.target as HTMLTextAreaElement).value)"
            />
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else-if="memos.loaded" class="text-caption text-grey-6 q-px-md q-pb-md">
        {{ t('memo.empty') }}
      </div>

      <div class="row items-center q-px-md q-py-sm add-row">
        <q-icon name="add" size="18px" class="text-grey-6 q-mr-sm" />
        <input
          v-model="newTitle"
          class="new-name col"
          type="text"
          maxlength="30"
          :placeholder="t('memo.namePlaceholder')"
          @keyup.enter="addMemo"
        />
        <q-btn
          dense flat no-caps color="primary"
          :disable="!newTitle.trim()"
          :loading="adding"
          :label="t('memo.addItem')"
          @click="addMemo"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import type { Category, Memo } from 'src/api/types'
import { useMemos } from 'src/stores/memos'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const memos = useMemos()

const busy = ref(false)
const failed = ref(0)
const newTitle = ref('')
const adding = ref(false)

onMounted(() => {
  void memos.load().then(sizeAll).catch(() => {})
  void sizeAll()
})
// 分类的备注是随 meta 一起来的，可能比这个组件挂载还晚
watch(() => meta.categories, sizeAll, { deep: true })

/** 一行文字就一行高，写多了自己长 —— 固定高度要么浪费半屏，要么看不全 */
const root = ref<HTMLElement | null>(null)

function size(el: HTMLTextAreaElement) {
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function grow(e: Event) {
  size(e.target as HTMLTextAreaElement)
}

/**
 * **进来时也要量一遍。**
 * 只在 input 时长高的话，页面一打开那些多行的备注全被 rows=1 截掉半截 ——
 * 而这一屏上本来就存着的内容比现打的多得多
 */
async function sizeAll() {
  await nextTick()
  root.value?.querySelectorAll('textarea').forEach((el) => size(el as HTMLTextAreaElement))
}

async function save(run: () => Promise<unknown>) {
  busy.value = true
  try {
    await run()
    failed.value = 0
  } catch (e) {
    failed.value += 1
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  } finally {
    busy.value = false
  }
}

function saveCategory(c: Category, note: string) {
  if (note === c.note) return
  void save(async () => {
    const saved = await api.patch<Category>(`/api/categories/${c.id}`, { note })
    meta.categories = meta.categories.map((x) => (x.id === c.id ? saved : x))
  })
}

function saveTitle(m: Memo, title: string) {
  if (title.trim() === m.title || !title.trim()) return
  void save(() => memos.update(m.id, { title: title.trim() }))
}

function saveBody(m: Memo, body: string) {
  if (body === m.body) return
  void save(() => memos.update(m.id, { body }))
}

async function addMemo() {
  const title = newTitle.value.trim()
  if (!title) return
  adding.value = true
  try {
    await memos.create(title)
    newTitle.value = ''
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
  } finally {
    adding.value = false
  }
}

function removeMemo(m: Memo) {
  $q.dialog({ title: t('memo.removeItem'), message: t('memo.removeAsk', { name: m.title }), cancel: true })
    .onOk(() => {
      void save(async () => {
        await memos.remove(m.id)
        $q.notify({ type: 'positive', message: t('memo.removed', { name: m.title }), timeout: 1500 })
      })
    })
}
</script>

<style scoped>
.memo-row { padding-top: 6px; padding-bottom: 6px; }
/* 备注框长得像一行字，不像个表单控件 —— 这一屏是拿来读的，不是拿来填表的 */
.note {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  overflow: hidden;
  padding: 2px 0 0;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  color: rgba(0, 0, 0, 0.6);
}
.note::placeholder { color: #c8c8c8; }
.memo-title {
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 14px;
  padding: 0;
  color: inherit;
}
.memo-title::placeholder { color: #bbb; }
.add-row { border-top: 1px solid rgba(0, 0, 0, 0.06); min-height: var(--nagaya-fee-foot-h); }
.new-name {
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  padding: 6px 0;
  color: inherit;
}
.new-name::placeholder { color: #bbb; }
</style>
