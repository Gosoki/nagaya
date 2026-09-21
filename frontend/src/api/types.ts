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

export interface Setting {
  key: string
  value: unknown
  type: string
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
