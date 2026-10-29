export type EntryKind = 'expense' | 'income' | 'settlement'
type Lang = 'zh' | 'ja'

export interface Member {
  id: number
  name: string
  display_name: string
  color: string
  display_order: number
  joined_on: string
  left_on: string | null
  lang: Lang
  is_active: boolean
  /** 头像的地址（带版本号，图由 src/avatars.ts 取）。没设过就是 null，界面退回那个带首字的色圆 */
  avatar: string | null
  avatar_version: number
  /** 离家模式：新记「离家时不算的那一类」（设置 away_category_id）默认不算他。人还在籍 */
  away: boolean
}

/** 自己加的备忘条目。固定费那几项的备忘写在 Category.note 上 */
export interface Memo {
  id: number
  title: string
  body: string
  display_order: number
  updated_at: string
}

export interface Category {
  id: number
  name: string
  icon: string
  color: string
  default_rule_json: Record<string, unknown> | null
  /** 每月一次的固定项：不在日常记账网格里，出账单时顺手填 */
  monthly: boolean
  display_order: number
  archived: boolean
  /** 这一项的常驻备忘：什么时候收、从谁的卡扣、合同哪天到期 */
  note: string
  /** 这一项固定费默认谁垫。分类的常驻属性，不是每期临时决定的 */
  default_payer_id: number | null
  /** 每期金额都一样：出账前自动按上期金额记上。默认关 */
  same_as_last: boolean
}

export interface Entry {
  id: number
  kind: EntryKind
  date: string
  title: string
  amount_jpy: number
  category_id: number | null
  payer_id: number
  to_member_id: number | null
  statement_id: number | null
  statement_label: string | null
  /** 所属那张账单的出账时刻（naive UTC）。老账单 label 是空的，名字靠它渲染 */
  statement_cut_at?: string | null
  split_rule_json: Record<string, unknown>
  note: string
  created_by: number | null
  created_at: string
  updated_at: string
  version: number
  /** 分摊快照 {member_id: 日元}。这才是钱的真相 */
  shares: Record<string, number>
}

/** 一张出过的账单。线是点「出账单」那一刻划的，不是日历划的 */
export interface Statement {
  id: number
  label: string
  cut_at: string
  covers_from: string | null
  covers_to: string | null
  cut_by: number | null
  /** 列表页每行直接显示，省得为每张单子再拉一次账单接口 */
  total_expense: number
  settled: boolean
}

/** 账单上的一行人。钱是全局累计的，这里拆成「期初 + 本期 + 已收付」 */
interface BillRow {
  member_id: number
  opening: number
  owed: number
  paid: number
  transferred_out: number
  transferred_in: number
  closing: number
}

export interface BillTransfer { from_id: number; to_id: number; amount: number }

