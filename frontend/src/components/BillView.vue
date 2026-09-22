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
      <!-- 头卡片的骨架和真卡片同一套行高（head-top / head-meta / mine），
           数据到了原地填进去，下面那块不跳 -->
      <div class="bill-section head">
        <div class="head-top row items-center"><q-skeleton type="text" width="40%" height="22px" /></div>
        <div class="head-meta row items-center"><q-skeleton type="text" width="55%" height="14px" /></div>
        <div class="mine settled">
          <div class="mine-label"><q-skeleton type="text" width="18%" height="14px" /></div>
          <div class="mine-figure"><q-skeleton type="text" width="45%" height="28px" /></div>
        </div>
      </div>
      <!-- 固定费那块也按真实结构摆：44 的标题条 + 五行 48、行间 1px 线 -->
      <div class="bill-section">
        <div class="section-head row items-center q-px-md">
          <q-skeleton type="text" width="30%" height="18px" />
        </div>
        <div v-for="n in 5" :key="n" class="skel-row row items-center q-px-md">
          <q-skeleton type="rect" height="36px" class="full-width" />
        </div>
      </div>
      <div class="bill-section q-pa-md">
        <q-skeleton v-for="n in 3" :key="n" type="rect" height="56px" class="q-mb-sm" />
      </div>
    </div>

    <!-- 用 v-if 而不是 v-else：上面那句多了个「还在加载」的条件，
         两个都不成立时（冷启动的头几十毫秒）这一页就该是干净的 -->
    <template v-if="bill">
      <!--
        头一张卡片：这是哪张单子、一共多少、**我**要做什么。

        **未出账和已出账两页，这一块必须一样高**（第 5 条）：两页来回切的时候，
        下面「本期固定费」那块不该上下跳。所以三行各自钉死行高、一律不折行：
          第一行  单子的名字 ………… 合计
          第二行  覆盖的日期 ………… 状态（笔数 / 已结清 / 未结清 / 出账后改过）
          第三块  我这期：一行标签 + 一行结论
        原来会让它变高的三样东西都收进了这个框里：
          * 「要转给两个人」那句整句 28px，会折成两行 —— 现在标签归标签，
            两笔收成一行、字小一号；
          * 「出账后被改过」那条橙色横幅 —— 现在是第二行里一颗橙色的签，
            点开看全文（复制出去的文本里照旧带着整句）；
          * 我不在这张单子上（比如后来才搬进来）时，那一块原来整个不见。
      -->
      <div class="head bill-section">
        <div class="head-top row items-center no-wrap">
          <!-- 出过的单子：名字就是翻页入口。原来「以前」单独占一个页签，
               而「挑某个月」才是常态、「逐张翻」很少 —— 并进来之后
               这一屏永远是一张账单，形状不再变来变去 -->
          <button v-if="!bill.is_draft" class="pick head-title">
            <span class="ellipsis">{{ statementLabel(bill) }}</span>
            <q-icon name="expand_more" size="20px" class="text-grey-6" />
            <q-menu anchor="bottom left" self="top left" max-height="60vh">
              <q-list separator style="min-width: 260px">
                <q-item
                  v-for="st in bills.statements ?? []"
                  :key="st.id"
                  v-close-popup
                  clickable
                  :active="st.id === bill.statement_id"
                  active-class="picked"
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
                    <span v-if="st.settled" class="chip ok q-mt-xs">{{ t('bill.settledBadge') }}</span>
                    <div v-else class="text-caption text-grey-6 q-mt-xs">{{ t('bill.unsettled') }}</div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </button>
          <div v-else class="head-title ellipsis">{{ t('bill.draft') }}</div>
          <q-space />
          <!-- 「这一期一共花了多少」降级：它谁也不用去做什么。
               真正要做的那件事（我要给谁多少）挪到下面用 28px 印 -->
          <div class="total-label">{{ t('bill.total') }}</div>
          <div class="total num">{{ formatYen(bill.total_expense) }}</div>
        </div>
        <div class="head-meta row items-center no-wrap">
          <div class="ellipsis">
            <template v-if="bill.covers_from">
              {{ shortRange(bill.covers_from, bill.covers_to) }}
            </template>
          </div>
          <q-space />
          <!-- 这一格就是「这张单子现在什么状态」：草稿报笔数，出过的账单
               结清了给绿签、没结清给橙字 -->
          <div v-if="bill.is_draft" class="no-wrap">
            <span v-if="bill.prev_cut_at" class="q-mr-sm">
              {{ t('bill.lastCut', { label: statementLabel({ label: bill.prev_label, cut_at: bill.prev_cut_at }) }) }}
            </span>
            {{ t('bill.entryCount', { n: bill.entry_count }) }}
          </div>
          <template v-else>
            <!-- 不锁历史，但改动必须可见：否则下一张的「上期结转」没人解释得清。
                 **这颗签是那条规矩在屏幕上的凭证**（复制出去的文本里是整句），
                 点开看全文 -->
            <button
              v-if="bill.edited_after_cut"
              class="chip warn edited q-mr-xs"
              type="button"
              @click="showEdited = true"
            >
              <q-icon name="error_outline" size="14px" />
              {{ t('bill.editedChip') }}
            </button>
            <span v-if="bill.settled" class="chip ok">{{ t('bill.settledBadge') }}</span>
            <span v-else class="text-warning">{{ t('bill.unsettled') }}</span>
          </template>
        </div>

        <!-- 自己那笔摆在最显眼处。读账单的人要的就是这一个数字，
             埋在半屏之下的话，他先看到的全是别人的录入框。
             **结清了就划掉**：钱早就转过了，一个亮着的「你应收 ¥84,106」
             会让人以为现在还欠着 -->
        <div
          class="mine"
          :class="[minePart.tone, { done: !bill.is_draft && myLeft === 0, multi: minePart.multi }]"
        >
          <div class="mine-label">{{ minePart.label }}</div>
          <!-- 要转给好几个人：一笔一行（两行 × 18px 正好还是 36px，头卡片不变高）。
               并成一行加省略号的话，第二个人的金额在 375 宽就被截没了 ——
               人照着第一个名字转完钱，就以为这期结清了 -->
          <div v-if="minePart.lines" class="mine-figure lines num">
            <div v-for="(ln, i) in minePart.lines" :key="i" class="ellipsis">{{ ln }}</div>
          </div>
          <div v-else class="mine-figure num ellipsis">{{ minePart.figure }}</div>
        </div>
      </div>

      <q-dialog v-model="showEdited">
        <q-card style="width: 92vw; max-width: 400px">
          <q-card-section class="row items-center no-wrap q-pb-none">
            <q-icon name="error_outline" size="22px" class="text-warning q-mr-sm" />
            <div class="text-subtitle1 text-weight-medium">{{ t('bill.editedChip') }}</div>
          </q-card-section>
          <q-card-section>{{ editedText }}</q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps color="primary" :label="t('common.confirm')" />
          </q-card-actions>
        </q-card>
      </q-dialog>

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
        <q-list separator>
        <q-item
          v-for="row in bill.members"
          :key="row.member_id"
          class="member-row"
          :class="{ me: row.member_id === auth.me?.id }"
        >
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
              <div v-else class="row items-baseline no-wrap" :class="row.closing < 0 ? 'text-negative' : 'text-positive'">
                <span class="text-caption text-grey-6 q-mr-xs">
                  {{ row.closing > 0 ? t('bill.toReceive') : t('bill.toPay') }}
                </span>
                <span class="closing num">{{ formatYen(Math.abs(row.closing)) }}</span>
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
              <span v-if="row.owed" class="b-owed">
                <i>{{ t('bill.owed') }}</i><b class="num">{{ formatYen(row.owed) }}</b>
              </span>
              <span v-if="row.paid" class="b-paid">
                <i>{{ t('bill.paid') }}</i><b class="num">{{ formatYen(row.paid) }}</b>
              </span>
              <span v-if="row.transferred_out" class="b-tx">
                <i>{{ t('bill.prepaid') }}</i><b class="num">{{ formatYen(row.transferred_out) }}</b>
              </span>
              <span v-if="row.transferred_in" class="b-tx">
                <i>{{ t('bill.received') }}</i><b class="num">{{ formatYen(row.transferred_in) }}</b>
              </span>
              <span v-if="row.opening" class="b-carry">
                <i>{{ t('bill.carried') }}</i><b class="num">{{ formatYen(row.opening) }}</b>
              </span>
            </div>
          </q-item-section>
        </q-item>
        </q-list>
      </div>

      <div class="bill-section plan">
        <q-item dense class="section-head">
          <q-item-section>
            {{ bill.transfers.length ? t('bill.plan', { n: bill.transfers.length }) : t('bill.planEmpty') }}
          </q-item-section>
        </q-item>
        <div class="q-px-md q-pb-md">
        <q-card v-for="(tr, i) in bill.transfers" :key="i" flat class="transfer q-mb-sm">
          <q-card-section class="row items-center no-wrap q-py-sm q-px-md">
            <div class="pair row items-center no-wrap q-mr-md">
              <MemberAvatar :member-id="tr.from_id" size="28px" />
              <q-icon name="arrow_forward" size="14px" class="text-grey-6 q-mx-xs" />
              <MemberAvatar :member-id="tr.to_id" size="28px" />
            </div>
            <div class="col" style="min-width: 0">
              <div class="text-caption text-grey-7 ellipsis">
                {{ nameOf(tr.from_id) }} → {{ nameOf(tr.to_id) }}
              </div>
              <div class="tr-amount num">{{ formatYen(tr.amount) }}</div>
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
           「出账单」压在最底下的话每次都要先滚到底。
           **画在底栏里**（Teleport 到 .footer-slot），不自己 fixed 定位 ——
           理由见 AddEntryPage 那条：量底栏高度那套在首帧会量早一拍 -->
      <Teleport to=".footer-slot">
      <div class="actions">
        <q-btn
          outline
          color="primary"
          no-caps
          icon="content_copy"
          :label="t('bill.copy')"
          @click="copyBill()"
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
      </Teleport>

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
          <q-btn unelevated no-caps color="primary" :label="t('bill.copy')" @click="copyBill(cutResult)" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- 剪贴板在非 HTTPS 下用不了（局域网 http 访问就会撞上），退回让人手动长按复制 -->
    <q-dialog v-model="showFallback">
      <q-card style="width: 92vw">
        <q-card-section class="text-caption text-grey-7">{{ t('bill.copyFallback') }}</q-card-section>
        <q-card-section>
          <pre class="bill-text">{{ fallbackText }}</pre>
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
import type { Bill, BillTransfer, Entry, Statement } from 'src/api/types'
import { leftOf as leftOfPlan } from 'src/core/transfers'
import { toHalfWidth } from 'src/digits'
import { escapeHtml } from 'src/html'
import { FALLBACK } from 'src/palette'
import MemberAvatar from 'src/components/MemberAvatar.vue'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { todayJst } from 'src/date'
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
/** 手动复制那个框里摆的字：刚才要复制的那一张，不一定是屏幕上这张 */
const fallbackText = ref('')
const cutResult = ref<Bill | null>(null)

