<!--
  成员 —— 谁住在这儿、哪天搬进来、哪天搬走；新来的人从这儿加。

  分摊按「那笔账当天在籍的人」算，所以入住日和搬走日就是分摊名单本身。
  **谁都能改别人的这两项**：这是家务动作不是自助动作 —— 人搬走之后多半不会再打开
  这个 app，只许本人改的话谁也标不掉他，之后每笔账都照样算他一份
  （后端 members.update_member 有同一段话）。
  登录名和密码只能本人改，这里不给入口；登录名也不列出来（个人设置里写着「只有自己看得到」）。
-->
<template>
  <div class="bill-section">
    <q-item clickable dense class="section-head" @click="open = !open">
      <q-item-section>{{ t('members.title') }}</q-item-section>
      <q-item-section side class="text-caption text-grey-6">
        {{ t('members.count', { n: meta.activeMembers.length }) }}
      </q-item-section>
      <q-item-section side>
        <q-icon :name="open ? 'expand_less' : 'expand_more'" color="grey-5" size="20px" />
      </q-item-section>
    </q-item>

    <template v-if="open">
      <q-list separator>
        <q-item v-for="m in meta.members" :key="m.id" class="member-row" :data-name="m.display_name">
          <q-item-section avatar>
            <MemberAvatar :member-id="m.id" size="36px" :class="{ gone: !m.is_active }" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="row items-center no-wrap">
              <div class="col ellipsis">{{ m.display_name }}</div>
              <span v-if="statusOf(m)" class="tag">{{ statusOf(m) }}</span>
            </q-item-label>
            <div class="row items-center no-wrap q-mt-xs dates">
              <!-- 入住日 -->
              <q-btn dense flat no-caps size="sm" color="grey-7" class="date-btn" :label="t('members.joined', { date: ymd(m.joined_on) })">
                <q-popup-proxy
                  cover transition-show="scale"
                  :model-value="pop === `j${m.id}`"
                  @update:model-value="(v: boolean) => (pop = v ? `j${m.id}` : null)"
                >
                  <q-date
                    :model-value="m.joined_on"
                    mask="YYYY-MM-DD" minimal today-btn no-unset
                    :options="(d: string) => !m.left_on || d <= slash(m.left_on)"
                    @update:model-value="(d: string | null) => d && pickJoined(m, d)"
                  />
                </q-popup-proxy>
              </q-btn>
              <!-- 搬走日：没填＝还住着，按钮是「标记搬走」；填了就显示日期，点开能改、能撤 -->
              <q-btn
                dense flat no-caps size="sm" class="date-btn"
                :color="m.left_on ? 'warning' : 'grey-6'"
                :icon="m.left_on ? undefined : 'logout'"
                :label="m.left_on ? t('members.left', { date: ymd(m.left_on) }) : t('members.markLeft')"
              >
                <q-popup-proxy
                  cover transition-show="scale"
                  :model-value="pop === `l${m.id}`"
                  @update:model-value="(v: boolean) => (pop = v ? `l${m.id}` : null)"
                >
                  <div class="date-pop">
                    <!-- 还没填搬走日时**什么都不预选**：预选今天的话，点今天是「取消选择」，
                         「今天搬走」这个最常见的情况反而标不上 -->
                    <q-date
                      :model-value="m.left_on"
                      mask="YYYY-MM-DD" minimal today-btn no-unset
                      :options="(d: string) => d >= slash(m.joined_on)"
                      @update:model-value="(d: string | null) => d && pickLeft(m, d)"
                    />
                    <div v-if="m.left_on" class="q-pa-sm pop-foot">
                      <q-btn dense flat no-caps color="primary" :label="t('members.stillHere')" @click="undoLeft(m)" />
                    </div>
                  </div>
                </q-popup-proxy>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div class="text-caption text-grey-6 q-px-md q-py-sm hint">{{ t('members.hint') }}</div>

      <!-- 加一个人。初始密码明文显示：加的人要把它念给新室友听 -->
      <button v-if="!adding" class="add-row row items-center no-wrap" @click="startAdd">
        <q-icon name="person_add" size="18px" class="q-mr-sm" />
        {{ t('members.add') }}
      </button>
      <div v-else class="add-form q-px-md q-py-sm">
        <label class="form-row row items-center no-wrap">
          <span class="col">{{ t('members.displayName') }}</span>
          <input v-model="form.display_name" class="field" type="text" maxlength="20" />
        </label>
        <label class="form-row row items-center no-wrap">
          <span class="col">{{ t('members.loginName') }}</span>
          <input v-model="form.name" class="field" type="text" maxlength="20" autocapitalize="off" autocomplete="off" />
        </label>
        <label class="form-row row items-center no-wrap">
          <span class="col">{{ t('members.password') }}</span>
          <input v-model="form.password" class="field" type="text" autocapitalize="off" autocomplete="off" />
        </label>
        <div class="form-row row items-center no-wrap">
          <span class="col">{{ t('members.joinedOn') }}</span>
          <q-btn dense flat no-caps color="primary" icon="event" :label="ymd(form.joined_on)">
            <q-popup-proxy
              cover transition-show="scale"
              :model-value="pop === 'new'"
              @update:model-value="(v: boolean) => (pop = v ? 'new' : null)"
            >
              <q-date
                :model-value="form.joined_on"
                mask="YYYY-MM-DD" minimal today-btn no-unset
                @update:model-value="(d: string | null) => { if (d) form.joined_on = d; pop = null }"
              />
            </q-popup-proxy>
          </q-btn>
        </div>
        <div class="row justify-end q-gutter-sm q-mt-xs">
          <q-btn dense flat no-caps color="grey-7" :label="t('common.cancel')" @click="adding = false" />
          <q-btn
            dense unelevated no-caps color="primary"
            :disable="!canCreate"
            :loading="busy"
            :label="t('members.create')"
            @click="create"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import type { Member } from 'src/api/types'
