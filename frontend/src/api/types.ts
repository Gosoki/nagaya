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
  period_id: number | null
  period_label: string | null
  period_start: string | null
  period_end: string | null
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

export interface Period {
  id: number
  label: string
  start_date: string
  end_date: string
  status: 'open' | 'closed'
  closed_at: string | null
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
  period_start?: string | null
  period_end?: string | null
}