const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)

/** 头卡片上的日期：今年的省掉年份（8/30），窄屏和日文下第二行才放得下两头 */
const thisYear = todayJst().slice(0, 4)
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`
/** 两头同一年的旧账单：年份只写一次（2025/8/30 〜 9/23）；跨年的照写全 */
function shortRange(from: string, to: string | null): string {
  const end = to ?? from
  const sameYear = from.slice(0, 4) === end.slice(0, 4)
  const head = from.slice(0, 4) === thisYear && sameYear ? md(from) : sameYear ? `${from.slice(0, 4)}/${md(from)}` : from
  const tail = sameYear ? md(end) : end
  return t('bill.coversRange', { from: head, to: tail })
}

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

/** 这一笔**此刻**还该转多少。口径见 src/core/transfers.ts */
function leftOf(tr: BillTransfer, i: number): number {
  return bill.value ? leftOfPlan(bill.value, tr, i) : 0
}

/** 卡片上那行小字：转了多少、还差多少、或者「已经不用转了」 */
function noteOf(tr: BillTransfer, i: number): string {
  return bill.value ? noteFor(bill.value, tr, i) : ''
}
/** 同上，但指名是哪一张 —— 出账完成那个弹窗复制的是**新出的那张**，不是屏幕上这张 */
function noteFor(b: Bill, tr: BillTransfer, i: number): string {
  if (b.settled_transfers[i]) return ''
  const paid = b.settled_paid?.[i] ?? 0
  const left = leftOfPlan(b, tr, i)
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
const supersededIn = (b: Bill) =>
  !b.is_draft && b.transfers.some((tr, i) => !b.settled_transfers[i] && leftOfPlan(b, tr, i) === 0)
const superseded = computed(() => (bill.value ? supersededIn(bill.value) : false))

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

  // 方案里没有我这条边：只说这张单子上我是什么状态（按此刻，见 effClosing）
  const eff = effClosing(b, row)
  if (eff === 0) return t('bill.youSettled')
  if (eff > 0) return t('bill.youReceive', { amount: formatYen(eff) })
  return t('bill.youOwe', { amount: formatYen(Math.abs(eff)) })
})

/**
 * 方案里没有我这条边时，我在这张单子上**此刻**还差多少。和 leftOf 同一个「两头取小」：
 *   * 不超过这张单子自己的数 —— 翻七月那张，不该跳出今天的欠款；
 *   * 此刻已经两清（或者方向反过来了）就是 0 —— 原来直接印这张单子的 closing，
 *     钱早就转过了，大字还写着「你应付 ¥X」
 */
function effClosing(b: Bill, row: { member_id: number; closing: number }): number {
  const live = Number(b.live_closing?.[String(row.member_id)] ?? row.closing)
  if (Math.sign(live) !== Math.sign(row.closing)) return 0
  return Math.sign(row.closing) * Math.min(Math.abs(row.closing), Math.abs(live))
}

/**
 * 最显眼那行字，拆成「标签 + 数字」两段。
 * 多笔要转时没法拆（是一串「给谁多少、给谁多少」），那就整句照旧，只是小一号。
 */
/**
 * 屏幕上最重要的那两行：一行标签，一行结论。
 *
 * **三档都必须有标签行。** 「已结清」那一档原来只有结论没有标签，于是这一块
 * 比别的档矮 20px —— 在未出账和已出账之间来回切，下面整块跟着上下跳。
 * tone 也在这儿定：结清了是中性色，不能沿用「欠钱」那个红。
 */
type MinePart = {
  label: string
  figure: string
  tone: 'owe' | 'owed' | 'settled'
  multi?: boolean
  /** 要转给好几个人时一笔一行 */
  lines?: string[]
}
const minePart = computed<MinePart>(() => {
  const row = mine.value
  const b = bill.value
  const settled = {
    label: t('bill.youSettledLabel'),
    figure: t('bill.youSettled'),
    tone: 'settled' as const,
  }
  // 我不在这张单子上（后来才搬进来的人翻旧账单）：这一块照样占着位置，
  // 否则这一页比别的页矮一截，两页来回切时底下整块上下跳
  if (!row || !b) return { label: t('bill.youSettledLabel'), figure: t('bill.youNotIn'), tone: 'settled', multi: true }
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
      tone: 'owe',
    }
  }
  if (inc.length && !out.length) {
    return {
      label: t('bill.youReceiveLabel'),
      figure: formatYen(inc.reduce((n, x) => n + x.left, 0)),
      tone: 'owed',
    }
  }
  if (!out.length && !inc.length && b.transfers.some((tr) => tr.from_id === me || tr.to_id === me)) {
    return settled
  }
  if (!b.transfers.some((tr) => tr.from_id === me || tr.to_id === me)) {
    const eff = effClosing(b, row)
    if (eff === 0) return settled
    return {
      label: eff > 0 ? t('bill.youReceiveLabel') : t('bill.youOweLabel'),
      figure: formatYen(Math.abs(eff)),
      tone: eff > 0 ? 'owed' : 'owe',
    }
  }
  // 要转给好几个人：**得全列出来**（原来只取第一条、却把欠款总额安在那个人头上）。
  // 收成一行、字小一号 —— 整句 28px 会折成两行，把这一块撑高
  const pay = rows.filter((x) => x.tr.from_id === me)
  if (pay.length === 1) {
    // 只转给一个人（同时还有人要转给我）：照单笔那一档印，字不缩
    return {
      label: t('bill.youPayLabel', { to: nameOf(pay[0]!.tr.to_id) }),
      figure: formatYen(pay[0]!.left),
      tone: 'owe',
    }
  }
  if (pay.length) {
    return {
      label: t('bill.youPayListLabel'),
      figure: pay.map((x) => `${nameOf(x.tr.to_id)} ${formatYen(x.left)}`).join('  ·  '),
      // 三个人合租最多欠两个人；万一更多，头两行照印，剩下的看下面的转账方案
      lines: pay.slice(0, 2).map((x) => `${nameOf(x.tr.to_id)} ${formatYen(x.left)}`),
      tone: 'owe',
      multi: true,
    }
  }
  return { label: t('bill.youSettledLabel'), figure: mineText.value, tone: row.closing < 0 ? 'owe' : 'owed', multi: true }
})

/** 「出账后改过」那颗签点开之后的全文。和复制出去的文本是同一句 */
const showEdited = ref(false)
const editedText = computed(() => {
  const e = bill.value?.edited_after_cut
  if (!e) return ''
  return e.from_earlier
    ? t('bill.driftedFromEarlier')
    : t('bill.editedAfterCut', {
        n: e.count,
        frozen: formatYen(e.frozen_total ?? 0),
        live: formatYen(e.live_total),
      })
})

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
  e.kind === 'expense' ? (categoryOfEntry(e)?.color ?? FALLBACK) : KIND_COLOR[e.kind]
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

/**
 * 贴进 LINE 的纯文本。在前端拼，所以自动跟随界面语言（SPEC §7.5）。
 * **指名是哪一张**：出账完成那个弹窗里的「复制」要的是刚出的那张（cutResult），
 * 而屏幕上这时正在重取 —— 原来复制的是屏幕上的视图，取数那几百毫秒里是空串，
 * 还照样提示「已复制」
 */
function textOf(b: Bill): string {
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
      const n = noteFor(b, tr, i)
      const note = done ? `  ${t('bill.planDone')}` : n ? `  ${n}` : ''
      lines.push(`  ${nameOf(tr.from_id)} → ${nameOf(tr.to_id)}  ${formatYen(tr.amount)}${note}`)
    }
  } else {
    lines.push(t('bill.planEmpty'))
  }
  if (supersededIn(b)) lines.push(t('bill.planSuperseded'))
  return lines.join('\n')
}
const billText = computed(() => (bill.value ? textOf(bill.value) : ''))

/** 复制某一张。不给就是屏幕上这张；文字是空的（还在取数）就什么都不做，不报「已复制」 */
async function copyBill(of?: Bill | null) {
  const text = of ? textOf(of) : billText.value
  if (!text) return
  fallbackText.value = text
  try {
    await navigator.clipboard.writeText(text)
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
  if (busy.value !== null) return
  const left = leftOf(tr, index)
  const statementId = bill.value?.is_draft ? null : (bill.value?.statement_id ?? null)
  // 「确定」连点两下，onOk 会跑两遍 —— 第二遍直接丢掉
  let fired = false
  $q.dialog({
    title: t('bill.done'),
    message: t('bill.doneHint', { from: nameOf(tr.from_id), to: nameOf(tr.to_id) }),
    // **不用 type=number**：那样「10,000」会被当成没填，「10.000」会记成 ¥10。
    // 文本框 + 数字键盘，千分位和空格下面自己擦
    prompt: { model: left.toLocaleString('en-US'), type: 'text', inputmode: 'numeric' },
    cancel: true,
  }).onOk(async (value: string) => {
    if (fired) return
    fired = true
    // 先把逗号和空格擦掉：整屏的金额都写成 ¥10,000，照着屏幕打回去是最自然的动作
    // 千分位的逗号（和点）擦掉；**别的小数点不当千分位** —— 日元没有小数，
    // 「5000.00」原来会被擦成 500,000。整串是「1,234,567 / 1.234.567」这种分组才擦点
    const raw = toHalfWidth(String(value)).replace(/[\s．]/g, (c) => (c === '．' ? '.' : ''))
    const grouped = /^\d{1,3}([.,]\d{3})+$/.test(raw)
    const plain = /^\d+$/.test(raw.replace(/,/g, ''))
    const amount = grouped || plain ? Number(raw.replace(/[.,]/g, '')) : NaN
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
      await ledger.confirmTransfer({
        statement_id: statementId,
        from_id: tr.from_id,
        to_id: tr.to_id,
        amount,
        expect_left: left,
        date: todayJst(),
      })
    } catch (e) {
      // 有人刚记过这一笔（另一方也点了、或者另一台设备）：不重复记，
      // 重取之后把「现在还差多少」说出来
      if (e instanceof ApiError && e.code === 'transfer_changed') {
        await load().catch(() => {})
        const now = Number((e.detail as { left?: number } | undefined)?.left ?? 0)
        $q.notify({
          type: 'warning',
          timeout: 5000,
          message: now > 0 ? t('bill.transferChanged', { left: formatYen(now) }) : t('bill.transferDoneElsewhere'),
        })
      } else {
        $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
      }
      busy.value = null
      return
    }
    // **记上了就是记上了。** 后面那次重取失败（断网）不许报成「没记上」——
    // 那样人会再按一次，又是一笔
    $q.notify({
      type: 'positive',
      timeout: 3000,
      message: t('bill.doneRecorded', {
        from: nameOf(tr.from_id),
        to: nameOf(tr.to_id),
        amount: formatYen(amount),
      }),
    })
    await load().catch(() => {})
    busy.value = null
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
  // 开 html 只为换行，每一段都先转义：固定费的名字是用户起的，
  // 带个 `<` 就会被当标签吞掉（见 src/html.ts）
  const hint = hints.map(escapeHtml).join('<br><br>')
  $q.dialog({
    title: t('bill.cut'),
    message: hint ? `${escapeHtml(t('bill.cutConfirm'))}<br><br>${hint}` : t('bill.cutConfirm'),
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
  column-gap: 16px;
  row-gap: 3px;
  margin-top: 4px;
  /* text-caption 自带 1.67 的行高，两行叠起来虚高 7px。
     这里是一块密排的数字，收到 1.4 正好 */
  line-height: 1.4;
}
/* **一格里标签靠左、数字靠右。**
   原来是「应担 ¥53,627」连着写、整体左对齐，于是三个人的数字左右错开，
   竖着比「谁垫得多」得一个一个读。靠右之后同一列的数字对齐，扫一眼就行 */
.breakdown > span {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  white-space: nowrap;
  min-width: 0;
}
.breakdown i { font-style: normal; color: var(--nagaya-ink-3); }
.breakdown b { font-weight: 400; color: var(--nagaya-ink-2); }
/* 这一行的结论。它是整块里唯一要人**照着做事**的数字，别和明细一个字号 */
.closing { font-size: var(--nagaya-fs-figure-s); font-weight: 600; letter-spacing: -0.01em; }
/* 「我」那一行。原来用 Quasar 的 bg-blue-1，蓝得压过了红绿两种金额色 */
.member-row.me { background: var(--nagaya-accent-bg); }
.member-row { padding-top: 10px; padding-bottom: 10px; }

/* 「已预付」和「已收到」互斥，共用第 2 行第 1 格 */
.b-owed { grid-area: 1 / 1; }
.b-paid { grid-area: 1 / 2; }
.b-tx { grid-area: 2 / 1; }
.b-carry { grid-area: 2 / 2; }
/* ---- 头一张卡片。三行各自钉死行高，两页才一样高（见模板上那段） ---- */
.head { padding: 14px 16px 16px; }
.head-top { height: 28px; }
.head-meta > .ellipsis { flex: 1 1 auto; min-width: 0; }
.head-title {
  min-width: 0;
  font-size: var(--nagaya-fs-title);
  font-weight: 600;
  line-height: 28px;
}
.total-label {
  margin-right: 6px;
  font-size: var(--nagaya-fs-meta);
  color: var(--nagaya-ink-3);
}
.total { font-size: var(--nagaya-fs-title); font-weight: 600; }
.head-meta {
  gap: 8px;                     /* 窄屏上两头的字别贴在一起 */
  height: 22px;
  margin-top: 2px;
  font-size: var(--nagaya-fs-meta);
  color: var(--nagaya-ink-3);
  white-space: nowrap;
}
/* 状态签：绿＝结清，橙＝出账后改过（点得开） */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 20px;
  padding: 0 8px;
  border: none;
  border-radius: var(--nagaya-r-pill);
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
}
.chip.ok { background: color-mix(in srgb, var(--nagaya-pos) 14%, transparent); color: var(--nagaya-pos); }
.chip.warn { background: var(--nagaya-warn-bg); color: var(--nagaya-warn); }
.chip.edited { cursor: pointer; }
/* 标题当按钮用，但看着还得是标题。
   **只中和浏览器给 button 的默认字体族**，别写 `font: inherit` */
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
.skel-row { height: var(--nagaya-fee-row-h); }
.skel-row + .skel-row { height: calc(var(--nagaya-fee-row-h) + 1px); border-top: 1px solid var(--nagaya-line); }
/* 翻单子那个菜单里，正在看的那一张 */
.picked { background: var(--nagaya-accent-bg); }
/* 本期固定费：和未出账那页的面板对齐到同一套尺寸 —— 行高 40、金额 16px、
   右边留 50px（那页那儿是展开箭头，这页没有，用内边距占出来） */
.monthly-list .q-item {
  min-height: var(--nagaya-fee-row-h);
  /* 多出来的 10px ＝ 未出账那页输入框的内边距：数字在框里离右边 10px */
  padding-right: calc(var(--nagaya-fee-amount-gap) + 10px);
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
.section-head .amount { padding-right: 10px; }
/* 自己那笔：这一屏最该一眼看到的东西。标签一行、结论一行，高度钉死 */
.mine {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--nagaya-line);
  font-weight: 600;
}
.mine-label {
  height: 18px;
  font-size: var(--nagaya-fs-label);
  font-weight: 400;
  line-height: 18px;
  color: var(--nagaya-ink-2);
}
.mine-figure {
  height: 36px;
  font-size: var(--nagaya-fs-figure);
  line-height: 36px;
  letter-spacing: -0.02em;
}
/* 只是说一句话（不在这张单子上）：同一行里放下，字小一号 */
.mine.multi .mine-figure { font-size: 20px; letter-spacing: 0; }
/* 要转给好几个人：一笔一行，两行加起来还是 36px */
.mine .mine-figure.lines { font-size: 15px; line-height: 18px; letter-spacing: 0; }
.mine.owe { color: var(--nagaya-neg); }
.mine.owed { color: var(--nagaya-pos); }
/* 结清了是中性色：红＝还欠着，绿＝还有人欠你，而这一档两样都不是 ——
   「已结清」印成红的，等于用报警色说「没事了」 */
.mine.settled { color: var(--nagaya-ink-2); }
.mine.settled.done { text-decoration: none; }
/* 结清了的那张：数字划掉。颜色留着 —— 还看得出当初是应收还是应付 */
.mine.done { text-decoration: line-through; }

/* 转账方案：一笔一块浅底，两个头像中间一个箭头，一眼看出谁给谁 */
.transfer {
  background: var(--nagaya-fill);
  border-radius: var(--nagaya-r-md);
}
.tr-amount { font-size: var(--nagaya-fs-figure-s); font-weight: 600; line-height: 1.3; white-space: nowrap; }
/* 窄屏（或者日文）：头像对收起来 —— 名字那行已经写着 A → B，
   留着它的话金额会被「确认已完成」压住，要转多少读不出来 */
@media (max-width: 429px) {
  .transfer .pair { display: none; }
}

/* 主操作条：压在底部 Tab 之上 */
.actions :deep(.q-btn) { min-height: 48px; font-size: 15px; font-weight: 600; }
/* 两块严格各占一半。用 grid 而不是 flex：flex 下两边算出来的 flex 一样，
   实测仍然是 188/156，内容宽度还在暗中起作用；grid 的 1fr 1fr 是确定的 */
.actions > * { min-width: 0; }
/* 已出的账单右边这一半：写状态，不做成禁用按钮 ——
   禁用按钮看着还是个按钮，会让人反复点它找反应 */
.issued {
  min-height: 48px;
  border-radius: 14px;
  background: var(--nagaya-fill);
  color: var(--nagaya-ink-4);
  /* 字号/字重/行高/图标间距全部照抄 q-btn 的实测值：外框早就各占一半了，
     里面不抄的话左右两块字一大一小、一粗一细，看着还是不一样大 */
  font-size: 15px;
  font-weight: 600;
  line-height: 24px;
}
.issued :deep(.q-icon) { margin-right: 12px; }
/* 画在底栏里：不需要 fixed、不需要 z-index、也不用和底栏叠 1px 防缝 */
.actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  /* 页面收到 --nagaya-max-w 居中，这条压在它上面的操作栏也得跟着收，
     否则宽屏上按钮会跑到内容外面去 */
  padding: 8px max(16px, calc((100% - var(--nagaya-max-w)) / 2 + 16px)) 4px;
}
/* 下边距不用自己留：操作条在底栏里，Quasar 会把底栏总高算进页面容器 */
.bill-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
  user-select: all;
}
</style>
