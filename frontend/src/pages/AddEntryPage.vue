<!--
  记一笔 —— PWA 打开的默认页（D16），也是整个 app 最该快的一屏。

  验收标准（SPEC §7.4）：常见场景 ≤ 3 次点击 + 1 次输入。
  金额 → 分类 → 保存，付款人和分摊默认折叠着，不展开也能存。
-->
<template>
  <q-page class="page">
    <!-- 编辑模式：顶上一条返回 + 这笔在哪张账单上。
         「已出账也能改」这件事必须当场说清楚差额去哪了，否则没人敢按保存 -->
    <div v-if="editingId !== null" class="page-head">
      <q-btn dense flat round icon="arrow_back" @click="goBack" />
      <div class="col text-weight-medium">{{ t('entry.editTitle') }}</div>
    </div>
    <!-- 位置和高度跟账单那页的页签一致，但选中的是**实心色块**不是下划线：
         选错记账类型的代价比选错账单页签大得多，值得给更硬的提示 -->
    <q-btn-toggle
      v-model="kind"
      spread no-caps unelevated
      :toggle-color="kindPalette"
      class="kind-toggle"
      :options="[
        { label: t('kind.expense'), value: 'expense' },
        { label: t('kind.income'), value: 'income' },
        { label: t('kind.settlement'), value: 'settlement' },
      ]"
    />

    <!-- 备注和日期摆在最上面：它们是「这笔是什么、哪天的」，
         先交代清楚再填钱，比夹在中间容易被忽略强 -->
    <div class="q-px-md">
      <div class="row items-center q-gutter-sm field top-field">
        <q-input
          v-model="title"
          dense borderless
          class="col"
          :placeholder="t('entry.title')"
          maxlength="40"
        />
        <q-btn dense flat no-caps icon="event" :label="dateLabel" class="text-grey-7 date-btn">
          <q-popup-proxy cover transition-show="scale">
            <div>
              <q-date v-model="date" mask="YYYY-MM-DD" today-btn minimal :options="dateAllowed" />
              <!-- 已出过账的日期选不了：那张单子锁着，记进去也不会出现在上面，
                   只会让人以为补上了。要补记就写在备注里 -->
              <div v-if="minDate && editingId === null" class="text-caption text-grey-7 q-pa-sm date-hint">
                {{ t('entry.dateLocked', { date: minDate }) }}
              </div>
            </div>
          </q-popup-proxy>
        </q-btn>
      </div>
    </div>

    <!-- 「这笔已经出过账」的提示贴着金额放：改动最可能发生在金额上，
         提示离得越近越有用。原来顶在最上面，滚一下就看不见了 -->
    <q-banner v-if="billedLabel" dense class="bg-blue-1 text-blue-9 edit-note">
      {{ t('entry.editBilled', { label: billedLabel }) }}
    </q-banner>

    <AmountInput ref="amountEl" v-model="amount" :color="kindInk" />

    <!-- 分类：大色块网格，一点即选。只有支出分类；收入和转账都没有 -->
    <div
      v-if="kind === 'expense'"
      class="cat-grid"
      :style="{ gridTemplateColumns: `repeat(${Math.min(4, gridCategories.length)}, 1fr)` }"
    >
      <button
        v-for="c in gridCategories"
        :key="c.id"
        class="cat"
        type="button"
        :aria-pressed="categoryId === c.id"
        :class="{ on: categoryId === c.id }"
        :style="catStyle(c)"
        @click="pickCategory(c.id)"
      >
        <q-icon :name="c.icon" size="22px" :style="{ color: catIcon(c) }" />
        <span>{{ c.name }}</span>
      </button>
    </div>

    <!-- **指个路。** 这一屏只放日常分类（房租水电煤网有自己那一屏），
         可屏幕上从来没说过这件事 —— 照着任务走一遍的那一路，第一步
         「这个月电费填进去」就在这儿愣住了，最自然的结果是记成「其他」，
         而那笔钱既进不了固定费面板，下个月还会照着灰色占位再填一次 -->
    <button v-if="kind === 'expense'" class="fixed-hint" type="button" @click="goFixed">
      {{ t('entry.fixedCostHint') }}
      <q-icon name="chevron_right" size="16px" />
    </button>

    <div class="q-px-md">
      <!-- 谁付的 / 转给谁 / 备注 三行统一行高，中间拉细分隔线 ——
           原来它们各自飘着，看上去像三段无关的文字，不像一个表单 -->
      <div class="fields">
      <div class="row items-center field">
        <div class="col-auto text-grey-7 label">
          {{ kind === 'income' ? t('entry.receiver') : t('entry.payer') }}
        </div>
        <q-space />
        <MemberPicker v-model="payerId" :members="meta.activeMembersSelfFirst" />
      </div>

      <div v-if="kind === 'settlement'" class="row items-center field">
        <div class="col-auto text-grey-7 label">{{ t('entry.to') }}</div>
        <q-space />
        <MemberPicker v-model="toMemberId" :members="meta.activeMembersSelfFirst.filter((m) => m.id !== payerId)" />
      </div>

      </div>

      <!-- 不做折叠：日常网格只剩三个按钮之后竖向空间够用，
           每人分多少一直摆在那儿，比藏在一个要点开的抽屉里踏实。
           折起来的那个抽屉还带个没用的摘要行（「Go / Kan / Zen」），白占一行 -->
      <div v-if="kind !== 'settlement'" class="q-mt-sm split-panel">
        <SplitEditor
          ref="splitEl"
          :amount="signedAmount"
          :members="splitMembers"
          :payer-id="payerId"
          :color="kindPalette"
          :seed-rule="ownRule ?? selectedCategoryRule"
          :entry-id="editingId"
          @change="onSplitChange"
        />
      </div>
    </div>

    <!-- 主操作在拇指区；合计对不上时差额就摆在按钮正上方，不用滚回去找 -->
    <div class="actions">
      <div v-if="splitDiff !== 0 && amount > 0" class="diff-line text-negative">
        {{ t('split.notBalanced', { n: formatYen(splitDiff) }) }}
      </div>
      <div class="row">
      <q-btn
        class="col"
        :color="kindPalette"
        size="lg"
        no-caps
        unelevated
        :disable="!canSave"
        :loading="busy"
        :label="editingId === null ? t('entry.record') : t('entry.save')"
        @click="editingId === null ? save() : saveEdit()"
      />
      <q-btn
        v-if="editingId !== null"
        class="col-auto q-ml-sm"
        color="negative"
        size="lg"
        no-caps
        outline
        icon="delete"
        :label="t('common.delete')"
        @click="removeEntry"
      />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import { inkOn, tint } from 'src/color'
