/**
 * 拼进 `html: true`（Quasar 的 Notify / Dialog）之前先转义。
 *
 * 那两处开 html 只是为了换行（它们的 message 是纯文本节点，`\n` 会被折成空格），
 * 可拼进去的内容里有**用户起的名字**（固定费项目、分类）和后端的原话 ——
 * 名字里带个 `<` 就会被当标签吞掉，带段 `<img onerror=…>` 就是存储型 XSS。
 */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  )
}

/**
 * 这一下回车是「提交」，还是输入法在「确认候选」。
 *
 * 日文/中文输入法按回车选字时，keydown 的 isComposing 是 true（Safari 上则是 keyCode 229）。
 * 原来写的是 `@keyup.enter`：打「すーぱー」、回车变成「スーパー」的那一下，
 * 这笔账当场就记下了，备注只到确认的那一截
 */
export function isSubmitEnter(e: Event): boolean {
  const k = e as KeyboardEvent
  return !k.isComposing && k.keyCode !== 229
}
