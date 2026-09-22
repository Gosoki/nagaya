<!-- 外壳：内容在上，导航在下。
     主操作一律放屏幕下半部的拇指区（SPEC §7.4），顶部只放不常点的东西。 -->
<template>
  <q-layout view="hHh lpR fFf">
    <!-- 顶栏固定在布局上，不放进页面里：账单三页之间切换时它不该跟着卸载重建，
         切页只换中间那块内容，上下两条都不动 -->
    <!-- **永远渲染，哪怕里头一样都没有。**
         viewport-fit=cover + black-translucent ＝ 内容铺到屏幕最顶、状态栏压在上面。
         得有一个东西替所有页面把 safe-area-inset-top 占掉，而这个东西必须是
         固定定位的顶栏本身（padding 加在 body/layout 上推不动 fixed 元素）。
         没内容时它的高度就是安全区本身：非刘海机上是 0，和以前一模一样；
         刘海机上是一条白带子，正好垫在状态栏后面，黑字也才看得清。
         Quasar 会量它的实际高度去顶下面的内容，所以页面不用各自再算一遍 -->
    <q-header ref="headEl" class="bg-white text-dark">
      <DraftBanner v-if="drafts.count" />
      <!-- **断网时屏幕上的数字是旧的，这件事必须说出来。**
           账单页就是三个人掏手机转账前盯的那一屏；室友刚填了水费、刚点了
           「确认已完成」，这边一无所知，照着旧数字转钱，转错了才发现。
           一条细带子，不挡内容，但一眼看得见 -->
      <div v-if="stale" class="stale-bar row items-center no-wrap">
        <q-icon name="cloud_off" size="16px" class="q-mr-xs" />
        <div class="col ellipsis">{{ t('common.staleData') }}</div>
        <button class="stale-retry" type="button" @click="refetch">{{ t('common.retry') }}</button>
      </div>
      <BillTabs v-if="onBillTabs" />
      <EntriesTabs v-if="route.name === 'entries'" />
    </q-header>

    <q-page-container>
      <router-view v-if="meta.members.length" />
      <!-- 起不来就得说出来。原来只有一个转圈：拉不到基础数据时它会一直转下去，
           人只能看着一个永远不会停的动画 —— 而这恰好是断网时的默认下场 -->
      <div v-else-if="bootFailed" class="column flex-center q-pa-xl text-center" style="height: 60vh">
        <q-icon name="cloud_off" size="40px" color="grey-5" />
        <div class="text-grey-7 q-my-md">{{ t('common.offlineBoot') }}</div>
        <q-btn outline no-caps color="primary" :label="t('common.retry')" @click="boot" />
      </div>
      <div v-else class="column flex-center" style="height: 60vh">
        <q-spinner-dots size="40px" color="primary" />
      </div>
    </q-page-container>

    <q-footer ref="footEl" class="bg-white text-grey-8 footer-safe">
      <!-- 各页自己的固定操作条（「记入账」「出账单」）画在这儿 —— 见各页的 Teleport。
           **不再用「量底栏高度 + fixed 定位」那一套**：量早一拍（安全区还没生效、
           图标字体还没到）就会把操作条摆进底栏里，头一次进应用正好撞上这一拍。
           放进底栏之后位置由布局决定，一个数都不用量，Quasar 还会把底栏的总高
           （导航 + 这一条）算进页面的下边距，内容也不会被盖住 -->
      <div class="footer-slot" />
      <!-- 不用 q-route-tab：它的高亮跟着 vue-router 的 matched 链走，而
           /bill/current、/bill/past 是和 /bill 平级的路由、不是它的子路由，
           于是站在那两页上底栏三个 Tab 一个都不亮。
           这里改成「路由 → 所属分区」自己算，点击自己导航 -->
      <q-tabs
        :model-value="navSection"
        dense
        no-caps
        indicator-color="transparent"
        active-color="primary"
        class="text-grey-6"
      >
        <q-tab name="add" icon="add_circle" :label="t('nav.add')" @click="go('add')" />
        <q-tab name="bill" icon="receipt" :label="t('nav.bill')" @click="go('bill')" />
        <!-- 不能再用 receipt_long：和旁边「账单」的 receipt 长得几乎一样，
             三格底栏里两格一个样，只能靠位置认；而这一格底下装的是
             流水＋设置，跟「小票」也不是一回事 -->
        <q-tab name="entries" icon="format_list_bulleted" :label="t('nav.entries')" @click="go('entries')" />
      </q-tabs>
    </q-footer>
  </q-layout>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { applyAppearance } from 'src/appearance'