import { jstDateOf, todayJst } from 'src/date'
import { formatYen } from 'src/i18n'
import type { Entry, EntryKind } from 'src/api/types'
import AmountInput from 'src/components/AmountInput.vue'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { useAuth } from 'src/stores/auth'
import { KIND_COLOR, KIND_PALETTE } from 'src/theme'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()
const drafts = useDrafts()

const kind = ref<EntryKind>('expense')
const amount = ref(0)
const categoryId = ref<number | null>(null)
const payerId = ref<number | null>(null)
const toMemberId = ref<number | null>(null)
const title = ref('')
const date = ref(todayJst())
const busy = ref(false)

/** 路由带了 id ＝ 在改一笔已经记下的账（已出账的也算）。空 ＝ 记新的一笔 */
const editingId = computed(() => (route.params.id ? Number(route.params.id) : null))
const version = ref(0)
const billedLabel = ref<string | null>(null)
/** 改的时候分摊要从**这笔自己的规则**起步，不是分类默认值 —— 否则一打开就被改回默认 */
const ownRule = ref<Record<string, unknown> | null>(null)
/**
 * 这笔账**落库时**那条规则和 kind。和 ownRule 分开存：ownRule 会被「换分类」清掉，
 * 而后端算参与人时看的是 entry.split_rule_json，换不换分类都照看不误。
 * 只用 ownRule 的话，「改日期 ＋ 换分类」会再次和后端对不上。
 */
const loadedRule = ref<Record<string, unknown> | null>(null)
const loadedKind = ref<EntryKind | null>(null)

