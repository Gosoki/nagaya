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