import { useOnline } from 'src/composables/online'
import { useMemos } from 'src/stores/memos'
import BillTabs from 'src/components/BillTabs.vue'
import EntriesTabs from 'src/components/EntriesTabs.vue'
import DraftBanner from 'src/components/DraftBanner.vue'
import { useAuth } from 'src/stores/auth'
import { useBills } from 'src/stores/bills'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const meta = useMeta()
const auth = useAuth()
const bills = useBills()
const ledger = useLedger()
const drafts = useDrafts()
const memos = useMemos()
const route = useRoute()
const router = useRouter()

/**
 * 「账单」这一格代表的是一整个分区，不只是 /bill 那一页 —— 固定费那一屏
 * 只能从账单页进去，站在那儿底栏也该亮着「账单」。
 * 新加账单相关的路由时记得加进来 —— test/nav-section.spec.ts 会盯着。
 */
const BILL_SECTION = ['bill', 'monthly']

const navSection = computed(() => {
  const name = String(route.name ?? '')
  if (BILL_SECTION.includes(name)) return 'bill'
  return name === 'entries' ? 'entries' : 'add'
})

/** 点已经亮着的那一格：回到这一分区的首页（站在首页上就什么都不做） */
function go(name: string) {
  // 账单那一节没有「首页路由」可回 —— 它两页共用一个地址。
  // 点底栏的账单＝回到最近那张，而不是停在上次翻开的某张旧账单上
  if (name === 'bill') bills.detail = null
  // 同理：点底栏的「记一笔」＝回到这一屏的起点 —— 表单那一面、类型是支出。
  // 不拨的话，人站在备忘上点这一格，路由没变、屏幕也没变（底栏成了死键），
  // 上次选的「转账」也会一直留着
  if (name === 'add') memos.goAddHome()
  if (route.name !== name) void router.push({ name })
}

/** 账单那两页才显示页签 */
const onBillTabs = computed(() => route.name === 'bill')

const bootFailed = ref(false)

async function boot() {
  bootFailed.value = false
  try {
    if (!auth.me) await auth.restore()
    await meta.load()          // 失败时它自己会回退到本地缓存
  } catch {
    bootFailed.value = true
    return
  }
  // 账本刷新失败**不该挡住界面**：离线时照样要能把这一笔填完存成草稿
  try {
    await ledger.refresh()
  } catch {
    /* 离线。草稿那条路不依赖它 */
  }
}

const online = useOnline()
/** 屏幕上的数字靠不靠得住：断网，或者最近一次取数失败了 */
const stale = computed(() => !online.value || Boolean(bills.lastError))
function refetch() {
  bills.reload(bills.tab === 'draft' ? 'draft' : 'current').catch(() => {})
  void meta.load().catch(() => {})
  void ledger.refresh().catch(() => {})
}

/**
 * 底栏到底多高，**量出来，别算**。
 *
 * 固定操作条（记一笔的「记入账」、账单的「出账单」）要正好压在底栏上沿。
 * 原来是 `calc(常数 57px + env(safe-area-inset-bottom))` —— 两处假设，
 * 任何一处不成立就会在两条之间留一道缝，而缝里会有内容滚过去：
 *   * 57 这个常数曾经写成 50，主按钮和 Tab 只隔 1px（注释里还留着这段）；
 *   * 字体放大、或者安全区在某些机型/显示模式下没算进底栏的 padding，
 *     两边对 env() 的理解就不一致了。
 * 量一次就都没有了：拿到的 height 本来就含它自己的安全区内边距。
 */
const footEl = ref<{ $el: HTMLElement } | null>(null)
const headEl = ref<{ $el: HTMLElement } | null>(null)
let footWatch: ResizeObserver | null = null
let headWatch: ResizeObserver | null = null

function measureFooter() {
  const el = footEl.value?.$el
  if (!el) return
  // **向下取整**。真实高度常常带小数（安全区一掺进来就有），四舍五入可能比真值
  // 大半像素 —— 固定操作条就被顶高那么一点，和底栏之间露出一条发丝缝，
  // 而缝里是正在滚的内容。宁可小一点：小了是压在底栏底下（它 z-index 2000，盖得住）
  const h = Math.floor(el.getBoundingClientRect().height)
  if (h > 0) document.documentElement.style.setProperty('--nagaya-footer-h', `${h}px`)
}

