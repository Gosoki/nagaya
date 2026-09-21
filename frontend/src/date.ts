/**
 * 业务日期一律按**日本时间**算 —— 和后端 models.today_jst 同一条规矩。
 *
 * 不能用 `new Date().toISOString().slice(0, 10)`：那是 UTC。
 * JST 比 UTC 早 9 小时，所以**日本时间 0 点到 9 点之间，UTC 还停在前一天** ——
 * 凌晨记的账会全部落到昨天。真踩过：0 点过几分跑 E2E，新记的那笔日期是昨天，
 * 排序排到了出账那批后面。半夜记账正是这个 App 的高频场景（聚餐散场）。
 *
 * 也不能靠浏览器本地时区：人在国外出差，记的还是这个家的账。
 */
const JST = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Tokyo',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** 今天（日本时间），YYYY-MM-DD */
export const todayJst = (): string => JST.format(new Date())
