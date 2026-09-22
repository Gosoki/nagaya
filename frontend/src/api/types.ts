export type EntryKind = 'expense' | 'income' | 'settlement'
export type Lang = 'zh' | 'ja'

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
  /** 头像，data:image/webp;base64,…。没设过就是 null，界面退回那个带首字的色圆 */
  avatar: string | null
  avatar_version: number
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
  bundle_id: number | null
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
export interface BillRow {
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
  } | null
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
  simplified: boolean
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
  bundle_id?: number | null
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
}

export interface BackupMade {
  name: string
  bytes: number
  at: string
  rows: number
  pruned: string[]
}