/**
 * 顶栏的真实高度（含刘海安全区）。它随页面变：记一笔那屏只有安全区，
 * 账单/更多那两屏还要加一条页签。
 *
 * **拿来挡键盘。** iOS 弹键盘时会把聚焦的输入框滚进可视区，而它默认会一直
 * 滚到页面最顶 —— 也就是钻到这条固定顶栏底下，金额那个大数字被切掉一截。
 * 量出来写进 --nagaya-header-h，再由 scroll-padding-top 告诉浏览器
 * 「滚到这儿就够了」。用量的不用写死：写死的话记一笔那屏会多让出一截空白。
 */
function measureHeader() {
  const el = headEl.value?.$el
  if (!el) return
  document.documentElement.style.setProperty(
    '--nagaya-header-h',
    `${Math.ceil(el.getBoundingClientRect().height)}px`,
  )
}

/**
 * **键盘弹起时把顶栏拽回可视区。**
 *
 * iOS 的规矩：`position: fixed` 钉的是**布局视口**，而键盘并不改布局视口，
 * 它让**可视视口**在里面上下滑。于是键盘一起、手指一滑，顶栏（连同那条
 * 「支出/收入/转账/备忘」）就滑出屏幕不见了 —— sticky 也一样中招，因为
 * 两者都不知道可视视口挪了。
 *
 * offsetTop 就是「可视视口在布局视口里往下挪了多少」，照着它反向平移即可。
 *
 * **只动 transform，不动 top/bottom。** 之前给底部按钮条改 bottom 那一版，
 * iOS 的键盘动画会分帧抛 resize，按钮一格格挪，卡得难看；transform 走合成器，
 * 不触发重排。rAF 合并一下，一帧最多写一次。
 */
/**
 * **手指一滑就收键盘。**
 *
 * iOS 上键盘开着时，滑动手势进行中 fixed 元素是冻住的 —— 顶栏跟一段就卡住，
 * 松手才跳回来，而 offsetTop 还有个上限（＝键盘高度），到顶之后更跟不动。
 * 这是 WebKit 的行为，JS 赢不了。
 *
 * 那就绕开：要滑动，就说明这一刻他在看下面的东西，不在打字 —— 收掉键盘，
 * 顶栏、按钮条、底下那片空白当场全部回位。很多 iOS app 就是这么做的。
 *
 * 只认**真手势**，而且要划过 8px 才算：点按钮时手指难免蹭一两像素，
 * 那种不能算成「他要滚了」。在输入框自己身上划（选字）也不算。
 */
