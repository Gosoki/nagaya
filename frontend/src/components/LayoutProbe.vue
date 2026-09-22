<!--
  布局诊断条。设置页最底下那行版本号**连点 5 下**开关（开关后会自动刷新）。

  只为一件事：iOS 主屏 app 冷启动时底栏抬起来那一下，到底是哪个数不对。
  headless 浏览器里复现不了（没有 standalone、没有刘海、没有真键盘），
  只能让真机自己把数报出来。平时不渲染，三个人都看不到。
-->
<template>
  <div class="probe">{{ text }}</div>
  <div ref="safe" class="safe-probe" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const text = ref('')
const safe = ref<HTMLElement | null>(null)
const t0 = performance.now()
let timer = 0

function box(sel: string): string {
  const el = document.querySelector(sel)
  if (!el) return '—'
  const b = el.getBoundingClientRect()
  return `${Math.round(b.top)}~${Math.round(b.bottom)}`
}

function sample() {
  const vv = window.visualViewport
  const cs = safe.value ? getComputedStyle(safe.value) : null
  const standalone =
    matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  const a = document.activeElement as HTMLElement | null
  text.value = [
    `t=${((performance.now() - t0) / 1000).toFixed(1)}s ${standalone ? 'APP' : 'WEB'}`,
    `inner=${innerHeight} doc=${document.documentElement.clientHeight} scr=${screen.height}`,
    `vv=${vv ? Math.round(vv.height) : '—'} off=${vv ? Math.round(vv.offsetTop) : '—'} y=${Math.round(scrollY)}`,
    `safe t=${cs?.paddingTop ?? '—'} b=${cs?.paddingBottom ?? '—'}`,
    `head=${box('.q-header')} foot=${box('.q-footer')}`,
    `act=${box('.actions')} nav=${box('.q-footer .q-tabs')}`,
    `focus=${a?.tagName ?? '—'}.${String(a?.className ?? '').split(' ')[0]}`,
  ].join('\n')
}

onMounted(() => {
  sample()
  timer = window.setInterval(sample, 200)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.probe {
  position: fixed;
  top: calc(env(safe-area-inset-top) + 60px);
  left: 8px;
  z-index: 9999;
  pointer-events: none;
  white-space: pre;
  font: 11px/1.35 ui-monospace, Menlo, monospace;
  color: #fff;
  background: rgba(0, 0, 0, 0.75);
  padding: 6px 8px;
  border-radius: 6px;
}
/* 量安全区用的：env() 在 JS 里读不到，挂在 padding 上再读计算值 */
.safe-probe {
  position: fixed;
  visibility: hidden;
  pointer-events: none;
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
</style>
