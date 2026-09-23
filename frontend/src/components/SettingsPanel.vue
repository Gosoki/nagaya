<!--
  设置 —— 「更多」里的第二页（第一页是流水）。

  **完全按后端的 settings_spec 渲染**：类型、取值范围、中日文说明都是接口给的，
  这里只负责把它们摆成控件。加一条新设置不用回来改这个文件 ——
  规矩本来就定了「词表/阈值一律进数据库 + 面板可改」，这一屏是那句话欠着的另一半。
-->
<template>
  <div>
    <ProfileCard />
    <AppearanceCard />
    <MembersCard />
    <FixedCostSettings />
    <!-- 系统设置默认收起来：这些是「定一次就不再动」的规矩，
         而这一页天天要来的是上面的个人设置。摊开着只会把它挤到屏幕外 -->
    <div class="bill-section">
      <q-item clickable dense class="section-head" @click="open = !open">
        <q-item-section>{{ t('settings.system') }}</q-item-section>
        <q-item-section
          v-if="open"
          side
          class="text-caption"
          :class="failed ? 'text-negative' : 'text-grey-6'"
        >
          <div class="row items-center">
            <q-spinner v-if="busy" size="14px" class="q-mr-xs" />
            {{ busy ? t('monthly.saving') : failed ? t('monthly.unsaved', { n: failed }) : t('monthly.autoSaved') }}
          </div>
        </q-item-section>
        <q-item-section v-else side class="text-caption text-grey-6">
          {{ t('settings.count', { n: rows.length }) }}
        </q-item-section>
        <q-item-section side>
          <q-icon :name="open ? 'expand_less' : 'expand_more'" color="grey-5" size="20px" />
        </q-item-section>
      </q-item>

      <q-list v-if="open" separator>
        <q-item v-for="s in rows" :key="s.key" class="setting-row" :data-key="s.key">
          <q-item-section>
            <q-item-label class="row items-center no-wrap">
              <div class="col">{{ labelOf(s.key) }}</div>

              <!-- 开关 -->
              <q-toggle
                v-if="s.type === 'bool'"
                dense
                :model-value="s.value === true"
                @update:model-value="(v: boolean) => save(s, v)"
              />
              <!-- 几选一 -->
              <q-btn
                v-else-if="s.type === 'enum'"
                dense flat no-caps color="primary" icon-right="arrow_drop_down"
                :label="optionLabel(String(s.value))"
              >
                <q-menu auto-close>
                  <q-list style="min-width: 150px">
                    <q-item
                      v-for="o in s.options ?? []"
                      :key="String(o)"
                      clickable
                      @click="save(s, o)"
                    >
                      <q-item-section>{{ optionLabel(String(o)) }}</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
              <!-- 挑一个人 -->
              <q-btn
                v-else-if="s.type === 'member_id_or_null'"
                dense flat no-caps icon-right="arrow_drop_down"
                :color="gone(s.value) ? 'negative' : 'primary'"
                :label="memberLabel(s.value)"
              >
                <q-menu auto-close>
                  <q-list style="min-width: 150px">
                    <q-item clickable @click="save(s, null)">
                      <q-item-section>{{ t('settings.none') }}</q-item-section>
                    </q-item>
                    <q-item
                      v-for="m in meta.activeMembers"
                      :key="m.id"
                      clickable
                      @click="save(s, m.id)"
                    >
                      <q-item-section>{{ m.display_name }}</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
              <!-- 挑一个分类（键名点明了它是分类，别当成普通数字） -->
              <q-btn
                v-else-if="s.key.endsWith('_category_id')"
                dense flat no-caps color="primary" icon-right="arrow_drop_down"
                :label="categoryLabel(s.value)"
              >
                <q-menu auto-close>
                  <q-list style="min-width: 150px">
                    <q-item clickable @click="save(s, null)">
                      <q-item-section>{{ t('settings.noneCategory') }}</q-item-section>
                    </q-item>
                    <q-item
                      v-for="c in meta.dailyCategories"
                      :key="c.id"
                      clickable
                      @click="save(s, c.id)"
                    >
                      <q-item-section>{{ c.name }}</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
              <!-- 整数 -->
              <input
                v-else-if="s.type === 'int' || s.type === 'int_or_null'"
                class="num"
                type="text"
                inputmode="numeric"
                :value="s.value === null ? '' : String(s.value)"
                @blur="saveNumber(s, $event.target as HTMLInputElement)"
              />
              <!-- 一行文字 -->
              <input
                v-else-if="s.type === 'str'"
                class="text"
                type="text"
                :value="String(s.value ?? '')"
                @blur="save(s, ($event.target as HTMLInputElement).value)"
              />
              <!-- 一行一个的列表：输入框在下面整行铺开，这儿不再重复一遍 -->
              <div v-else-if="s.type === 'string_list'" class="text-caption text-grey-6">
                {{ t('settings.listHint') }}
              </div>
              <!-- 分摊规则：手机上编 JSON 太难用，先只读 -->
              <div v-else class="text-caption text-grey-7">{{ ruleText(s.value) }}</div>
            </q-item-label>

            <!-- 说明是后端写的，里面用 **…** 标着重点。原样输出的话星号会露在界面上 -->
            <q-item-label caption class="note">
              <template v-for="(part, i) in noteParts(s)" :key="i">
                <b v-if="i % 2">{{ part }}</b><template v-else>{{ part }}</template>
              </template>
            </q-item-label>
            <q-item-label v-if="s.type === 'string_list'" caption>
              <textarea
                class="list"
                rows="2"
                :value="(s.value as string[] ?? []).join('\n')"
                @blur="saveList(s, ($event.target as HTMLTextAreaElement).value)"
              />
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- 备份放最后：它是「设一次就不再动」的东西，天天要来的是上面几块 -->
    <BackupCard />

    <!-- 装的是哪一版。手机上的 PWA 换包要等 service worker 轮换，
         「改了怎么没生效」十次有九次是这儿对不上 —— 印出来就不用猜了 -->
    <div class="text-center text-caption text-grey-5 q-py-md build" @click="tapBuild">{{ build }}</div>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import { toHalfWidth } from 'src/digits'
