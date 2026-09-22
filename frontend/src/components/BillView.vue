<!--
  一张账单的全貌 —— SPEC F6。**看哪一张由 viewKey 决定，不看路由**：
  三个页签是同一个地址上的状态切换，点页签不会改地址、也不会重建这个组件。

  账单只负责展示：余额是全局累计的，这里拆成「期初结转 + 本期发生 + 本期已收付」。
  所以「赊账」不需要任何额外机制 —— 少付的部分自然以「上期结转」出现在下一张账单上。

  一键复制的文本是直接贴进 LINE 群的，所以格式按等宽对齐排，手机上看着是一张表。
-->
<template>
  <div class="page">
    <!-- 冷启动时别急着喊「这儿是空的」：请求还在飞就先什么都不显示，
         否则每次头一回进来都要先闪一句「本期还没有账目」 -->
    <div v-if="!bill && !bills.pending" class="text-center q-mt-xl">
      <!-- **「取不到」和「没有」得分开说。** 断网时原来这儿写的是
           「这屋里还没出过账」—— 一句假话，而且没有任何重试的出口 -->
      <template v-if="bills.lastError">
        <div class="text-negative">{{ bills.lastError }}</div>
        <q-btn flat dense color="primary" class="q-mt-sm" :label="t('common.retry')" @click="retry" />
      </template>
      <div v-else class="text-grey-6">
        {{ isOpenTab ? t('bill.noOpen') : t('bill.noPeriod') }}
      </div>
    </div>

    <!-- **慢网下别给整屏白。** 地铁里 3 秒一跳很常见，实测 6.2 秒纯白 ——
         人会以为卡死了或者这家还没出过账，于是反复点页签，每点一次又重发一轮，
         越点越慢。骨架按真实块高摆，数据到了内容是「填进去」而不是「砸出来」 -->
    <div v-if="!bill && bills.pending" class="skel">
      <div class="q-pa-md">
        <q-skeleton type="text" width="45%" height="26px" />
        <q-skeleton type="text" width="60%" height="16px" class="q-mt-xs" />
        <q-skeleton type="text" width="35%" height="22px" class="q-mt-sm" />
      </div>
      <div class="bill-section q-px-md q-pb-md">
        <q-skeleton type="text" width="30%" height="18px" class="q-mb-sm" />
        <q-skeleton
          v-for="n in 5"
          :key="n"
          type="rect"
          :height="'var(--nagaya-fee-row-h)'"
          class="q-mb-xs"
        />
      </div>
      <div class="q-px-md q-py-md">
        <q-skeleton v-for="n in 3" :key="n" type="rect" height="56px" class="q-mb-sm" />
      </div>
    </div>

    <!-- 用 v-if 而不是 v-else：上面那句多了个「还在加载」的条件，
         两个都不成立时（冷启动的头几十毫秒）这一页就该是干净的 -->
    <template v-if="bill">
      <div class="head bill-section q-pa-md">
        <div class="row items-baseline">
          <!-- 出过的单子：名字就是翻页入口。原来「以前」单独占一个页签，
               而「挑某个月」才是常态、「逐张翻」很少 —— 并进来之后
               这一屏永远是一张账单，形状不再变来变去 -->
          <button v-if="!bill.is_draft" class="pick text-subtitle1 text-weight-medium">
            {{ statementLabel(bill) }}
            <q-icon name="expand_more" size="20px" class="text-grey-6" />
            <q-menu anchor="bottom left" self="top left" max-height="60vh">
              <q-list separator style="min-width: 260px">
                <q-item
                  v-for="st in bills.statements ?? []"
                  :key="st.id"
                  v-close-popup
                  clickable
                  :class="{ 'bg-blue-1': st.id === bill.statement_id }"
                  @click="pickStatement(st.id)"
                >
                  <q-item-section>
                    <q-item-label>{{ statementLabel(st) }}</q-item-label>
                    <q-item-label caption>
                      {{ t('bill.coversRange', { from: st.covers_from, to: st.covers_to }) }}
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="text-weight-medium text-grey-9">{{ formatYen(st.total_expense) }}</div>
                    <q-badge
                      v-if="st.settled"
                      color="positive"
                      class="q-mt-xs"
                      :label="t('bill.settledBadge')"
                    />
                    <div v-else class="text-caption text-grey-6 q-mt-xs">{{ t('bill.unsettled') }}</div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </button>
          <div v-else class="text-subtitle1 text-weight-medium">{{ t('bill.draft') }}</div>
          <q-space />
          <!-- 「这一期一共花了多少」降级：它谁也不用去做什么。
               真正要做的那件事（我要给谁多少）挪到下面用 28px 印 -->
          <div class="text-caption text-grey-6 q-mr-xs">{{ t('bill.total') }}</div>
          <div class="text-subtitle1 text-weight-medium num">{{ formatYen(bill.total_expense) }}</div>
        </div>
        <div class="row items-baseline text-caption text-grey-6">
          <div v-if="bill.covers_from">
            {{ t('bill.coversRange', { from: bill.covers_from, to: bill.covers_to }) }}
          </div>
          <q-space />
          <!-- 这一格就是「这张单子现在什么状态」：草稿报笔数，出过的账单
               结清了给绿标、没结清给橙字。原来绿标另起一行占着一整行 -->
          <div v-if="bill.is_draft">
            <span v-if="bill.prev_cut_at" class="q-mr-sm">
              {{ t('bill.lastCut', { label: statementLabel({ label: bill.prev_label, cut_at: bill.prev_cut_at }) }) }}
            </span>
            {{ t('bill.entryCount', { n: bill.entry_count }) }}
          </div>
          <q-badge v-else-if="bill.settled" color="positive" :label="t('bill.settledBadge')" />
          <div v-else class="text-warning">{{ t('bill.unsettled') }}</div>
        </div>

        <!-- 自己那笔摆在最显眼处。读账单的人要的就是这一个数字，
             埋在半屏之下的话，他先看到的全是别人的录入框。
             **结清了就划掉**：钱早就转过了，一个亮着的「你应收 ¥84,106」
             会让人以为现在还欠着 -->
        <!-- **一句话里也要分层。** 原来整句 17px 红字印成一行，人得读完
             「你要给 Zen ¥53,047」才拿到那个数；而这是全屏第一重要的数字，
             旁边「合计」反倒用了更大的字。现在标签归标签、数字归数字 -->
        <div
          v-if="mine"
          class="mine q-mt-md"
          :class="[mine.closing < 0 ? 'owe' : 'owed', { done: !bill.is_draft && myLeft === 0 }]"
        >
          <div v-if="minePart.label" class="mine-label">{{ minePart.label }}</div>
          <div class="mine-figure num">{{ minePart.figure }}</div>
        </div>

        <!-- 不锁历史，但改动必须可见：否则下一张的「上期结转」没人解释得清。
             **这条横幅是那条规矩唯一的可见凭证** —— 曾被一个 class="hidden" 的
             外壳罩住（重构时套错的），于是「可以改」成了「改了没人知道」 -->
        <q-banner v-if="bill.edited_after_cut" dense class="bg-orange-1 text-orange-9 q-mt-sm rounded-borders">
          {{ bill.edited_after_cut.from_earlier
            ? t('bill.driftedFromEarlier')
            : t('bill.editedAfterCut', {
              n: bill.edited_after_cut.count,
              frozen: formatYen(bill.edited_after_cut.frozen_total ?? 0),
              live: formatYen(bill.edited_after_cut.live_total),
            }) }}
        </q-banner>
      </div>

      <!-- 本期固定费：出账单时顺手把家賃/水电煤网填了，账单跟着重算 -->
      <MonthlyFixed v-if="bill.is_draft" @saved="load" />

      <!-- 已出的账单没有那个面板（它只管当前草稿），可固定费往往是这张单子上最大的
           一笔钱。不摆出来的话，点进一张旧账单只看得见日用品，家賃 12 万凭空消失。

           整段只有一个入口，通向固定费那一屏 —— 不给每行挂一个箭头去单笔编辑页：
           固定费是一整屏一起看的东西，拆成一笔笔既多按钮又不好改。 -->
      <div v-else class="bill-section">
        <q-item clickable dense class="section-head" @click="openMonthly">
          <q-item-section>{{ t('monthly.title') }}</q-item-section>
          <q-item-section side class="amount text-grey-9">{{ formatYen(monthlyTotal) }}</q-item-section>
          <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
        </q-item>
        <!-- 行的尺寸照着未出账那页的可编辑面板来：一样的行高、一样的金额字号、
             一样的右边距。两页看的是同一件事，来回切时这一块不该变样 -->
        <q-list v-if="monthlyEntries.length" separator class="monthly-list">
          <q-item v-for="e in monthlyEntries" :key="e.id" dense>
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: colorOfEntry(e) }" text-color="white">
                <q-icon :name="iconOfEntry(e)" size="16px" />
              </q-avatar>
            </q-item-section>
            <!-- 只写分类名，不写备注：固定费这一屏（可编辑面板那边）根本没有
                 填备注的入口，这里却显示一条，等于凭空冒出个改不了的字段 -->
            <q-item-section>
              <q-item-label>{{ categoryOfEntry(e)?.name ?? labelOfEntry(e) }}</q-item-label>
            </q-item-section>
            <q-item-section side class="amount text-grey-9">{{ formatYen(e.amount_jpy) }}</q-item-section>
          </q-item>
        </q-list>
        <div v-else class="text-caption text-grey-6 q-px-md q-pb-md">{{ t('monthly.noneBilled') }}</div>
      </div>

      <!-- 固定费之下，把这期其他的开销也摆出来：
           不然账单上只看得见固定项，日用品/食費那些钱是从哪来的就说不清 -->
      <!-- .others 这个 class 是 E2E 用来指「本期其他那一块」的，别随手删 -->
      <div class="bill-section others">
        <q-item dense class="section-head">
          <q-item-section>{{ t('bill.others') }}</q-item-section>
        </q-item>
        <q-list v-if="others.length" separator>
          <q-item v-for="e in others" :key="e.id" dense clickable @click="editEntry(e.id)">
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: colorOfEntry(e) }" text-color="white">
                <q-icon :name="iconOfEntry(e)" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ labelOfEntry(e) }}</q-item-label>
              <q-item-label caption>
                {{ e.date.slice(5) }} · {{ meta.byId[e.payer_id]?.display_name }}
              </q-item-label>
            </q-item-section>
            <q-item-section side :class="e.amount_jpy < 0 ? 'text-positive' : 'text-grey-9'">
              {{ formatYen(e.amount_jpy) }}
            </q-item-section>
            <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
          </q-item>
        </q-list>
        <div v-else class="text-caption text-grey-6 q-px-md q-pb-md">{{ t('bill.othersEmpty') }}</div>
      </div>

      <!-- .per-member 是 E2E 用来指「每人那一块」的锚点，别随手删 -->
      <div class="bill-section per-member">
        <q-item dense class="section-head">
          <q-item-section>{{ t('bill.perMember') }}</q-item-section>
        </q-item>
        <!-- 「谁欠谁」原来只能靠读三行各 4 个灰数字算出来。
             这条背景填充**不占一个新像素**（它在背景层），长度就是旁边已经
             印出来的那个数，左边是要付、右边是要收，中轴贯穿三行 ——
             于是「谁欠得最多」变成一眼看形状的事，而那 12 个数字一个不删 -->
        <div class="axis-hint text-grey-6">
          <span>{{ t('bill.axisPay') }}</span>
          <span>{{ t('bill.axisReceive') }}</span>
        </div>
        <q-list separator class="axis-list">
        <q-item
          v-for="row in bill.members"
          :key="row.member_id"
          class="axis-row"
          :class="{ 'bg-blue-1': row.member_id === auth.me?.id }"
        >
          <div class="axis-fill" :style="fillStyle(row)" />
          <q-item-section avatar>
            <MemberAvatar :member-id="row.member_id" />
          </q-item-section>
          <!-- 名字和金额一行，明细在下面**占满整行**排成两列。
               明细原来挤在名字那一列里（右边被金额占走近百 px），四项排不下，
               折成 2+1+1 三行还把「上期结转」和「-¥38,262」拆两行去。
               **「已收到」不能漏**：收过转账的人（这里是 Go）少了这一项，
               剩下几个数怎么算都凑不出右边那个合计 -->
          <q-item-section>
            <div class="row items-center no-wrap">
              <div class="col">{{ nameOf(row.member_id) }}</div>
              <div v-if="row.closing === 0" class="text-weight-medium text-positive">
                {{ t('bill.settled') }}
              </div>
              <div v-else :class="row.closing < 0 ? 'text-negative' : 'text-positive'">
                <span class="text-caption text-grey-6 q-mr-xs">
                  {{ row.closing > 0 ? t('bill.toReceive') : t('bill.toPay') }}
                </span>
                <span class="text-weight-medium">{{ formatYen(Math.abs(row.closing)) }}</span>
              </div>
            </div>
            <div class="breakdown text-caption text-grey-6">
              <!-- 和旁边四项一个规矩：是 0 就别占一行。
                   刚出完账的草稿页上，三个人各显示一遍「应担 ¥0」，
                   底下还跟着一句「大家都平了，不用转账」—— 同一件事说四遍 -->
              <!-- **每个字段钉死自己那一格**，不许自动流。
                   自动流的时候，Go 缺「已预付」就会让「上期结转」顶到左列，
                   而 Kan/Zen 的还在右列 —— 三个人横着比「谁上期结转了多少」，
                   眼睛得在两列之间来回跳，而那正是要照着打钱的数字 -->
              <span v-if="row.owed" class="b-owed">{{ t('bill.owed') }} {{ formatYen(row.owed) }}</span>
              <span v-if="row.paid" class="b-paid">{{ t('bill.paid') }} {{ formatYen(row.paid) }}</span>
              <span v-if="row.transferred_out" class="b-tx">
                {{ t('bill.prepaid') }} {{ formatYen(row.transferred_out) }}
              </span>
              <span v-if="row.transferred_in" class="b-tx">
                {{ t('bill.received') }} {{ formatYen(row.transferred_in) }}
              </span>
              <span v-if="row.opening" class="b-carry">{{ t('bill.carried') }} {{ formatYen(row.opening) }}</span>
            </div>
          </q-item-section>
        </q-item>
        </q-list>
      </div>

      <div>
        <q-item dense class="section-head">
          <q-item-section>
            {{ bill.transfers.length ? t('bill.plan', { n: bill.transfers.length }) : t('bill.planEmpty') }}
          </q-item-section>
        </q-item>
        <div class="q-px-md q-pb-md">
        <q-card v-for="(tr, i) in bill.transfers" :key="i" flat bordered class="q-mb-sm">
          <q-card-section class="row items-center q-py-sm q-px-md">
            <div class="col">
              <div class="text-caption text-grey-7">
                {{ nameOf(tr.from_id) }}
                <q-icon name="arrow_forward" size="13px" class="q-mx-xs" />
                {{ nameOf(tr.to_id) }}
              </div>
              <div class="text-subtitle1 text-weight-medium">{{ formatYen(tr.amount) }}</div>
              <!-- **进度必须上屏。** 后端一直算着「这一笔已经转过多少」，可它以前
                   只送进了对话框的预填值 —— 屏幕上只有一个全额，于是已经还了一半的人
                   照着这个数再转一次全额 -->
              <div v-if="noteOf(tr, i)" class="text-caption" :class="noteClassOf(tr, i)">
                {{ noteOf(tr, i) }}
              </div>
            </div>
