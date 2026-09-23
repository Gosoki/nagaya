<!--
  固定费的设置 —— 管的是**这份清单本身**，不是这一期填多少钱。

  每期填多少在账单那页的固定费面板；这里定的是：有哪几项、各自谁垫、
  哪几项每期金额都一样。
-->
<template>
  <div class="bill-section">
    <!-- 默认收起来：这份清单定好之后几乎不动，而设置页天天要来的是上面几块。
         摊开着有五六行，把下面的东西全挤到屏幕外 -->
    <q-item clickable dense class="section-head" @click="open = !open">
      <q-item-section>{{ t('monthly.settingsTitle') }}</q-item-section>
      <q-item-section side class="text-caption text-grey-6">
        {{ t('settings.count', { n: items.length }) }}
      </q-item-section>
      <q-item-section side>
        <q-icon :name="open ? 'expand_less' : 'expand_more'" color="grey-5" size="20px" />
      </q-item-section>
    </q-item>

    <q-list v-if="open" separator>
      <q-item v-for="c in items" :key="c.id" class="fixed-row" :data-name="c.name">
        <q-item-section avatar>
          <!-- 点图标就能换。图标和颜色摆在一个弹层里：这一格显示的就是它俩合起来的样子，
               分两处改的话要来回试 -->
          <button class="icon-btn" :aria-label="t('monthly.icon')">
            <q-avatar size="30px" :style="{ background: c.color }" text-color="white">
              <q-icon :name="c.icon" size="16px" />
            </q-avatar>
            <q-menu>
              <div class="picker q-pa-sm">
                <div class="text-caption text-grey-6 q-mb-xs">{{ t('monthly.icon') }}</div>
                <div class="icons">
                  <button
                    v-for="name in ICONS"
                    :key="name"
                    class="icon-cell"
                    :class="{ on: c.icon === name }"
                    @click="save(c, { icon: name })"
                  >
                    <q-icon :name="name" size="20px" />
                  </button>
                </div>
                <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ t('monthly.color') }}</div>
                <div class="colors">
                  <button
                    v-for="hex in CATEGORY_COLORS"
                    :key="hex"
                    class="color-cell"
                    :class="{ on: c.color.toLowerCase() === hex }"
                    :style="{ background: hex }"
                    :aria-label="hex"
                    @click="save(c, { color: hex })"
                  />
                </div>
              </div>
            </q-menu>
          </button>
        </q-item-section>
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <input
              class="name col"
              type="text"
              maxlength="20"
              :value="c.name"
              @blur="rename(c, $event.target as HTMLInputElement)"
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
              dense flat no-caps size="sm" icon-right="arrow_drop_down"
              :color="payerGone(c) ? 'negative' : 'primary'"
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

    <div v-if="open" class="row items-center q-px-md q-py-sm add-row">
      <q-icon name="add" size="18px" class="text-grey-6 q-mr-sm" />
      <input
        v-model="newName"
        class="new-name col"
        type="text"
        maxlength="20"
        :placeholder="t('monthly.addPlaceholder')"
        @keydown.enter="isSubmitEnter($event) && add()"
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
import { isSubmitEnter } from 'src/html'
import { useMeta } from 'src/stores/meta'
import { CATEGORY_COLORS } from 'src/palette'

/** 图标候选：合租里真会出现的那些项。够用就行，不做成一个图标库浏览器 */
const ICONS = [
  'home', 'bolt', 'local_fire_department', 'water_drop', 'wifi',
  'router', 'propane_tank', 'ac_unit', 'local_parking', 'directions_car',
  'tv', 'subscriptions', 'phone_iphone', 'local_laundry_service', 'cleaning_services',
  'key', 'shopping_basket', 'receipt_long',
]
const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()

const newName = ref('')
const adding = ref(false)

const items = computed(() => meta.monthlyCategories)
const open = ref(false)
/** 这一项的垫付人已经搬走：标红、写明（「和上期一样」这一项会因此停下，见 carry） */
const payerGone = (c: Category) =>
  c.default_payer_id !== null && meta.byId[c.default_payer_id]?.is_active === false
const payerLabel = (c: Category) =>
  c.default_payer_id === null
    ? t('settings.none')
    : `${meta.byId[c.default_payer_id]?.display_name ?? String(c.default_payer_id)}${payerGone(c) ? t('settings.memberLeft') : ''}`

/** 存一个字段。**成功与否要说得出来** —— 调用方靠返回值决定后面还做不做 */
async function save(c: Category, patch: Record<string, unknown>): Promise<boolean> {
  try {
    const saved = await api.patch<Category>(`/api/categories/${c.id}`, patch)
    meta.categories = meta.categories.map((x) => (x.id === saved.id ? saved : x))
    return true
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
    return false
  }
}

/** 改名。清空了、或者存不上（重名、断网），框里写回生效的那个名字 ——
 *  不然框里写着「网费」，面板和账单上它还叫「电费」 */
async function rename(c: Category, el: HTMLInputElement) {
  const name = el.value.trim()
  if (!name || name === c.name) {
    el.value = c.name
    return
  }
  if (!(await save(c, { name }))) el.value = c.name
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
    // save() 自己已经把错弹出来了。这里必须看它的脸色：原来无论成没成都照样
    // 弹一句绿色的「已删掉」，而那个撤销按钮点下去还会再静默失败一次
    if (!(await save(c, { archived: true }))) return
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
            if (await save(c, { archived: false })) await meta.load()
          },
        },
      ],
    })
  })
}
</script>

<style scoped>
.fixed-row { padding-top: 8px; padding-bottom: 8px; }
.icon-btn { border: none; background: none; padding: 0; cursor: pointer; line-height: 0; }
.picker { width: 232px; }
.icons { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
.icon-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  border: none;
  border-radius: 6px;
  background: var(--nagaya-fill);
  color: var(--nagaya-ink-2);
  cursor: pointer;
}
.icon-cell.on { background: var(--q-primary); color: #fff; }
.colors { display: flex; flex-wrap: wrap; gap: 6px; }
.color-cell {
  width: 26px;
  height: 26px;
  border-radius: 13px;
  border: none;
  padding: 0;
  cursor: pointer;
}
.color-cell.on { box-shadow: 0 0 0 2px var(--nagaya-surface) inset, 0 0 0 2px var(--nagaya-ink-2); }
.name,
.new-name {
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 16px;           /* 16 是 iOS 的底线：再小一点，聚焦时整页会被放大 */
  padding: 0;
  color: inherit;
}
.new-name { padding: 6px 0; }
.new-name::placeholder { color: var(--nagaya-ink-4); }
.add-row { border-top: 1px solid var(--nagaya-line); min-height: var(--nagaya-add-row-h); }
</style>
