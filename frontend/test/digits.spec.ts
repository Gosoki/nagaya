import { expect, it } from 'vitest'

import { MAX_YEN, digitsOf, parseTypedYen, toHalfWidth, yenOf } from '../src/digits'

it('全角数字不再被吞成空（固定费那格清空＝删账）', () => {
  expect(digitsOf('１２，０００')).toBe('12000')
  expect(digitsOf('¥8,700')).toBe('8700')
})

it('全角减号也认', () => {
  expect(toHalfWidth('－５００')).toBe('-500')
})

it('金额框超过上限就按上限，空的是 0', () => {
  expect(yenOf('1234567890')).toBe(MAX_YEN)
  expect(yenOf('８，７００')).toBe(8700)
  expect(yenOf('')).toBe(0)
})

it('手打金额：千分位擦掉，小数点不当千分位', () => {
  expect(parseTypedYen('1,234,567')).toBe(1234567)
  expect(parseTypedYen('1.234.567')).toBe(1234567)
  expect(parseTypedYen('１２００')).toBe(1200)
  expect(parseTypedYen(' 1 500 ')).toBe(1500)
  expect(parseTypedYen('10000')).toBe(10000)
  // 日元没有小数：原来「5000.00」会被擦成 500,000
  expect(parseTypedYen('5000.00')).toBeNaN()
  expect(parseTypedYen('abc')).toBeNaN()
})
