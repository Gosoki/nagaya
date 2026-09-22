<!--
  备份 —— 设置页上的一块。

  **这一屏是备份唯一的出口。** 这屋里没有邮件没有推送，备份失败了没有第二条路
  告诉人；所以这里显示的每一项都是**现场探出来的**（目录能不能写、盘够不够、
  上一份是哪天），不是读一条存下来的「上次成功」。存下来的那种会过期：
  目录早被删了、盘早拔了，它还在说一切正常 —— 而那正是这个功能当初要治的毛病
  （设置页上写着「每日自动备份」，而备份代码一行都没有）。
-->
<template>
  <div class="bill-section">
    <q-item dense class="section-head">
      <q-item-section>{{ t('backup.title') }}</q-item-section>
      <q-item-section side>
        <q-btn
          dense flat no-caps color="primary" icon="save"
          :loading="busy"
          :label="t('backup.now')"
          @click="runNow"
        />
      </q-item-section>
    </q-item>

    <q-item v-if="st" class="backup-row">
      <q-item-section>
        <!-- 出错是**多一行**，不是把别的都藏起来。
             原来这一行 v-if 一成立，「上次 X · 共 N 份」整条就不渲染了 ——
             而「最新那份打不开」的时候，人比平时更需要知道上次是哪天、还剩几份 -->
        <q-item-label v-if="st.error" class="text-negative">
          {{ errorText(st.error) }}
        </q-item-label>
        <!-- 「这儿还没有」不是警报是指令：刚把目录指到别处的人做的是对的事，
             不该被一盏红灯迎接 —— 而按钮就在这一行的右边 -->
        <q-item-label v-if="!st.last_at && !st.error" class="text-grey-7">
          {{ t('backup.never') }}
        </q-item-label>
        <q-item-label v-if="st.last_at" :class="st.stale ? 'text-warning' : ''">
          {{ t('backup.last', { at: when(st.last_at) }) }}
          <span class="text-caption text-grey-6 q-ml-sm">
            {{ t('backup.count', { n: st.count }) }} · {{ size(st.last_bytes) }}
            <!-- 「共 N 份」只是数了数文件名，而这一格是**真打开验过**的那一份。
                 位腐、同步盘传了一半、iCloud 把内容抽走只留占位 —— 名字都还在 -->
            <q-icon v-if="st.last_ok" name="check" size="14px" class="text-positive" />
          </span>
        </q-item-label>

        <q-item-label caption class="path">{{ t('backup.dir') }} {{ st.path }}</q-item-label>
        <q-item-label caption>
          {{ st.every_hours ? t('backup.auto', { n: st.every_hours }) : t('backup.autoOff') }}
        </q-item-label>
        <!-- 说出来而不是拦住：默认就是同一块盘，而「同一块盘」这件事
             只有在盘真坏了那天才显出分量，那时候说已经晚了 -->
        <q-item-label v-if="st.same_disk" caption class="text-grey-6">
          {{ t('backup.sameDisk') }}
        </q-item-label>
        <!-- 只指路，不写步骤：恢复得在终端做，四步说明摆在手机上占三行还用不上 -->
        <q-item-label caption class="text-grey-6">{{ t('backup.restore') }}</q-item-label>
      </q-item-section>
    </q-item>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import type { BackupMade, BackupStatus } from 'src/api/types'

const { t, te } = useI18n()
const $q = useQuasar()

const st = ref<BackupStatus | null>(null)
const busy = ref(false)

onMounted(() => void load())

async function load() {
  try {
    st.value = await api.get<BackupStatus>('/api/backup')
  } catch {
    /* 拉不到状态就先不显示这一块，别在设置页上弹一个跟当前操作无关的错 */
  }
}

async function runNow() {
  busy.value = true
  try {
    const made = await api.post<BackupMade>('/api/backup')
    $q.notify({ type: 'positive', timeout: 3000, message: t('backup.made', { name: made.name }) })
  } catch (e) {
    $q.notify({ type: 'negative', timeout: 6000, message: e instanceof ApiError ? e.text : String(e) })
  } finally {
    busy.value = false
    await load()          // 成没成都重探一遍：失败的原因也要在那一行上说出来
  }
}

/** 后端给的是错误码，文案在这边查。查不到就把码本身显出来，总比空白强 */
function errorText(code: string): string {
  const key = `errors.${code}`
  return te(key) ? t(key) : code
}

const when = (iso: string) => iso.replace('T', ' ').slice(5, 16)
const size = (n: number | null) => (n === null ? '' : `${Math.round(n / 1024).toLocaleString()} KB`)
</script>

<style scoped>
.backup-row { padding-top: 4px; padding-bottom: 12px; }
/* 路径可能很长（同步盘那种），让它换行而不是把这一行撑破 */
.path { word-break: break-all; }
</style>