import MemberAvatar from 'src/components/MemberAvatar.vue'
import { todayJst } from 'src/date'
import { useAuth } from 'src/stores/auth'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const auth = useAuth()

const open = ref(false)
/** 哪个日期弹层开着（同一时刻只开一个） */
const pop = ref<string | null>(null)

/** 2026-09-01 → 2026/9/1 */
const ymd = (d: string) => d.replace(/^(\d+)-0?(\d+)-0?(\d+)$/, '$1/$2/$3')
/** q-date 的 options 拿到的是 2026/09/01 这种写法。搬走日不能早于入住日（后端也拦） */
const slash = (d: string) => d.replace(/-/g, '/')

/** 行尾那个小标签：只有「今天不算在住」的人才有 */
function statusOf(m: Member): string {
  if (m.is_active) return ''
  return m.joined_on > todayJst() ? t('members.notYet') : t('members.leftTag')
}

async function save(m: Member, patch: Record<string, unknown>): Promise<boolean> {
  try {
    const saved = await api.patch<Member>(`/api/members/${m.id}`, patch)
    meta.members = meta.members.map((x) => (x.id === saved.id ? saved : x))
    if (auth.me?.id === saved.id) auth.me = saved
    // 在籍名单变了：谁付的、分摊、默认垫付人全跟着它走，整份重取
    await meta.load().catch(() => {})
    return true
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
    return false
  }
}

function pickJoined(m: Member, d: string) {
  pop.value = null
  if (d !== m.joined_on) void save(m, { joined_on: d })
}

/**
 * 标记搬走（或者改搬走日）。**第一次标要确认**：这一下之后新记的账就不算他一份了。
 * 改一个已经填了的日期不再问 —— 那是在纠正，不是在做决定
 */
function pickLeft(m: Member, d: string) {
  pop.value = null
  if (d === m.left_on) return
  if (m.left_on) {
    void save(m, { left_on: d })
    return
  }
  $q.dialog({
    title: t('members.leaveTitle', { name: m.display_name }),
    message: t('members.leaveConfirm', { name: m.display_name, date: ymd(d) }),
    cancel: true,
    ok: { label: t('members.markLeft'), color: 'warning', flat: true },
  }).onOk(() => void save(m, { left_on: d }))
}

function undoLeft(m: Member) {
  pop.value = null
  void save(m, { left_on: null })
}

const adding = ref(false)
const busy = ref(false)
const form = reactive({ display_name: '', name: '', password: '', joined_on: todayJst() })
/** 和个人设置里改密码同一个下限（后端 MIN_PASSWORD_LEN） */
const MIN_PASSWORD = 6
const canCreate = computed(
  () => form.display_name.trim() && form.name.trim() && form.password.length >= MIN_PASSWORD,
)

function startAdd() {
  Object.assign(form, { display_name: '', name: '', password: '', joined_on: todayJst() })
  adding.value = true
}

async function create() {
  if (!canCreate.value || busy.value) return
  busy.value = true
  try {
    const made = await api.post<Member>('/api/members', {
      display_name: form.display_name.trim(),
      name: form.name.trim(),
      password: form.password,
      joined_on: form.joined_on,
    })
    await meta.load().catch(() => {})
    adding.value = false
    $q.notify({
      type: 'positive',
      timeout: 0,
      multiLine: true,
      message: t('members.added', { name: made.display_name, login: made.name }),
      actions: [{ label: t('common.confirm'), color: 'white' }],
    })
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.member-row { padding-top: 10px; padding-bottom: 10px; }
.gone { opacity: 0.45; }
.tag {
  font-size: var(--nagaya-fs-meta);
  color: var(--nagaya-ink-3);
  background: var(--nagaya-fill);
  border-radius: var(--nagaya-r-pill);
  padding: 1px 8px;
  margin-left: 8px;
}
/* 两个日期按钮贴着名字左缘：flat 按钮自带的左内边距让它们看起来缩进了一格 */
.dates { margin-left: -2px; gap: 4px; }
.date-btn :deep(.q-btn__content) { font-size: var(--nagaya-fs-label); font-weight: 400; }
/* dense 的小按钮只有 26px 高：点击区上下各伸 8px，排版不变 */
.date-btn::after { content: ''; position: absolute; inset: -8px 0; }
.date-pop { overflow: hidden; background: var(--nagaya-surface-2); }
.date-pop :deep(.q-date) { box-shadow: none; border-radius: 0; }
.pop-foot { border-top: 1px solid var(--nagaya-line); text-align: center; }
.hint { border-top: 1px solid var(--nagaya-line); }
.add-row {
  width: 100%;
  min-height: var(--nagaya-add-row-h);
  padding: 0 16px;
  border: none;
  border-top: 1px solid var(--nagaya-line);
  background: none;
  font: inherit;
  color: var(--nagaya-accent);
  cursor: pointer;
}
.add-form { border-top: 1px solid var(--nagaya-line); }
.form-row { min-height: 44px; }
.field {
  height: 36px;
  border: none;
  border-radius: var(--nagaya-r-sm);
  outline: none;
  background: var(--nagaya-fill);
  font: inherit;
  font-size: 16px;           /* 16 是 iOS 的底线：再小一点，聚焦时整页会被放大 */
  color: inherit;
  padding: 0 10px;
  text-align: right;
  width: 170px;
}
.field:focus { box-shadow: inset 0 0 0 1.5px var(--nagaya-accent); }
</style>