/** 一张账单的全貌。草稿（还没出账的流水）和出过的单子是同一个形状 */
export interface Bill {
  statement_id: number | null
  label: string | null
  is_draft: boolean
  cut_at: string | null
  covers_from: string | null
  covers_to: string | null
  edited_after_cut: {
    count: number
    frozen_total: number | null
    live_total: number
    /** 这张单子自己一笔没动，是更早那张被改了才漂的 */
    from_earlier: boolean
    /** 谁受影响、差多少：冻结时的 closing 和此刻的不一样的那几个人（一样的不列） */
    members?: { member_id: number; frozen_closing: number; live_closing: number }[]
    /** 改了哪几笔、谁改的。只改了分摊的那笔前后金额一样 —— 别再写成「当初 ¥X，现在 ¥X」 */
    entries?: EditedEntry[]
    /** from_earlier 时是被哪几张更早的单子带着漂的；查不出来是空列表 */
    sources?: number[]
  } | null
  /** 已出的账单上「本期固定费」列哪几项（没记钱的按 ¥0 列）。草稿是 null —— 那页用面板 */
  monthly_ids?: number[] | null
  prev_cut_at: string | null
  prev_label: string | null
  days_since_prev_cut: number | null
  suggest_monthly: boolean
  settled: boolean
  settled_transfers: boolean[]
  /** 方案里每一笔**已经转过去多少**。界面拿它算「还差多少」，别再预填全额 */
  settled_paid: number[]
  total_expense: number
  total_income: number
  entry_count: number
  members: BillRow[]
  /** 出账那一刻冻结的方案。**这是历史陈述，不是行动指示** */
  transfers: BillTransfer[]
  /**
   * 「此刻」该谁给谁多少 —— 和「未出账」那页看到的是同一份。
   *
   * 大字、进度、按钮都归它管：冻结方案里那一对，后来可能再也不会走钱
   * （大家换了现金、并单转、经第三人），照着它行动就是凭空造一笔债。
   */
  live_transfers: BillTransfer[]
  /** 「此刻」每个人的净额。键是 member_id */
  live_closing: Record<string, number>
  /** 帮买那几笔（付款人不担、全算一个别人的支出）。合计里照算，账单上注一句「含帮买」；老缓存里没有 */
  help_total?: number
  help_items?: { entry_id: number; payer_id: number; for_id: number; amount: number; title: string }[]
  simplified: boolean
  /**
   * 最近出的那张账单的 id，一张都没出过是 0。出账、出账前的「先按上期记上」带着它回去
   * （after_statement_id）：两台手机同时出账时，后到的那台撞 409 bill_changed，不再多出一张只有房租的单子
   */
  prev_statement_id?: number
  /** 出账前请人看一眼的几类疑点。**只有草稿有**，出过的单子是 null。只提示，不替人改 */
  review?: BillReview | null
  /** 「上期结转」跟着一张已出的账单漂了（那张出账后被改过）：指向它。只有草稿有 */
  opening_drift?: { statement_id: number; label: string } | null
}

/** 「出账后被改过」里的一笔 */
export interface EditedEntry {
  entry_id: number
  title: string
  category_id: number | null
  /** 出账那一刻 / 此刻的金额。审计日志里查不到就是 null */
  before_amount: number | null
  after_amount: number | null
  deleted: boolean
  /** 谁改的（member_id） */
  by: number[]
}

/** 草稿账单上的疑点。每一类都是弱证据 —— 只亮出来请人看，不拦、不改 */
export interface BillReview {
  /** 搬走之后还在分摊里（left_but_charged），或入住之后没算进去（joined_not_charged） */
  membership_gaps: {
    entry_id: number
    member_id: number
    type: 'left_but_charged' | 'joined_not_charged'
    share: number
  }[]
  /** 同类、同金额、日期挨着的两笔（两台手机各记了同一张小票） */
  possible_duplicates: { a: number; b: number }[]
  /** 比同分类近期中位数大出好几倍的那笔（多打一个 0、把房租记进「其他」）。只判偏大那一侧 */
  outliers: { entry_id: number; median: number; ratio: number }[]
}

/** POST /api/monthly/carry 的回应：记了哪几笔（垫付人一起说出来）、哪几项没敢记 */
export interface CarryResult {
  created: { category_id: number; name: string; amount: number; payer_id?: number | null }[]
  failed: { category_id: number; name: string; reason: string; detail?: Record<string, unknown> }[]
}