import BackupCard from 'src/components/BackupCard.vue'
import FixedCostSettings from 'src/components/FixedCostSettings.vue'
import MembersCard from 'src/components/MembersCard.vue'
import AppearanceCard from 'src/components/AppearanceCard.vue'
import ProfileCard from 'src/components/ProfileCard.vue'
import type { Setting } from 'src/api/types'
import { useMeta } from 'src/stores/meta'

const { t, locale } = useI18n()
/** 打包时刻（日本时间），vite.config.ts 注入 —— 印在这一屏最底下 */
const build = __BUILD__

/**
 * 版本号连点 5 下：开/关布局诊断条（见 LayoutProbe）。
 * 藏得深是故意的 —— 那是给排查手机上布局问题用的，不是给人日常看的。
 * 切完整页刷新：要复现的正是「刚启动那一下」
 */
let taps = 0
let tapTimer = 0
function tapBuild() {
  taps++
  clearTimeout(tapTimer)
  tapTimer = window.setTimeout(() => (taps = 0), 1500)
  if (taps < 5) return
  taps = 0
  let on = false
  try {
    on = localStorage.getItem('nagaya.debugLayout') !== '1'
    if (on) localStorage.setItem('nagaya.debugLayout', '1')
    else localStorage.removeItem('nagaya.debugLayout')
  } catch {
    return
  }
  $q.notify({ message: on ? t('settings.debugOn') : t('settings.debugOff'), timeout: 1000 })
  setTimeout(() => location.reload(), 800)
}
const $q = useQuasar()
const meta = useMeta()

const busy = ref(false)
const failed = ref(0)
/** 默认收起。定一次就不动的东西，不该天天占着屏幕 */
const open = ref(false)

onMounted(() => {
  // meta 里已经有一份，但设置面板要的是最新的（别的手机可能刚改过）
  void meta.load().catch(() => {})
})

// hidden 的那几项有自己的卡片（App 名字和图标），通用面板里不渲染 ——
// 渲染了就等于同一个值有两个入口，改哪个都对不上
const rows = computed(() => meta.settings.filter((s) => !s.hidden))

