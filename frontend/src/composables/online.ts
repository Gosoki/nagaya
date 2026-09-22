/**
 * 现在还连得上吗。
 *
 * **两条依据，缺一不可**：
 *   * `navigator.onLine` —— 飞行模式、wifi 断了这种，浏览器自己知道；
 *   * 最近一次取数是不是失败了 —— 连着 wifi 但出不去（便利店那种要点同意的
 *     热点、后端挂了、电车里信号跳），`onLine` 照样是 true，而屏幕上的数字
 *     其实已经是旧的了。
 *
 * 为什么非说不可：账单页就是三个人掏手机转账前盯的那一屏。断网时它会拿
 * 上次加载的数字冒充当下的数字 —— 室友刚把水费填进去、刚点了「确认已完成」，
 * 这边一无所知，照着旧的「你要给 Zen ¥102,114」转了钱，转错了才发现。
 */
import { onMounted, onUnmounted, ref } from 'vue'

export function useOnline() {
  const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
  const set = () => {
    online.value = navigator.onLine
  }
  onMounted(() => {
    window.addEventListener('online', set)
    window.addEventListener('offline', set)
  })
  onUnmounted(() => {
    window.removeEventListener('online', set)
    window.removeEventListener('offline', set)
  })
  return online
}
