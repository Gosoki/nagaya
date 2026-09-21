/**
 * 硬约束 8（SPEC §7.5 / §8）：`.vue` 里不许出现裸中日文字符串。
 *
 * 这条以前只写在文档里、靠人自觉 —— 而这次一口气加了几百行新界面，
 * 最容易的偷懒就是把日文直接写进模板，中文那份永远补不上。
 * 所以给它配一道真闸。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
const CJK = /[一-鿿぀-ゟ゠-ヿ]/

/**
 * 例外。每一条都得写清为什么 —— 白名单没有理由就会慢慢变成垃圾桶，
 * 最后这道闸跟不存在一样。
 */
const ALLOWED: { text: string; why: string }[] = [
  { text: "'中文'", why: '语言切换按钮上的语言名，翻译它本身没有意义' },
  { text: "'日本語'", why: '同上' },
  { text: '>長<', why: '项目 logo 的字形，不是文案' },
]

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return vueFiles(full)
    return name.endsWith('.vue') ? [full] : []
  })
}

/** 剥掉注释和 <style>，剩下的才是会显示给人看的东西 */
function strip(source: string): string {
  return source
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

describe('界面文案必须走 i18n', () => {
  const files = vueFiles(SRC)

  it('至少扫到了文件（别因为路径写错而空跑变成假绿）', () => {
    expect(files.length).toBeGreaterThan(5)
  })

  for (const file of files) {
    it(relative(SRC, file), () => {
      const offenders: string[] = []
      strip(readFileSync(file, 'utf-8'))
        .split('\n')
        .forEach((line, i) => {
          // 扣掉白名单里的字面量之后，**整行**还剩中日文就算违规。
          // 不能只查引号里的内容：模板里的裸文本 <div>本期固定费</div> 才是最常见的那种，
          // 只扫字面量会让这道闸变成空转（第一版就是这么写的，injection 测试当场打脸）。
          let rest = line
          for (const { text } of ALLOWED) rest = rest.split(text).join('')
          if (CJK.test(rest)) offenders.push(`  第 ${i + 1} 行: ${line.trim().slice(0, 70)}`)
        })
      expect(offenders, `裸中日文字符串，应当走 t()：\n${offenders.join('\n')}`).toEqual([])
    })
  }
})