let touchY = 0
function onTouchStart(e: TouchEvent) {
  touchY = e.touches[0]?.clientY ?? 0
}
function onTouchMove(e: TouchEvent) {
  const el = document.activeElement as HTMLElement | null
  if (!el || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA')) return
  if (e.target === el) return
  if (Math.abs((e.touches[0]?.clientY ?? 0) - touchY) < 8) return
  el.blur()
}

let vvRaf = 0
function trackHeader() {
  const vv = window.visualViewport
  const el = headEl.value?.$el
  if (!vv || !el) return
  const keyboard = window.innerHeight - vv.height - vv.offsetTop
  // 键盘没起就把 transform 摘干净：桌面/安卓上这段等于不存在
  const y = keyboard > 40 ? Math.round(vv.offsetTop) : 0
  el.style.transform = y ? `translateY(${y}px)` : ''
}
function onViewport() {
  if (vvRaf) return
  vvRaf = requestAnimationFrame(() => {
    vvRaf = 0
    trackHeader()
  })
}

/** 上下两条一起重量。两处的兜底都可能和真值差一截（安全区、图标字体） */
function remeasure() {
  measureFooter()
  measureHeader()
}

onMounted(() => {
  remeasure()
  // **多量几次。** 首帧量到的常常不是最终高度：字体（图标字体尤其）是异步到的，
  // 安全区在 standalone 下也可能晚一拍才生效 —— 量早了就把小一号的值写死在那儿。
  // ResizeObserver 只在元素自己变了才响，而「字体到了」这种变化它有时赶不上
  void (document as Document & { fonts?: FontFaceSet }).fonts?.ready.then(remeasure)
  window.addEventListener('load', remeasure)
  window.addEventListener('resize', remeasure)
  window.addEventListener('orientationchange', remeasure)
  setTimeout(remeasure, 300)

  window.visualViewport?.addEventListener('scroll', onViewport)
  window.visualViewport?.addEventListener('resize', onViewport)
  document.addEventListener('touchstart', onTouchStart, { passive: true })
  document.addEventListener('touchmove', onTouchMove, { passive: true })
  if (typeof ResizeObserver === 'undefined') return
  if (footEl.value?.$el) {
    footWatch = new ResizeObserver(measureFooter)
    footWatch.observe(footEl.value.$el)
  }
  if (headEl.value?.$el) {
    headWatch = new ResizeObserver(measureHeader)
    headWatch.observe(headEl.value.$el)
  }
})
onBeforeUnmount(() => {
  footWatch?.disconnect()
  headWatch?.disconnect()
  window.removeEventListener('load', remeasure)
  window.removeEventListener('resize', remeasure)
  window.removeEventListener('orientationchange', remeasure)
  window.visualViewport?.removeEventListener('scroll', onViewport)
  window.visualViewport?.removeEventListener('resize', onViewport)
  document.removeEventListener('touchstart', onTouchStart)
  document.removeEventListener('touchmove', onTouchMove)
  if (vvRaf) cancelAnimationFrame(vvRaf)
})

// 只有流水那页要留着弹性滚动 —— 它的下拉刷新站在「拉到顶还能再拉一截」
// 这个动作上。别的页一律关掉：键盘弹起时拉过头会露出一条藏青带（见 tokens.css）
watch(
  () => route.name,
  (name) => document.documentElement.classList.toggle('bounce-ok', name === 'entries'),
  { immediate: true },
)

// 名字和图标是这屋自己设的，而页签标题/小图/主屏清单都不是 Vue 管的 DOM，
// meta 一到手就手动贴上去（见 src/appearance.ts）
watch(
  () => [meta.setting<string>('app_name', ''), meta.setting<number>('app_icon_version', 0)] as const,
  ([name, version]) => applyAppearance(name, version),
  { immediate: true },
)

/**
 * 切回前台就重新拉一次 meta。
 *
 * App 的名字和图标是**全屋共用**的一份（存在后端的设置里），但原来只有冷启动
 * 才会去拉 —— 室友在设置里改完，另外两个人的 app 还挂在后台，切回来看到的
 * 仍是旧名字旧图标，而且可能挂上好几天。成员、分类同理。
 *
 * 只在真的回到前台时拉，失败不打扰：这一下纯属「顺手对一下表」。
 */
function onVisible() {
  if (document.visibilityState !== 'visible') return
  void meta.load().catch(() => {})
}

onMounted(() => {
  void boot()
  document.addEventListener('visibilitychange', onVisible)
})
onBeforeUnmount(() => document.removeEventListener('visibilitychange', onVisible))
</script>

<!-- 非 scoped：底栏高度给固定操作条用。
     两个页面都曾把它写死成 50px，而实际是 57px（56 tabs + 1 border），
     于是主操作按钮和 Tab 只隔 1px，拇指偏一点就点错。 -->
<style>
:root {
  /* 底栏真实高度（**含安全区**）。挂载后由 measureFooter() 量出真值写回来，
     这里是**首帧的兜底**。
     兜底值必须自己把安全区算进去：写死 57 的话，首帧那一下固定操作条会按
     57 摆，而带 home indicator 的机器上底栏是 57+34 —— 操作条整条沉到底栏
     底下，只露出一条边。「第一次进应用下面凸起来」就是它 */
  --nagaya-footer-h: calc(57px + env(safe-area-inset-bottom));
  /* 手机是主场。平板/电脑上不收一下的话，列表会被拉成「名字贴最左、
     数字贴最右」中间一片空白 —— 收到一个手机宽度居中，全站一致 */
  --nagaya-max-w: 480px;
  /* 顶栏统一高度：页签、返回条都用它，和底部 Tab（57px）呼应 */
  --nagaya-head-h: 52px;
  /* 顶栏真实高度（含安全区）。0 只是首帧兜底，挂载后 measureHeader() 写回来 */
  --nagaya-header-h: 0px;
  /* 页签条（流水/备忘/设置、未出账/已出账）的实际高度。
     页面里的吸顶元素要吸在它**下沿**，不是吸到 0 —— 吸到 0 就等于钻进
     固定顶栏底下，一滚就整条看不见了 */
  --nagaya-tabs-h: calc(var(--nagaya-head-h) + 1px);   /* 52 的页签 + 1px 下边线 */
  /* 「本期固定费」那一块的尺寸。同一块东西有两套实现 —— 未出账那页是可编辑面板，
     已出账那页是只读列表 —— 两边长得必须一样。数写在这儿一份，免得又各自走散 */
  /* 48 不是 40：这五个格子是每个月真要动手打字的地方，而输入框比行矮 4px。
     40 的时候框只有 34 高、上下两框之间只隔 7px，拇指往下偏一点就把水费
     打进了燃气那行 —— 而这一屏「改完自动保存」，没有确认也没有撤销 */
  --nagaya-fee-row-h: 48px;
  --nagaya-fee-amount-fs: 16px;
  /* 金额列离右边多远。未出账那页那儿站着展开箭头，已出账那页用内边距占出来 */
  --nagaya-fee-amount-gap: 50px;
  /* 「加一条 / 加一项」那种收尾行的高度。备忘和固定费设置两处共用 */
  --nagaya-add-row-h: 50px;
}
/* 账单上的一「块」：固定费、本期其他、每人、转账方案各算一块。
   块与块之间用 8px 的灰带断开 —— 1px 细线在手机上分不出「同一块里的两行」
   和「两块之间」，整页会糊成一长条 */
.bill-section { border-bottom: 8px solid var(--nagaya-bg-sunken); }
/* 离线细带。颜色用 warning 一路：这不是错误，是「你看到的可能不是最新的」 */
.stale-bar {
  min-height: 32px;
  padding: 4px 12px;
  background: #fff4e0;
  color: var(--nagaya-warn);
  font-size: 12px;
}
.stale-retry {
  border: none;
  background: transparent;
  color: var(--nagaya-warn);
  font-size: var(--nagaya-fs-meta);
  font-weight: 600;
  text-decoration: underline;
  padding: 6px 4px;
  cursor: pointer;
}
/* 每一块的标题条。未出账和已出账两页、四个块共用这一份，免得又各写各的。
   高度写死 44：只有「本期固定费」那条右边带着 16px 的合计，撑出 44 高，
   别的标题条只有 14px 的字、自然高度 41 —— 不钉死的话同一页上四条不齐 */
.section-head {
  min-height: 44px;
  padding-top: 16px;
  padding-bottom: 4px;
}
.section-head .q-item__section--main { font-size: 14px; font-weight: 500; }

/* 二级页面的返回条。原来三个页面各写各的，最矮的只有 42px，挤在一起显得小气 */
.page-head {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: var(--nagaya-head-h);
  padding: 0 4px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  font-size: 16px;
}
.q-page {
  max-width: var(--nagaya-max-w);
  margin: 0 auto;
}
/* 刘海屏/灵动岛：顶栏往下让出安全区 */
.q-header { padding-top: env(safe-area-inset-top); }
/*
  **聚焦时滚到哪儿为止。** iOS 弹键盘会把聚焦的框滚进可视区，默认一直滚到
  页面最顶 —— 那儿正是固定顶栏和状态栏，金额那个大数字被切掉一截。
  scroll-padding 是给滚动容器（这里是整页）划的「别往这儿放」的边。
*/
html { scroll-padding-top: calc(var(--nagaya-header-h) + 8px); }
/*
  **聚焦时别被顶栏和状态栏盖住。** iOS 弹键盘时会把聚焦的输入框滚到布局视口
  最顶上，而那儿正是状态栏和固定顶栏所在 —— 金额框就是这么被吃掉的。
  scroll-margin-top 告诉浏览器「滚到这儿就够了」，Safari 14.5 起支持。
*/
/* **只管上面那头。** 下面那头原来也留了 147px（底栏 + 操作条），可它的意思是
   「滚进视野时下面得空出这么多」—— 于是一聚焦就多往上滚一截，内容底下吊出
   一大片空白。键盘本来就把下半屏占了，那块空白纯属白让 */
input,
textarea { scroll-margin-top: calc(var(--nagaya-header-h) + 8px); }
</style>

<style scoped>
/* 刘海屏/手势条：底栏内缩到安全区以内，否则最后一个 tab 会被手势条压住 */
.footer-safe {
  padding-bottom: env(safe-area-inset-bottom);
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
</style>