<!-- 转出方和转入方看到的是同一个「已完成」，记的也是同一笔。
                 **跟这笔没关系的人不显示按钮**：原来对所有人显示「已收到」，
                 Kan 一点就替 Go 确认了收款，而 Go 那边钱还没到。

                 **按钮的开关是「此刻还欠不欠」，不是「这是不是最新那张」。**
                 原来按 isCurrent 判：更早那些单子收掉了按钮，最新那张没收 ——
                 而出账之后只要有人没照方案走（现金、并单转、经第三人），
                 冻结方案里那一对就再也不会走钱，按下去凭空造一笔债。
                 实测：全屋余额已经全是 0，按一下变成一个人倒欠另一个人一万。
                 改看 leftOf() 之后这种情况按钮自己就不在了，而「钱确实还欠着」
                 的旧单子反倒能结账了 —— 两头都比原来对 -->
            <q-icon
              v-if="bill.settled_transfers[i] || leftOf(tr, i) === 0"
              name="check_circle"
              :color="bill.settled_transfers[i] ? 'positive' : 'grey-5'"
              size="24px"
            />
            <q-btn
              v-else-if="auth.me?.id === tr.to_id || auth.me?.id === tr.from_id"
              color="primary"
              no-caps
              unelevated
              padding="10px 18px"
              :loading="busy === i"
              :label="t('bill.done')"
              @click="confirmReceived(tr, i)"
            />
          </q-card-section>
        </q-card>
        <!-- 旧单子上那个按钮必须收掉。**冻结的方案里那几对，后来可能再也不会有钱
             流过** —— 新开销把债权重新净额化之后，A 的钱是经 B 绕回来的，
             于是「C→A」那一行永远点不亮、整张永远挂着「未结清」。
             实测（两种结算模式都一样）：全屋余额已经全是 0，按一下那个按钮
             凭空造出一万块债。所以旧单子只留绿勾，结账去最新那张。 -->
        <div v-if="superseded" class="text-caption text-grey-6 q-mt-sm">
          {{ supersededText }}
        </div>
        </div>
      </div>

      <!-- 主操作固定在拇指区，和记一笔那屏一个规矩：这一页很长，
           「出账单」压在最底下的话每次都要先滚到底 -->
      <div class="actions">
        <q-btn
          outline
          color="primary"
          no-caps
          icon="content_copy"
          :label="t('bill.copy')"
          @click="copyBill"
        />
        <q-btn
          v-if="bill.is_draft"
          color="primary"
          no-caps
          unelevated
          icon="task_alt"
          :label="t('bill.cut')"
          :disable="!bill.entry_count"
          @click="doCut"
        />
        <!-- 已出的账单：右边这一半写「已出账」。做成静态块不是禁用按钮 ——
             禁用按钮看着还是个按钮，会让人反复点它找反应 -->
        <div v-else class="issued row items-center justify-center">
          <q-icon name="task_alt" size="24px" />
          {{ t('bill.issued') }}
        </div>
      </div>

    </template>

    <!-- 出账完成：立刻告诉大家谁该转多少 -->
    <q-dialog v-model="showCutResult">
      <q-card style="width: 92vw">
        <q-card-section class="q-pb-none">
          <div class="text-subtitle1 text-weight-medium">{{ t('bill.cutDoneTitle') }}</div>
          <div class="text-caption text-grey-7 q-mt-xs">{{ t('bill.cutDoneHint') }}</div>
        </q-card-section>
        <q-card-section>
          <div v-if="!cutResult?.transfers.length" class="text-grey-7">{{ t('bill.planEmpty') }}</div>
          <div
            v-for="(tr, i) in cutResult?.transfers ?? []"
            :key="i"
            class="row items-baseline q-py-xs"
          >
            <div>{{ nameOf(tr.from_id) }}</div>
            <q-icon name="arrow_forward" size="14px" class="q-mx-xs text-grey-6" />
            <div>{{ nameOf(tr.to_id) }}</div>
            <q-space />
            <div class="text-subtitle1 text-weight-medium">{{ formatYen(tr.amount) }}</div>
          </div>
        </q-card-section>
        <!-- **主色给真正要做的那件事。** 这个弹窗存在的唯一理由就是「把谁给谁
             多少发到群里」，而原来蓝色的是「确定」（＝关掉它），顺手一点，
             那两行转账方案就此消失，得自己滚到页底再找一次「复制账单」 -->
        <q-card-actions align="right">
          <q-btn v-close-popup flat no-caps color="grey-7" :label="t('common.confirm')" />
          <q-btn unelevated no-caps color="primary" :label="t('bill.copy')" @click="copyBill" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- 剪贴板在非 HTTPS 下用不了（局域网 http 访问就会撞上），退回让人手动长按复制 -->
    <q-dialog v-model="showFallback">
      <q-card style="width: 92vw">
        <q-card-section class="text-caption text-grey-7">{{ t('bill.copyFallback') }}</q-card-section>
        <q-card-section>
          <pre class="bill-text">{{ billText }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import type { Bill, BillTransfer, Entry, Statement, BillRow } from 'src/api/types'
import MemberAvatar from 'src/components/MemberAvatar.vue'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { todayJst } from 'src/date'
import { tint } from 'src/color'
import { statementLabel } from 'src/statement'
import { formatYen } from 'src/i18n'
import { useAuth } from 'src/stores/auth'
import { type BillKey, useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { KIND_COLOR } from 'src/theme'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const router = useRouter()

const props = defineProps<{ viewKey: BillKey }>()

/** 点一条明细就去改它。已出账的照样能改：差额自己进下一张的「上期结转」 */
function editEntry(id: number) {
  void router.push({ name: 'entry-edit', params: { id: String(id) } })
}
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()

const bills = useBills()
const viewKey = computed(() => props.viewKey)
/** 「已出账」那页：看的是最近出的那一张，id 由 store 里的单子列表定 */
const isOpenTab = computed(() => props.viewKey === 'current')
const view = computed(() => {
  const ck = bills.cacheKey(viewKey.value)
  return ck === null ? null : (bills.views[ck] ?? null)
})
const bill = computed(() => view.value?.bill ?? null)
const draftEntries = computed(() => view.value?.entries ?? [])
const busy = ref<number | null>(null)
const showFallback = ref(false)
const cutResult = ref<Bill | null>(null)

const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)

/** 自己在这张账单上的那一行 */
const showCutResult = computed({
  get: () => cutResult.value !== null,
  set: (v) => {
    if (!v) cutResult.value = null
  },
})

const mine = computed(
  () => bill.value?.members.find((r) => r.member_id === auth.me?.id) ?? null,
)
// 「这是不是最新那张」这个判断没有了 —— 它曾经是按钮的开关，而那是错的判据：
// 最新那张的方案同样会在出账后作废（有人没照方案走、或者又记了新账），
// 而更早那张上的钱可能确确实实还欠着。现在一律看 leftOf()：此刻还欠不欠。

/**
 * 这一笔**此刻**还该转多少。
 *
 * 两头取小：
 *   * 「这一笔还剩多少」＝ 方案额 − 已经转过的（后端的 settled_paid）；
 *   * 「这一对此刻还欠多少」＝ live_transfers 里同一对的金额。
 * 后者是关键：出账之后大家换了条路结清（现金、并单转、经第三人），
 * 这一对就再也不会走钱，它此刻是 0 —— 于是按钮自己消失，按不出假债来。
 * 前者保证在旧单子上不会问出一个超过这张单子本身的数。
 */
function leftOf(tr: BillTransfer, i: number): number {
  const b = bill.value
  if (!b) return 0
  const rest = tr.amount - (b.settled_paid?.[i] ?? 0)
  const live = (b.live_transfers ?? []).find(
    (x) => x.from_id === tr.from_id && x.to_id === tr.to_id,
  )?.amount
  return Math.max(0, Math.min(rest, live ?? rest))
}

/** 卡片上那行小字：转了多少、还差多少、或者「已经不用转了」 */
function noteOf(tr: BillTransfer, i: number): string {
  const b = bill.value
  if (!b || b.settled_transfers[i]) return ''
  const paid = b.settled_paid?.[i] ?? 0
  const left = leftOf(tr, i)
  if (left === 0) return t('bill.planPairDone')
  if (paid > 0) return t('bill.planProgress', { paid: formatYen(paid), left: formatYen(left) })
  if (left !== tr.amount) return t('bill.planLeft', { left: formatYen(left) })
  return ''
}
const noteClassOf = (tr: BillTransfer, i: number) =>
  leftOf(tr, i) === 0 ? 'text-grey-6' : 'text-primary'

/**
 * 这张单子的方案里有行**永远点不亮了** —— 钱已经绕别的路结清，
 * 或者后来的账把债权重新净额化了。这时候得说一句，否则那张永远挂着「未结清」
 * 而没人知道为什么。
 */
const superseded = computed(() => {
  const b = bill.value
  if (!b || b.is_draft) return false
  return b.transfers.some((tr, i) => !b.settled_transfers[i] && leftOf(tr, i) === 0)
})

/**
 * 方案被接手时那句话。**得带上「那我现在到底欠多少」** ——
 * 只说「去未出账那页」等于把人赶去另一页自己找数字，而那个数这儿就有。
 */
const supersededText = computed(() => {
  const owe = Number(bill.value?.live_closing?.[String(auth.me?.id ?? '')] ?? 0)
  return owe < 0
    ? t('bill.planSupersededMine', { amount: formatYen(-owe) })
    : t('bill.planSuperseded')
})

/** 这张单子里跟我有关的那几行，此刻还剩多少要转 */
const myLeft = computed(() => {
  const b = bill.value
  const me = auth.me?.id
  if (!b || me === undefined) return 0
  return b.transfers.reduce(
    (sum, tr, i) => (tr.from_id === me || tr.to_id === me ? sum + leftOf(tr, i) : sum),
    0,
  )
})

/**
 * 最显眼那行字。**它是行动指示，所以按「此刻」说话，不按出账那一刻说话。**
 *
 * 原来直接印冻结方案里我那几笔的原额：已经还清的人照样被命令「你要给 Zen ¥9,999」，
 * 他真会再转一次（实测多付 ¥9,999）；还了一半的人被告知一个偏大的数。
 * 后端其实一直算着「已经转过多少」，只是那个数以前只送进了对话框的预填值。
 *
 * 口径仍然限定在**这张单子的方案**里：翻七月那张时不该跳出今天的欠款。
 */
const mineText = computed(() => {
  const row = mine.value
  const b = bill.value
  if (!row || !b) return ''
  const me = row.member_id
  const mineRows = b.transfers
    .map((tr, i) => ({ tr, left: leftOf(tr, i) }))
    .filter((x) => x.tr.from_id === me || x.tr.to_id === me)

  if (mineRows.length) {
    const out = mineRows.filter((x) => x.tr.from_id === me && x.left > 0)
    const inc = mineRows.filter((x) => x.tr.to_id === me && x.left > 0)
    if (!out.length && !inc.length) return t('bill.youSettled')
    if (inc.length && !out.length) {
      return t('bill.youReceive', { amount: formatYen(inc.reduce((n, x) => n + x.left, 0)) })
    }
    if (out.length === 1) {
      const only = out[0]!
      return t('bill.youPay', { to: nameOf(only.tr.to_id), amount: formatYen(only.left) })
    }
    // **得全列出来**：原来只取第一条、却把欠款总额安在那个人头上 ——
    // 要分给两个人时，屏幕上最显眼的那行字会让人把全部的钱转给其中一个
    return t('bill.youPayList', {
      list: out.map((x) => `${nameOf(x.tr.to_id)} ${formatYen(x.left)}`).join('、'),
    })
  }

  // 方案里没有我这条边：只说这张单子上我是什么状态
  if (row.closing === 0) return t('bill.youSettled')
  if (row.closing > 0) return t('bill.youReceive', { amount: formatYen(row.closing) })
  return t('bill.youOwe', { amount: formatYen(Math.abs(row.closing)) })
})

/**
 * 最显眼那行字，拆成「标签 + 数字」两段。
 * 多笔要转时没法拆（是一串「给谁多少、给谁多少」），那就整句照旧，只是小一号。
 */
const minePart = computed<{ label: string; figure: string }>(() => {
  const row = mine.value
  const b = bill.value
  if (!row || !b) return { label: '', figure: '' }
  const me = row.member_id
  const rows = b.transfers
    .map((tr, i) => ({ tr, left: leftOf(tr, i) }))
    .filter((x) => (x.tr.from_id === me || x.tr.to_id === me) && x.left > 0)
  const out = rows.filter((x) => x.tr.from_id === me)
  const inc = rows.filter((x) => x.tr.to_id === me)
  if (out.length === 1 && !inc.length) {
    const only = out[0]!
    return {
      label: t('bill.youPayLabel', { to: nameOf(only.tr.to_id) }),
      figure: formatYen(only.left),
    }
  }
  if (inc.length && !out.length) {
    return {
      label: t('bill.youReceiveLabel'),
      figure: formatYen(inc.reduce((n, x) => n + x.left, 0)),
    }
  }
  if (!out.length && !inc.length && b.transfers.some((tr) => tr.from_id === me || tr.to_id === me)) {
    return { label: '', figure: t('bill.youSettled') }
  }
  if (!b.transfers.some((tr) => tr.from_id === me || tr.to_id === me)) {
    if (row.closing === 0) return { label: '', figure: t('bill.youSettled') }
    return {
      label: row.closing > 0 ? t('bill.youReceiveLabel') : t('bill.youOweLabel'),
      figure: formatYen(Math.abs(row.closing)),
    }
  }
  return { label: '', figure: mineText.value }
})

/**
 * 每人那一行背景上那条发散填充。
 *
 * 长度按「和这一屏欠得最多的那个人比」算，不是按金额绝对值 —— 这一屏要回答的
 * 是「谁欠得最多、差多少」，而不是「这些钱在全世界算多还是少」。
 * 中轴固定在 50%：要付往左长，要收往右长，三行共用同一条轴才比得出来。
 */
const maxAbs = computed(() =>
  Math.max(1, ...(bill.value?.members ?? []).map((r) => Math.abs(r.closing))),
)
function fillStyle(row: BillRow): Record<string, string> {
  const w = `${(Math.abs(row.closing) / maxAbs.value) * 50}%`
  // 用**这个人自己的颜色**：头像和账单每人行是同一个色，
  // 「这条是谁的」不用再回头看左边那个圆点
  const bg = tint(meta.byId[row.member_id]?.color ?? '#90a4ae', 0.32)
  return row.closing < 0
    ? { right: '50%', width: w, background: bg }
    : { left: '50%', width: w, background: bg }
}

/** 改完数据强制重取这一张。进页面用的是 ensure（缓存先上屏） */
const load = () => bills.reload(viewKey.value)
/** 空态上那个「重试」。失败的话 store 的 lastError 会自己更新，这儿只是别漏接 */
const retry = () => void load().catch(() => {})

/** 翻到另一张出过的单子。挑中最近那张就存 null，这样以后再出新账它跟着走 */
function pickStatement(id: number) {
  bills.detail = id === bills.statements?.[0]?.id ? null : id
}

/** 这张账单上的固定费。已出的账单用它代替那个可编辑面板 */
const monthlyEntries = computed(() =>
  draftEntries.value
    .filter((e) => {
      if (e.kind === 'settlement' || e.category_id === null) return false
      return Boolean(meta.categoryById[e.category_id]?.monthly)
    })
    // 跟可编辑面板同一个顺序（家賃在最上面）。按日期排的话全是出账日，等于没排
    .sort(
      (a, b) =>
        (meta.categoryById[a.category_id!]?.display_order ?? 0) -
        (meta.categoryById[b.category_id!]?.display_order ?? 0),
    ),
)

const monthlyTotal = computed(() =>
  monthlyEntries.value.reduce((sum, e) => sum + e.amount_jpy, 0),
)

/** 固定费是一整屏一起看的东西，点哪一行都去那一屏，不进单笔编辑页 */
function openMonthly() {
  const id = bill.value?.statement_id
  if (id == null) return
  void router.push({ name: 'monthly', params: { statementId: String(id) } })
}

/** 这张账单上非固定费的明细（日用品/食費/收入之类）。转账不算，它们在下面的方案里 */
const others = computed(() =>
  draftEntries.value.filter((e) => {
    if (e.kind === 'settlement') return false
    const cat = e.category_id === null ? undefined : meta.categoryById[e.category_id]
    return !cat?.monthly
  }),
)

const categoryOfEntry = (e: Entry) =>
  e.category_id === null ? undefined : meta.categoryById[e.category_id]
// 收入没有分类，得有自己的图标色，否则跟「分类丢了」长得一模一样
const colorOfEntry = (e: Entry) =>
  e.kind === 'expense' ? (categoryOfEntry(e)?.color ?? '#90a4ae') : KIND_COLOR[e.kind]
const iconOfEntry = (e: Entry) =>
  e.kind === 'income' ? 'savings' : (categoryOfEntry(e)?.icon ?? 'receipt_long')
const labelOfEntry = (e: Entry) => e.title || categoryOfEntry(e)?.name || t(`kind.${e.kind}`)

// 有缓存立刻渲染，同时后台校正。换页签时组件不重建、只换 prop，所以盯着 prop
// 失败在 store 的 lastError 里已经说过了，这儿只是别留一个没人接的 rejection
onMounted(() => {
  bills.ensure(viewKey.value).catch(() => {})
  bills.warm()                      // 预热另外两页，第一次切过去不用等
})
watch(viewKey, () => bills.ensure(viewKey.value).catch(() => {}))

/** 贴进 LINE 的纯文本。在前端拼，所以自动跟随界面语言（SPEC §7.5）。 */
const billText = computed(() => {
  const b = bill.value
  if (!b) return ''
  const lines: string[] = []
  const head = b.is_draft ? t('bill.draft') : statementLabel(b)
  lines.push(`【${head}】 ${t('bill.total')} ${formatYen(b.total_expense)}`)
  if (b.covers_from) lines.push(t('bill.coversRange', { from: b.covers_from, to: b.covers_to }))
  if (!b.is_draft) lines.push(b.settled ? t('bill.settledBadge') : t('bill.unsettled'))
  // 每人明细是**实时**重算的，转账方案却是出账当时冻结的那份 —— 这张单子
  // 被改过之后两者必然对不上。屏幕上那条橙色横幅是这条规矩唯一的凭证，
  // 而复制文本才是「用户手里那份」，不能只有屏幕上有
  if (b.edited_after_cut) {
    lines.push(
      b.edited_after_cut.from_earlier
        ? t('bill.driftedFromEarlier')
        : t('bill.editedAfterCut', {
            n: b.edited_after_cut.count,
            frozen: formatYen(b.edited_after_cut.frozen_total ?? 0),
            live: formatYen(b.edited_after_cut.live_total),
          }),
    )
  }
  lines.push('')
  for (const r of b.members) {
    const bits = r.owed ? [`${t('bill.owed')} ${formatYen(r.owed)}`] : []
    if (r.paid) bits.push(`${t('bill.paid')} ${formatYen(r.paid)}`)
    if (r.transferred_out) bits.push(`${t('bill.prepaid')} ${formatYen(r.transferred_out)}`)
    if (r.transferred_in) bits.push(`${t('bill.received')} ${formatYen(r.transferred_in)}`)
    if (r.opening) bits.push(`${t('bill.carried')} ${formatYen(r.opening)}`)
    const tail =
      r.closing === 0
        ? t('bill.settled')
        : `${r.closing > 0 ? t('bill.toReceive') : t('bill.toPay')} ${formatYen(Math.abs(r.closing))}`
    lines.push(`${nameOf(r.member_id)}  ${bits.join(' / ')} → ${tail}`)
  }
  lines.push('')
  if (b.transfers.length) {
    lines.push(t('bill.plan', { n: b.transfers.length }))
    for (const [i, tr] of b.transfers.entries()) {
      // **进度得跟着一起贴出去。** 这份文本才是「群里那份」，而屏幕上有绿勾、
      // 它没有 —— 于是已经还清的人在群里看到自己名下白纸黑字还欠着，再转一次
      const done = b.settled_transfers[i]
      const note = done ? `  ${t('bill.planDone')}` : noteOf(tr, i) ? `  ${noteOf(tr, i)}` : ''
      lines.push(`  ${nameOf(tr.from_id)} → ${nameOf(tr.to_id)}  ${formatYen(tr.amount)}${note}`)
    }
  } else {
    lines.push(t('bill.planEmpty'))
  }
  if (superseded.value) lines.push(t('bill.planSuperseded'))
  return lines.join('\n')
})

async function copyBill() {
  try {
    await navigator.clipboard.writeText(billText.value)
    $q.notify({ type: 'positive', message: t('bill.copied'), timeout: 1500 })
    cutResult.value = null       // 出账完成那个弹窗：复制完它的事就办完了

  } catch {
    // 非安全上下文（局域网 http）下 clipboard 直接抛，退回手动复制
    showFallback.value = true
  }
}

/**
 * 点「已完成」＝记一笔转账。金额可改小，差额自动结转 —— 这就是赊账。
 *
 * 预填的是**还差多少**，不是方案上的全额。原来永远预填全额，而部分还款之后
 * 这一屏一个字都不会变（转账进的是下一张草稿，这张的每人行、方案、结清标记
 * 全由它自己的明细算），于是「我刚才是不是没点上」→ 再按一次确定 → 重复记了
 * 一整笔。屏幕上没有任何地方提示过。
 */
function confirmReceived(tr: BillTransfer, index: number) {
  const left = leftOf(tr, index)
  $q.dialog({
    title: t('bill.done'),
    message: t('bill.doneHint', { from: nameOf(tr.from_id), to: nameOf(tr.to_id) }),
    prompt: { model: String(left || tr.amount), type: 'number' },
    cancel: true,
  }).onOk(async (value: string) => {
    // 先把逗号和空格擦掉：整屏的金额都写成 ¥10,000，照着屏幕打回去是最自然的动作
    const amount = Math.floor(Number(String(value).replace(/[,，\s]/g, '')))
    if (!Number.isFinite(amount) || amount <= 0) {
      // **不许静默 return。** 对话框已经关了、页面一个字不变，和「刚才没点上」
      // 长得一模一样 —— 而这个函数上面那段注释说的正是那个状态会让人再按一次、
      // 重复记一整笔
      $q.notify({ type: 'warning', message: t('bill.doneNeedAmount'), timeout: 4000 })
      return
    }
    busy.value = index
    try {
      // 转账发生在出账之后，所以它进的是**下一张**草稿 —— 这是对的：
      // 账单是对「出账那一刻」的陈述，之后收到的钱属于下一轮。
      // 但记账的入口留在这张单子上，因为方案就在这儿。
      await ledger.create({
        kind: 'settlement',
        date: todayJst(),
        amount_jpy: amount,
        payer_id: tr.from_id,
        to_member_id: tr.to_id,
      })
      await load()
      // 「记上了」这件事必须看得见。没有这一句的话，部分还款在这一屏上
      // 完全没有反馈 —— 人只会再按一次
      $q.notify({
        type: 'positive',
        timeout: 3000,
        message: t('bill.doneRecorded', {
          from: nameOf(tr.from_id),
          to: nameOf(tr.to_id),
          amount: formatYen(amount),
        }),
      })
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    } finally {
      busy.value = null
    }
  })
}

/** 出账单：把这一刻之前记的账归到一张单子上。**不锁定任何东西** */
function doCut() {
  // 默认勾上＝这张单子把固定费也结了。不勾＝把固定费留在草稿里，只结日常那部分。
  // 刚出过账又出一张（后端按设置里的天数判定），固定费那轮还没到，默认就别带上 ——
  // 但得把理由写出来，不然框子自己跳成没勾会让人以为坏了。
  const withMonthlyByDefault = bill.value?.suggest_monthly !== false
  // 只有默认没勾上时才多说一句。Quasar 的对话框不认换行，要换行就得开 html
  const gap = bill.value?.days_since_prev_cut ?? 0
  const hints: string[] = []
  if (!withMonthlyByDefault) {
    hints.push(gap === 0 ? t('bill.monthlyOffHintToday') : t('bill.monthlyOffHint', { n: gap }))
  }
  // **哪几项固定费还空着，出账前说一声。**
  // 电、气、水在日本是三张分开寄的账单，到得不齐是常态；漏一项就是这张单子
  // 少收几千日元，而且要等发进 LINE 群之后才有人发现，三个人的转账方案得推倒重来。
  // 日常编辑时「空框＝0，不出声」是对的，但出账是不可逆的那一步，这儿不该继续沉默
  const blank = (bills.monthly.draft?.rows ?? [])
    .filter((r) => !r.archived && !r.amount)
    .map((r) => r.name)
  if (blank.length) hints.push(t('bill.cutBlankFixed', { names: blank.join('、') }))
  const hint = hints.join('<br><br>')
  $q.dialog({
    title: t('bill.cut'),
    message: hint ? `${t('bill.cutConfirm')}<br><br>${hint}` : t('bill.cutConfirm'),
    html: Boolean(hint),
    cancel: true,
    options: {
      type: 'checkbox',
      model: withMonthlyByDefault ? ['monthly'] : [],
      items: [{ label: t('bill.includeMonthly'), value: 'monthly' }],
    },
  }).onOk(async (picked: string[]) => {
    try {
      const withMonthly = picked.includes('monthly')
      const st = await api.post<Statement>(`/api/statements?include_monthly=${withMonthly}`)
      // 出完账立刻把「谁给谁多少」摆出来 —— 这是出账之后马上要做的事，
      // 不该让人再自己翻回去找
      const cut = await api.get<Bill>(`/api/statements/${st.id}/bill`)
      cutResult.value = cut
      // 出账把所有缓存都变旧了（草稿清空、多出一张单子、固定费整批挪走），整体重取。
      // **固定费那份缓存以前不在这里面**，于是切回「未出账」会把刚出账的那批
      // 当本期草稿画出来，还可点可改
      bills.invalidate()
      bills.tab = 'current'         // 出完账就该看这张新单子；地址不动
      await bills.ensure('current')
      void bills.loadMonthly('draft').catch(() => {})   // 顺手补热，切回草稿不白闪
      // 记一笔那屏的「日期不许选回已出账范围」靠 ledger.prevCutAt，
      // 出完账不刷新的话它还是出账前的旧值，锁就形同虚设
      await ledger.refresh()
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    }
  })
}
</script>

<style scoped>
/* 每人那一行的明细：两列对齐，不是一串「·」连起来的长句。
   列宽固定（1fr 1fr）而不是自动换行 —— 自动换行下每行塞几项要看字数，
   三个人三个样，一列数字对不齐 */
.breakdown {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 10px;
  row-gap: 2px;
  margin-top: 2px;
  /* text-caption 自带 1.67 的行高，两行叠起来虚高 7px。
     这里是一块密排的数字，收到 1.4 正好 */
  line-height: 1.4;
}
.breakdown > span { white-space: nowrap; }
/* 「已预付」和「已收到」互斥，共用第 2 行第 1 格 */
.b-owed { grid-area: 1 / 1; }
.b-paid { grid-area: 1 / 2; }
.b-tx { grid-area: 2 / 1; }
.b-carry { grid-area: 2 / 2; }
/* 标题当按钮用，但看着还得是标题。
   **只中和浏览器给 button 的默认字体族**，别写 `font: inherit` ——
   那个简写会把 text-subtitle1 的 16px 一并盖成容器的 14px，标题小一号 */
.pick {
  display: inline-flex;
  align-items: center;
  border: none;
  background: none;
  padding: 0;
  font-family: inherit;
  color: inherit;
  cursor: pointer;
}
/* 本期固定费：和未出账那页的面板对齐到同一套尺寸 —— 行高 40、金额 16px、
   右边留 50px（那页那儿是展开箭头，这页没有，用内边距占出来） */
.monthly-list .q-item {
  min-height: var(--nagaya-fee-row-h);
  padding-right: var(--nagaya-fee-amount-gap);
}
/* 第二行起要把分隔线那 1px **加在行高之外**。
   未出账那页的行是 q-expansion-item，1px 落在外层、把那一格撑成 41；
   这边的行有 min-height 而且是 border-box，1px 被吃进 40 里 —— 于是五行下来
   两页差 4px。这一条就是补回那 1px */
.monthly-list .q-item + .q-item {
  min-height: calc(var(--nagaya-fee-row-h) + 1px);
}
.monthly-list .amount,
.section-head .amount {
  font-size: var(--nagaya-fee-amount-fs);
  font-variant-numeric: tabular-nums;
}
/* 自己那笔：这一屏最该一眼看到的东西 */
.mine { font-weight: 600; }
.mine-label {
  font-size: var(--nagaya-fs-label);
  font-weight: 400;
  color: var(--nagaya-ink-2);
}
.mine-figure {
  font-size: var(--nagaya-fs-figure);
  line-height: 1.15;
  letter-spacing: -0.02em;
}
.mine.owe { color: var(--nagaya-neg); }
.mine.owed { color: var(--nagaya-pos); }
/* 结清了的那张：数字划掉。颜色留着 —— 还看得出当初是应收还是应付 */
.mine.done { text-decoration: line-through; }

/* ---------------------------------------------------- 每人那块的发散条 */
.axis-hint {
  display: flex;
  justify-content: space-between;
  padding: 0 16px 4px;
  font-size: 11px;
}
.axis-list { position: relative; }
/* 贯穿三行的零轴。画在列表上而不是每行上，三行才是同一条线 */
.axis-list::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--nagaya-line-2);
  pointer-events: none;
}
.axis-row { position: relative; overflow: hidden; }
/* **一条细横杠，不是一块底色。** 铺满整行高的填充会被读成「这一行被选中了」
   或者「进度 70%」；压成 6px 贴在行底、配上贯穿三行的那条中轴，
   它就只能被读成一张图：左边是要付，右边是要收，谁长谁欠得多 */