const rule = ref<Record<string, unknown> | null>(null)
const splitValid = ref(true)
const splitDiff = ref(0)
/**
 * 分类格子的配色。
 *
 * 未选中给**它自己颜色的淡底**，不是灰底也不是全透明：
 *   * 全透明（原来那样）＝ 看不出能点。三个方向的评审、以及照着任务走一遍的
 *     那一路，全都在这儿卡住过 —— 屏幕上那就是三行说明文字。
 *   * 灰底 ＝ 一排空盒子（这也是原来那条注释拒绝铺底的理由，它没说错）。
 * 淡底既说得出是哪一类，又看得出能点，而且和选中态是同一形状的两级。
 */
type Swatch = { id: number; color: string }
const catStyle = (c: Swatch) =>
  categoryId.value === c.id
    ? { background: c.color, color: inkOn(c.color) }
    : { background: tint(c.color) }
const catIcon = (c: Swatch) => (categoryId.value === c.id ? inkOn(c.color) : c.color)

/** 去固定费那一屏。带上「从哪儿来的」不需要 —— 那屏自己会回到账单页 */
const goFixed = () => router.push({ name: 'monthly' })

const amountEl = ref<InstanceType<typeof AmountInput> | null>(null)
const splitEl = ref<InstanceType<typeof SplitEditor> | null>(null)

/**
 * 网格里**只放日常分类**。
 *
 * 固定费（房租/电费/燃气/水费/网费）不在这儿填 —— 它们有自己那一屏，
 * 而且账目里点一条固定费也是跳去那一屏，根本到不了这个编辑页。
 * 摆在这儿只会让人以为「在这儿也能记房租」，记出来的那笔还落不进固定费面板。
 *
 * 唯一的例外是这笔账本来就归某个不在网格里的分类（比如直接输地址进来改一笔
 * 房租）：那就把它自己那一格补上，否则网格里一个选中的都没有，像是分类丢了。
 */
const gridCategories = computed(() => {
  const daily = meta.dailyCategories
  const own = categoryId.value === null ? undefined : meta.categoryById[categoryId.value]
  return own && !daily.some((c) => c.id === own.id) ? [...daily, own] : daily
})

/** 支出蓝 / 收入绿 / 转账黄 —— 金额、主按钮、段选中态都跟着它走，
    一眼就知道自己在记哪种账，不用回头看顶上选中的是哪个 */
/**
 * 从「转账」切成支出/收入时，把这笔账原来的规则丢掉。
 *
 * 转账落库的规则是 `{"mode":"exact","exact":{转入人: 全额}}`。拿它当分摊基准，
 * SplitEditor 会把它换算成「全额挂在原转入人头上」的调整额 —— 屏幕上写着
 * A ¥0 / B ¥1,000 / C ¥0，合计对得上、还是绿的。直接存 → 后端按均分存，
 * 和刚才看到的不是一回事；在面板上碰一下 → 那条换算规则真被上传，B 凭空多担 667 円。
 * 后端本来就防着这件事（update_entry 里 `inheritable = prev_kind != settlement`），
 * 是前端把这道防线绕开的，这里把同一条规矩镜像一遍。
 */
watch(kind, (now, before) => {
  if (before === 'settlement' && now !== 'settlement') {
    ownRule.value = null
    loadedRule.value = null
  }
})

const kindPalette = computed(() => KIND_PALETTE[kind.value])
const kindInk = computed(() => KIND_COLOR[kind.value])

/** 收入在库里存负数（SPEC §5）；界面上只让人填正数，符号这里加 */
const signedAmount = computed(() => (kind.value === 'income' ? -amount.value : amount.value))

/** 上次出账那天（含）之前的日期不给选 */
/**
 * 分摊面板的参与人。**必须是 computed 而不是模板里直接调 meta.membersOn(date)**：
 * 那样每次渲染都返回一个新数组，prop 身份一直在变，SplitEditor 里那个
 * watch(() => props.members) 会不停地把用户刚调好的比例重置回默认
 */
const splitMembers = computed(() => {
  // **改一笔账时不按新日期重挑参与人。** 后端明写着「改日期不该换人」
  // （update_entry 的 from_entry 那一支），预览要是跟着日期走，只要这笔账原来的
  // 参与人里有谁不在新日期当天在籍的名单里（改日期跨过某人的入住日、或者事后
  // 补填了谁的搬出日），屏幕上就比落库少分一个人 —— 而合计照样等于总额，
  // balanced 是绿的，一点提示都没有
  if (editingId.value !== null && loadedRule.value && loadedKind.value !== 'settlement') {
    const ids = Object.keys(
      (loadedRule.value.exact as Record<string, unknown>) ??
        (loadedRule.value.weights as Record<string, unknown>) ??
        {},
    ).map(Number)
    const rows = ids.map((id) => meta.byId[id]).filter(Boolean)
    if (rows.length) return [...rows].sort((a, b) => a.display_order - b.display_order || a.id - b.id)
  }
  return meta.membersOn(date.value)
})

