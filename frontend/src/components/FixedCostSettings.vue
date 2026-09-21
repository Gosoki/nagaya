<!--
  固定费的设置 —— 管的是**这份清单本身**，不是这一期填多少钱。

  每期填多少在账单那页的固定费面板；这里定的是：有哪几项、各自谁垫、
  哪几项每期金额都一样。
-->
<template>
  <div class="bill-section">
    <q-item dense class="section-head">
      <q-item-section>{{ t('monthly.settingsTitle') }}</q-item-section>
      <q-item-section side class="text-caption text-grey-6">
        {{ t('settings.count', { n: items.length }) }}
      </q-item-section>
    </q-item>

    <q-list separator>
      <q-item v-for="c in items" :key="c.id" class="fixed-row" :data-name="c.name">
        <q-item-section avatar>
          <q-avatar size="30px" :style="{ background: c.color }" text-color="white">
            <q-icon :name="c.icon" size="16px" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <input
              class="name col"
              type="text"
              maxlength="20"
              :value="c.name"
              @blur="rename(c, ($event.target as HTMLInputElement).value)"
            />
            <q-btn
              dense flat round size="sm" icon="delete_outline" color="grey-6"
              :aria-label="t('monthly.removeItem')"
              @click="remove(c)"
            />
          </q-item-label>
          <q-item-label class="row items-center no-wrap q-mt-xs">
            <div class="text-caption text-grey-6">{{ t('entry.payer') }}</div>
            <q-btn
              dense flat no-caps size="sm" color="primary" icon-right="arrow_drop_down"
              :label="payerLabel(c)"
            >
              <q-menu auto-close>
                <q-list style="min-width: 140px">
                  <q-item clickable @click="save(c, { default_payer_id: null })">
                    <q-item-section>{{ t('settings.none') }}</q-item-section>
                  </q-item>
                  <q-item
                    v-for="m in meta.activeMembers"
                    :key="m.id"
                    clickable
                    @click="save(c, { default_payer_id: m.id })"
                  >
                    <q-item-section>{{ m.display_name }}</q-item-section>
                  </q-item>
                </q-list>
              </q-menu>
            </q-btn>
            <q-space />
            <div class="text-caption text-grey-6 q-mr-xs">{{ t('monthly.sameAsLast') }}</div>
            <q-toggle
              dense
              :model-value="c.same_as_last"
              @update:model-value="(v: boolean) => save(c, { same_as_last: v })"
            />
          </q-item-label>
        </q-item-section>
      </q-item>
    </q-list>

    <!-- 「和上期一样」是那条硬规矩唯一的出口，得把代价说清楚 -->
    <div class="text-caption text-grey-6 q-px-md q-pt-sm">{{ t('monthly.sameAsLastHint') }}</div>

    <div class="row items-center q-px-md q-py-sm add-row">
      <q-icon name="add" size="18px" class="text-grey-6 q-mr-sm" />
      <input
        v-model="newName"
        class="new-name col"
        type="text"
        maxlength="20"
        :placeholder="t('monthly.addPlaceholder')"
        @keyup.enter="add"
      />
      <q-btn
        dense flat no-caps color="primary"
        :disable="!newName.trim()"
        :loading="adding"
        :label="t('monthly.addItem')"
        @click="add"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import type { Category } from 'src/api/types'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()

const newName = ref('')
const adding = ref(false)

const items = computed(() => meta.monthlyCategories)
const payerLabel = (c: Category) =>
  c.default_payer_id === null
    ? t('settings.none')
    : (meta.byId[c.default_payer_id]?.display_name ?? String(c.default_payer_id))

async function save(c: Category, patch: Record<string, unknown>) {
  try {
    const saved = await api.patch<Category>(`/api/categories/${c.id}`, patch)
    meta.categories = meta.categories.map((x) => (x.id === saved.id ? saved : x))
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  }
}

function rename(c: Category, raw: string) {
  const name = raw.trim()
  if (!name || name === c.name) return
  void save(c, { name })
}

async function add() {
  const name = newName.value.trim()
  if (!name || adding.value) return
  adding.value = true
  try {
    await api.post('/api/categories', {
      name,
      monthly: true,
      display_order: 100 + items.value.length,
    })
    newName.value = ''
    await meta.load()
    $q.notify({ type: 'positive', message: t('monthly.added'), timeout: 2000 })
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
  } finally {
    adding.value = false
  }
}

/**
 * 删掉一项 —— **归档，不是真删**：它名下的历史账目还要显示原来的名字。
 * 给一次撤销的机会，误删一项的代价不该是「去数据库里捞」。
 */
function remove(c: Category) {
  $q.dialog({
    title: t('monthly.removeItem'),
    message: t('monthly.removeConfirm', { name: c.name }),
    cancel: true,
  }).onOk(async () => {
    await save(c, { archived: true })
    await meta.load()
    $q.notify({
      type: 'positive',
      message: t('monthly.removed', { name: c.name }),
      timeout: 6000,
      actions: [
        {
          label: t('common.undo'),
          color: 'white',
          handler: async () => {
            await api.patch(`/api/categories/${c.id}`, { archived: false })
            await meta.load()
          },
        },
      ],
    })
  })
}
</script>

<style scoped>
.fixed-row { padding-top: 8px; padding-bottom: 8px; }
.name,
.new-name {
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 14px;
  padding: 0;
  color: inherit;
}
.new-name { padding: 6px 0; }
.new-name::placeholder { color: #bbb; }
.add-row { border-top: 1px solid rgba(0, 0, 0, 0.06); min-height: var(--nagaya-fee-foot-h); }
</style>
