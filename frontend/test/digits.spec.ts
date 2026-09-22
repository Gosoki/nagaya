import { expect, it } from 'vitest'

import { digitsOf, toHalfWidth } from '../src/digits'

it('全角数字不再被吞成空（固定费那格清空＝删账）', () => {
  expect(digitsOf('１２，０００')).toBe('12000')
  expect(digitsOf('¥8,700')).toBe('8700')
})

it('全角减号也认', () => {
  expect(toHalfWidth('－５００')).toBe('-500')
})