const minDate = computed(() => (ledger.prevCutAt ? jstDateOf(ledger.prevCutAt) : null))
// 只有**新记**的账才限日期：新的一笔不管写哪天都落进当前草稿，选回已出账的范围
// 只会让人以为补进了那张单子。改已有的账不受这条约束 —— 它归哪张单子由
// statement_id 定死，改日期不会让它换单子
const dateAllowed = (d: string) =>
  editingId.value !== null || !minDate.value || d.replace(/\//g, '-') >= minDate.value

const dateLabel = computed(() => {
  const today = todayJst()
  return date.value === today ? t('common.today') : date.value.slice(5)
})

const canSave = computed(
  () =>
    amount.value > 0 &&
    payerId.value !== null &&
    splitValid.value &&
    // 分类不再是硬门槛：没选但写了备注就记「其他」，两个都没有时按保存会弹框问。
    // 收入本来就没有分类（返现、給付金套不上「日用品/伙食」，写备注更清楚）。
    (kind.value !== 'settlement' || (toMemberId.value !== null && toMemberId.value !== payerId.value)),
)

/** 选中分类的默认分摊规则，交给编辑器当初始值 —— 否则预览和实际存下去的不是一回事 */
const selectedCategoryRule = computed(
  () =>
    (meta.categories.find((c) => c.id === categoryId.value)?.default_rule_json as
      | Record<string, unknown>
      | null
      | undefined) ?? null,
)

onMounted(async () => {
  if (editingId.value !== null) {
    await loadForEdit(editingId.value)
    return
  }
  payerId.value = meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null
  // 「PWA 一打开就是记一笔，启动即光标就位」（router 里那条 D16）——
  // 这句规矩一直写在注释里，但从来没落地过：focus() 只在保存后的 reset 里调过。
  // iOS 上没有用户手势时不会真的弹键盘，所以这一下只是把光标放好，不挡屏幕
  amountEl.value?.focus()
})

/** 正在编辑的那一笔的原样。删除要用它 —— ledger.remove 靠它决定刷哪几份缓存 */
const loaded = ref<Entry | null>(null)

async function loadForEdit(id: number) {
  try {
    const e = await api.get<Entry>(`/api/entries/${id}`)
    loaded.value = e
    kind.value = e.kind
    amount.value = Math.abs(e.amount_jpy)
    categoryId.value = e.category_id
    payerId.value = e.payer_id
    toMemberId.value = e.to_member_id
    title.value = e.title
    date.value = e.date
    version.value = e.version
    ownRule.value = e.split_rule_json
    loadedRule.value = e.split_rule_json
    loadedKind.value = e.kind
    billedLabel.value = e.statement_label
  } catch (err) {
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err) })
    goBack()
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else void router.push({ name: 'entries' })
}

async function saveEdit() {
  if (!canSave.value || payerId.value === null || editingId.value === null) return
  if (!(await ensureCategory())) return
  busy.value = true
  try {
    await ledger.update(editingId.value, version.value, {
      kind: kind.value,
      date: date.value,
      amount_jpy: signedAmount.value,
      payer_id: payerId.value,
      to_member_id: kind.value === 'settlement' ? toMemberId.value : null,
      category_id: kind.value === 'expense' ? categoryId.value : null,
      title: title.value,
      rule: kind.value === 'settlement' ? null : rule.value,
    })
    await ledger.refresh()
    $q.notify({ type: 'positive', message: t('entry.saved'), timeout: 1200 })
    goBack()
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: e instanceof ApiError ? e.text : String(e),
      timeout: 4000,
    })
  } finally {
    busy.value = false
  }
}

