/**
 * 三种账目各自的颜色：支出蓝、收入绿、转账黄。
 *
 * **这里是唯一的出处。** 页面要 hex 就拿 KIND_COLOR（画头像、描边这类），
 * Quasar 组件要 palette 名就拿 KIND_PALETTE（color / toggle-color 属性只认名字）。
 * 两张表的值必须和 quasar-variables.sass 对得上，有测试钉着。
 */
import type { EntryKind } from 'src/api/types'

export const KIND_COLOR: Record<EntryKind, string> = {
  expense: '#3d4785',
  income: '#2f9e5f',
  settlement: '#d98e04',
}

export const KIND_PALETTE: Record<EntryKind, string> = {
  expense: 'primary',
  income: 'positive',
  settlement: 'warning',
}