/** 固定费面板的一行。`amount === null` ＝ 本期还没录，灰色占位不算数 */
export interface MonthlyRow {
  category_id: number
  name: string
  icon: string
  color: string
  default_rule_json: Record<string, unknown> | null
  /** 这一项默认谁垫 */
  default_payer_id: number | null
  /** 上期那一笔是谁垫的（还在籍才有）。没录的行按它预填 */
  last_payer_id?: number | null
  /** 每期金额都一样 */
  same_as_last: boolean
  /** 这一项已经删掉（归档）了，只是本期还挂着钱，所以那一行还留着 */
  archived: boolean
  entry_id: number | null
  amount: number | null
  version: number | null
  rule: Record<string, unknown> | null
  date: string | null
  /** 本期这个分类一共有几笔。>1 说明这一行没显示全 */
  entry_count: number
  /** 点「按上期记上」会记多少。草稿里开了「和上期一样」、本期还没处理过的才有 */
  carry_amount?: number | null
  /**
   * 开了「和上期一样」却不能照抄的原因，得人自己填：
   * payer_left（上期垫付人搬走了）/ rule_stale（人变了，上期分摊对不上）/
   * last_multi（上期这一项记了好几笔，不知道该照哪一笔）
   */
  carry_blocked?: string | null
  /** last_multi 时上期那几笔的笔数和合计（只给开了「和上期一样」的项，D21） */
  carry_blocked_detail?: { count: number; total: number } | null
  /** 点「照上期」会记成谁垫的 —— 后端照着它记，界面别自己推算 */
  carry_payer_id?: number | null
  /** 上期这一项多少钱。只有开了「和上期一样」的才给，本期填没填都给（展开区那颗按钮一直在） */
  last_amount?: number | null
  /** 本期已录那一笔是谁垫的（没录是 null）。和 entry_id 同一次查出来，不再去流水里借 */
  payer_id?: number | null
  /** 没录的行：起步分摊点了名、却没写到这几个今天在籍的人（照这样存他们担 0） */
  rule_missing_member_ids?: number[]
  /** 最近几期金额都一样、却没开「和上期一样」：提示一下（不带金额，D21）。只有草稿有 */
  suggest_same_as_last?: boolean
  /** 草稿里记在日常分类、备注带着这一项名字的账 —— 可能就是它，别再填一遍。只有草稿有 */
  maybe_elsewhere?: { entry_id: number; amount: number; category_name: string | null; title: string }[]
  /** 上次记这一项之后出过几次账 / 这一项平常隔几次出账才有一笔（出账时区分「忘了」和「这期本来没有」） */
  cuts_since_last?: number | null
  typical_gap?: number | null
}

export interface MonthlyData {
  default_date: string
  rows: MonthlyRow[]
  /** 本期固定费合计。**由后端给**：面板一行只显示得下一笔，同一分类有两笔时行加不出正确的数 */
  total: number
}

export interface Setting {
  key: string
  value: unknown
  type: string
  /** 通用面板里不渲染它 —— 有专门的卡片管（App 名字和图标） */
  hidden?: boolean
  note_zh: string
  note_ja: string
  options: unknown[] | null
  min: number | null
  max: number | null
}

export interface EntryPayload {
  kind: EntryKind
  date: string
  amount_jpy: number
  payer_id: number
  title?: string
  note?: string
  category_id?: number | null
  to_member_id?: number | null
  member_ids?: number[] | null
  rule?: Record<string, unknown> | null
  /** 幂等键：离线草稿补交时带着同一个，后端认出来就不再记第二遍 */
  client_key?: string
  /** 固定费金额和上期差出好几倍（409 amount_jump）之后，人确认过就带上它再发一次 */
  confirm_jump?: boolean
}

/** 备份现在什么情况。**全部现场探**，不是读一条存下来的结论 —— 存的那种会过期 */
export interface BackupStatus {
  /** 备份目录（绝对路径） */
  path: string
  /** 现在就做不了备份的原因（错误码）；null ＝ 没问题 */
  error: string | null
  last_at: string | null
  last_name: string | null
  last_bytes: number | null
  count: number
  keep: number
  every_hours: number
  /** 上一份太久了（超过间隔的两倍） */
  stale: boolean
  /** 上一份**真打开验过**了吗（不是数文件名）。null ＝ 一份都还没有 */
  last_ok: boolean | null
  /** 备份和账本在同一块盘上 —— 挡不住盘坏 */
  same_disk: boolean | null
  /** data/ 里升级前快照、恢复时挪走的旧账本：一直不清理，在这儿亮出来 */
  stale_copies?: { count: number; bytes: number; oldest: string | null }
  /** 备份目录是不是人改过的（不是默认那个） */
  custom_path?: boolean
}

/** GET /api/backup/alert：平时页面上要不要亮一句「备份出问题了」。null ＝ 没事 */
export interface BackupAlert {
  alert: string | null
}

export interface BackupMade {
  name: string
  bytes: number
  at: string
  rows: number
  pruned: string[]
}
