/**
 * 软键盘占掉了屏幕底下多少像素。
 *
 * **为什么非要算这个**：iOS 上 `position: fixed` 钉的是**布局视口**，而键盘弹起来
 * 不改布局视口 —— 于是「记入账」那条仍然钉在屏幕底边，整条被键盘压在下面。
 * 人一边打金额一边看不见保存键，只能先收键盘再点，多一步还容易以为没生效。
 *
 * 可视视口（visualViewport）才是键盘之上那块真正看得见的区域：
 *
 *     键盘高度 ＝ 布局视口高 − 可视视口高 − 可视视口在布局视口里的上偏移
 *
 * 40px 以下当没有：地址栏收起、输入法上面那条候选栏的微调都会让这个数抖一抖，
 * 照着抖的话按钮会跟着上下跳。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useKeyboardInset() {
  const inset = ref(0)

  function measure() {
    const vv = window.visualViewport
    if (!vv) return
    const raw = window.innerHeight - vv.height - vv.offsetTop
    inset.value = raw > 40 ? Math.round(raw) : 0
  }

  onMounted(() => {
    const vv = window.visualViewport
    if (!vv) return              // 老 Safari / 桌面：按老样子钉在底边
    vv.addEventListener('resize', measure)
    vv.addEventListener('scroll', measure)
    measure()
  })

  onBeforeUnmount(() => {
    const vv = window.visualViewport
    if (!vv) return
    vv.removeEventListener('resize', measure)
    vv.removeEventListener('scroll', measure)
  })

  return inset
}
