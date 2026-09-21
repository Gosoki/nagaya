<!--
  固定费单独一屏 —— 账单来了随时填，不用等到出账单。
  出账单只是「划一条线，把这一刻之前的都算进来」，两件事分开。
-->
<template>
  <q-page class="q-pb-xl">
    <MonthlyFixed />
  </q-page>
</template>

<script setup lang="ts">
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
</script>
