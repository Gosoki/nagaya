/**
 * 屏幕上还有没落地的输入：整页重载之前要等它、等不到就别刷（router.onError 换 chunk 那条路）。
 *
 * 只数写请求（client.pendingWrites）不够：固定费面板失焦存一行撞上 409（量级闸、版本冲突），
 * 写请求已经落地、计数归零，询问框这才弹出来，那一行还 dirty —— 这时整页重载，
 * 框没了、填的数没了，onBeforeUnmount 也不跑，「这几项没存上」那条提示都没机会出来。
 * 所以有没存上东西的组件挂一个判据上来（MonthlyFixed：正在存 / 在等人答 / 存失败还 dirty），
 * 卸载时摘掉
 */
const holders = new Set<() => boolean>()

/** 挂上一个「我这儿还有没存上的」判据。返回值是摘掉它的函数（卸载时调） */
export function holdReload(holding: () => boolean): () => void {
  holders.add(holding)
  return () => {
    holders.delete(holding)
  }
}

/** 此刻有几处还没存上 */
export const pendingUi = (): number => [...holders].filter((f) => f()).length