/** 界面文案走 i18n；认不出的键就把键名本身显出来，总比空白强 */
function labelOf(key: string): string {
  const path = `settings.label.${key}`
  const got = t(path)
  return got === path ? key : got
}
function optionLabel(value: string): string {
  const path = `settings.option.${value}`
  const got = t(path)
  return got === path ? value : got
}
/**
 * 说明是后端随设置一起给的（中日双份），跟着界面语言挑一份。
 * 里面用 `**…**` 标重点，按奇偶切成「普通 / 粗体」交替的几段。
 */
const noteParts = (s: Setting) => (locale.value === 'ja' ? s.note_ja : s.note_zh).split('**')

/** 指着的人已经搬走了：标红、写明。记账那边早就不再用他（退回自己），这里得说出来 */
const gone = (v: unknown) => typeof v === 'number' && meta.byId[v] !== undefined && !meta.byId[v]!.is_active
const memberLabel = (v: unknown) =>
  typeof v === 'number'
    ? `${meta.byId[v]?.display_name ?? String(v)}${gone(v) ? t('settings.memberLeft') : ''}`
    : t('settings.none')
const categoryLabel = (v: unknown) =>
  typeof v === 'number'
    ? (meta.categoryById[v]?.name ?? String(v))
    : t('settings.noneCategory')

function ruleText(v: unknown): string {
  const rule = v as { equal_weight?: number; weights?: Record<string, number> } | null
  if (rule?.equal_weight) return t('settings.equalSplit')
  if (rule?.weights) {
    return Object.entries(rule.weights)
      .map(([id, w]) => `${meta.byId[Number(id)]?.display_name ?? id} ${w}`)
      .join(' : ')
  }
  return JSON.stringify(v)
}

async function save(s: Setting, value: unknown) {
  if (JSON.stringify(value) === JSON.stringify(s.value)) return
  busy.value = true
  try {
    const saved = await api.put<Setting>(`/api/settings/${s.key}`, { value })
    // 本地那份一起更新：meta.setting() 到处在用，不更新的话要等下次进 app 才生效
    meta.settings = meta.settings.map((x) => (x.key === s.key ? saved : x))
    failed.value = 0
  } catch (e) {
    failed.value += 1
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  } finally {
    busy.value = false
  }
}

/**
 * 数字框失焦就存。**认不出是数就不存、框里退回原值** —— 原来全角数字或者
 * 一串字母会被 `replace(/[^\d-]/g, '')` 洗成空串，`Number('')` 是 0，
 * 于是「备份间隔」这种设置悄悄变成了 0。存失败时也退回原值：
 * 框里留着一个没生效的数，看着就像存上了
 */
async function saveNumber(s: Setting, el: HTMLInputElement) {
  const text = toHalfWidth(el.value).replace(/[,\s]/g, '')
  // 按**当前**那份重画：存成功后 meta 里换成了新对象，手上这个 s 还是旧值
  const shown = () => {
    const now = meta.settings.find((x) => x.key === s.key)?.value ?? null
    el.value = now === null ? '' : String(now)
  }
  if (!text) {
    if (s.type === 'int_or_null') await save(s, null)
    shown()
    return
  }
  if (!/^-?\d+$/.test(text)) {
    shown()
    return
  }
  await save(s, Number(text))
  shown()
}

function saveList(s: Setting, raw: string) {
  void save(
    s,
    raw.split('\n').map((x) => x.trim()).filter(Boolean),
  )
}
</script>

<style scoped>
.setting-row { padding-top: 8px; padding-bottom: 8px; }
.note { font-size: 12px; line-height: 1.5; }
.num,
.text,
.list {
  border: none;
  border-radius: var(--nagaya-r-sm);
  outline: none;
  background: var(--nagaya-fill);
  font: inherit;
  font-size: 16px;            /* 低于 16px iOS 会在聚焦时放大整页（原来写着这句、值却是 15） */
  color: inherit;
  padding: 0 10px;
}
.num,
.text { height: 36px; }
.num:focus,
.text:focus,
.list:focus { box-shadow: inset 0 0 0 1.5px var(--nagaya-accent); }
.num { width: 72px; text-align: right; }
.text { width: 150px; text-align: right; }
.list {
  width: 100%;
  resize: none;
  padding: 8px 10px;
  margin-top: 6px;
}
</style>