/**
 * 删掉这一笔。
 *
 * 两处以前是缺的：
 *   * **失败没有任何提示** —— 回调裸着一个 await，断网或者这笔刚被别人删掉时
 *     对话框关掉、页面不动，用户只会反复点；
 *   * **删完没有撤销** —— 后端一直是软删（`POST /entries/{id}/restore` 早就在那儿），
 *     可前端从没接过这个入口。对比一下：删掉一个**固定费项目**（只是归档一个分类）
 *     反而给了 6 秒撤销，而删掉一笔真金白银的账没有后悔药，轻重正好反了。
 */
function removeEntry() {
  if (editingId.value === null) return
  const id = editingId.value
  const entry = loaded.value
  $q.dialog({ title: t('common.delete'), message: t('entry.deleteConfirm'), cancel: true }).onOk(
    async () => {
      try {
        // 走 store 而不是直接 DELETE：**「写完要刷哪几份缓存」只该有一处定义**。
        // 自己打接口的话账单缓存一份都不刷 —— 账目页少了一笔，账单页还挂着它，
        // 连复制进 LINE 的那段文字都带着。撤销那一支走的一直是 store，一正一反
        if (entry) await ledger.remove(entry)
        else await api.del(`/api/entries/${id}`)
      } catch (e) {
        $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
        return
      }
      await ledger.refresh().catch(() => {})
      // 先弹再走。直接用地址打开这一屏时（刷新、PWA 快捷方式），goBack() 会跨文档，
      // 整页一重载这条撤销就没了 —— 而它正是这次删除唯一的后悔药
      $q.notify({
        type: 'positive',
        message: t('entry.deleted'),
        timeout: 6000,
        actions: [
          {
            label: t('common.undo'),
            color: 'white',
            handler: async () => {
              try {
                await ledger.restore(id)
                await ledger.refresh().catch(() => {})
                $q.notify({ type: 'positive', message: t('entry.restored'), timeout: 1500 })
              } catch (e) {
                $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
              }
            },
          },
        ],
      })
      goBack()
    },
  )
}
watch(
  () => meta.settings.length,
  () => {
    if (payerId.value === null) {
      payerId.value = meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null
    }
  },
)

function pickCategory(id: number) {
  categoryId.value = categoryId.value === id ? null : id
  ownRule.value = null       // 换了分类就用新分类的默认分摊，跟记新账时一致
}

function onSplitChange(next: Record<string, unknown> | null, valid: boolean, diff: number) {
  rule.value = next
  splitValid.value = valid
  splitDiff.value = diff
}

/** 兜底分类（默认「其他」）。哪一个由设置说了算，代码里不写死名字 */
const fallbackCategoryId = computed(() => meta.setting<number | null>('fallback_category_id', null))

/**
 * 支出没选分类时怎么办。
 *
 * 写了备注就记进「其他」—— 备注已经说清这笔是什么了，再逼人点一下分类是多余的。
 * 两样都没有就弹框问：这种账过三个月自己都认不出来，不该让它这么进库。
 * 弹框里填了备注就直接存，想选分类就取消回去点。
 */
async function ensureCategory(): Promise<boolean> {
  if (kind.value !== 'expense' || categoryId.value !== null) return true
  if (!title.value.trim()) {
    const typed = await new Promise<string | null>((resolve) => {
      $q.dialog({
        title: t('entry.needLabel'),
        message: t('entry.needLabelHint'),
        prompt: { model: '', type: 'text', maxlength: 40 },
        cancel: true,
      })
        .onOk((v: string) => resolve(v))
        .onCancel(() => resolve(null))
    })
    if (typed === null || !typed.trim()) return false
    title.value = typed.trim()
  }
  categoryId.value = fallbackCategoryId.value
  return categoryId.value !== null
}

async function save() {
  if (!canSave.value || payerId.value === null) return
  if (!(await ensureCategory())) return
  busy.value = true
  const payload = {
      kind: kind.value,
      date: date.value,
      amount_jpy: signedAmount.value,
      payer_id: payerId.value,
      to_member_id: kind.value === 'settlement' ? toMemberId.value : null,
      category_id: kind.value === 'expense' ? categoryId.value : null,
      title: title.value,
      rule: kind.value === 'settlement' ? null : rule.value,
  }
  try {
    await ledger.create(payload)
    $q.notify({ type: 'positive', message: t('entry.saved'), timeout: 1200 })
    reset()
  } catch (e) {
    // 只有「连不上服务器」才转存草稿。金额方向错、账期已关这类是**服务器明确拒绝**，
    // 存成草稿只会让人以后反复补交同一笔失败的账（D15）
    if (e instanceof ApiError && e.code === 'network') {
      drafts.add(payload)
      $q.notify({ type: 'warning', message: t('draft.savedOffline'), timeout: 2500 })
      reset()
    } else {
      $q.notify({
        type: 'negative',
        message: e instanceof ApiError ? e.text : String(e),
        timeout: 4000,
      })
    }
  } finally {
    busy.value = false
  }
}