.axis-fill {
  position: absolute;
  bottom: 6px;
  height: 6px;
  border-radius: 3px;
  pointer-events: none;
}
/* 内容得压在填充之上 */
.axis-row > .q-item__section { position: relative; }

/* 主操作条：压在底部 Tab 之上 */
.actions :deep(.q-btn) { min-height: 44px; }
/* 两块严格各占一半。用 grid 而不是 flex：flex 下两边算出来的 flex 一样，
   实测仍然是 188/156，内容宽度还在暗中起作用；grid 的 1fr 1fr 是确定的 */
.actions > * { min-width: 0; }
/* 已出的账单右边这一半：写状态，不做成禁用按钮 ——
   禁用按钮看着还是个按钮，会让人反复点它找反应 */
.issued {
  min-height: 44px;
  border-radius: 4px;
  background: #f2f2f5;
  color: #9e9e9e;
  /* 字号/字重/行高/图标间距全部照抄 q-btn 的实测值：外框早就各占一半了，
     里面不抄的话左右两块字一大一小、一粗一细，看着还是不一样大 */
  font-size: 14px;
  font-weight: 500;
  line-height: 24px;
}
.issued :deep(.q-icon) { margin-right: 12px; }
.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(var(--nagaya-footer-h) + env(safe-area-inset-bottom));
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  /* 页面收到 --nagaya-max-w 居中，这条压在它上面的操作栏也得跟着收，
     否则宽屏上按钮会跑到内容外面去 */
  padding: 8px max(12px, calc((100% - var(--nagaya-max-w)) / 2));
  background: #fff;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
.page {
  /* 给固定操作条留位，否则滚到底时最后一块会被它盖住 */
  padding-bottom: calc(var(--nagaya-footer-h) + 78px + env(safe-area-inset-bottom));
}
.bill-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
  user-select: all;
}
</style>
