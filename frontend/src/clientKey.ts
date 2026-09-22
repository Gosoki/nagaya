/**
 * 每笔新账的幂等键（后端 models.RequestKey）。同一个键后端只记一次。
 *
 * 不用 crypto.randomUUID()：它只在安全上下文（https / localhost）里有，
 * 而这个 App 常在局域网里走 http://10.0.0.x 打开 —— 那儿它是 undefined。
 * getRandomValues 没有这个限制。
 */
export function newClientKey(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}