/**
 * 记完留在原页：清掉金额、备注、分摊，**分类留着**，光标回金额框。
 * 超市小票一串日用品可以连着录；要换分类点一下就行，不必先清空。
 */
function reset() {
  amount.value = 0
  title.value = ''
  rule.value = null
  splitEl.value?.reset()
  amountEl.value?.focus()
}
</script>

<style scoped>
.edit-note {
  margin: 0 16px 4px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}
.page {
  /* 底部有两层：固定操作栏（约 64px）压在底部 Tab（50px）之上。
     留够位置，否则最后一个人那一行会被操作栏盖住。 */
  padding-bottom: calc(var(--nagaya-footer-h) + 90px + env(safe-area-inset-bottom));
}
.kind-toggle { border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
/* 顶到屏幕边缘的东西不做圆角：首尾两段默认带 3px，贴着边看就是两个豁口。
   高度对齐底部 Tab 那一栏（57px）—— 默认的 37px 上轻下重，不像个 app */
.kind-toggle :deep(.q-btn) {
  border-radius: 0;
  min-height: var(--nagaya-head-h);
  font-size: 16px;
}
.label { font-size: 14px; }

.fields { border-top: 1px solid rgba(0, 0, 0, 0.06); }
/* 提到金额上面的那一行：上面紧挨着页签那条线了，自己只留下边线 */
.top-field { border-bottom: 1px solid rgba(0, 0, 0, 0.06); }
.field {
  min-height: 52px;                       /* 三行一样高，拇指点哪一行都一样 */
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}
.fields .field:last-child { border-bottom: none; }
.split-panel { padding-top: 4px; }

.cat-grid {
  display: grid;
  /* 列数在模板里按分类数算，最多 4 列。写死 4 列的话分类不足 4 个时
     右边会空出一格，整排偏左，看着像上面的金额没居中 */
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 6px 16px 10px;
}
.cat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 64px;                      /* 大色块，一点即中，不用瞄 */
  /* 底色由 catStyle() 按分类色算：未选中是它自己的淡底，选中是实心。
     不铺**灰**底那条老规矩仍然成立（一排灰盒子确实难看），但「什么都不铺」
     的代价更大 —— 未选中的格子看不出能点 */
  border: none;
  border-radius: var(--nagaya-r-md);
  color: var(--nagaya-ink);
  font-size: var(--nagaya-fs-meta);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
/* 选中态的字色由 catStyle() 给（深色分类配白字、浅色配黑字） */


/* 指路那一行：看着像条链接，不抢分类格子的戏 */
.fixed-hint {
  display: flex;
  align-items: center;
  gap: 2px;
  margin: 8px auto 0;
  padding: 8px 12px;
  min-height: 44px;
  border: none;
  background: transparent;
  color: var(--nagaya-ink-2);
  font-size: var(--nagaya-fs-meta);
  cursor: pointer;
}

.actions :deep(.q-btn) { min-height: 44px; }
.date-hint { max-width: 290px; border-top: 1px solid rgba(0, 0, 0, 0.08); }
.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(var(--nagaya-footer-h) + env(safe-area-inset-bottom));   /* 压在底部 Tab 之上 */
  padding: 6px 16px 8px;
  /* 不用半透明：内容从按钮底下透出来会看着像渲染坏了 */
  background: #fff;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
/* 操作栏本身横贯到底（那条上边线要通），但里面的按钮跟页面一样收窄居中 */
.actions > * {
  max-width: var(--nagaya-max-w);
  margin-left: auto;
  margin-right: auto;
}
.diff-line {
  font-size: 12px;
  text-align: center;
  padding-bottom: 4px;
}
</style>
