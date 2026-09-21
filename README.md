# 長屋 nagaya

日本三人合租的记账 / 分摊工具。手机优先（占 70% 使用），装到主屏当 App 用。

> 名字取自江户时代庶民合住的联排出租屋 —— 落語《長屋の花見》里那帮穷邻居凑份子办赏花，
> 跟这个项目要干的事是一回事。

**设计与决策全部在 [`docs/SPEC.md`](docs/SPEC.md)（18 条已定决策 D1–D18）。动手前先读那个。**

---

## 它解决什么

三个人合租，钱主要从一个人卡上出，下个月中旬大家把上月的账结给他。要记的有：

- **家賃**：固定不变，每人交多少是**手填的固定金额**（房间大小不同，不是比例）
- **水道光熱費 + ネット**：金额每月变，按比例分；**水费两个月才收一次**
- **日常公共支出**：谁方便谁垫，粗放记一笔「日用品 ¥1,380」就行
- **集体收入**：返现、押金返还这类，按同样的规则分

以及：出账单贴到 LINE、结清后平账、没结清就挂账结转到下个月。

## 三条最要紧的设计

1. **每笔账的分摊结果是落库快照**（`entry_share`），不是查询时现算。
   第 4 个人搬进来、改默认比例、删分类 —— 历史账单一个数字都不会变。
2. **账期和结算日是两件事**。费用按发生日归自然月；结算日只用于账单上那句话；
   关账手动点。所以「10/15 记的转账算进 9 月期」天然成立。
3. **分摊算法前后端各一份实现**，靠 `tests/fixtures/` 下的共享用例锁住不漂。
   前端要本地即时预览，后端绝不信任客户端传来的金额。

## 跑起来

```bash
# 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m tools.seed_dev        # 建库 + 三个开发账号（密码 dev12345）
./run.sh                                  # http://localhost:8000

# 前端（开发）
cd frontend
npm install
npm run dev                               # http://localhost:9000，/api 代理到 8000

# 前端（部署形态：打包后由后端挂在同一个端口上）
npm run build && cd ../backend && ./run.sh
```

## 测试

```bash
cd backend  && .venv/bin/python -m pytest      # 算法 / 账本 / API
cd frontend && npm test                        # 前端分摊引擎 vs 后端 fixture
cd frontend && npx playwright test             # 375px 手机视口 E2E
```

分摊算法改动之后**必须**重跑 `cd backend && .venv/bin/python -m tools.gen_random_cases`，
否则后端那条「随机用例文件过期」的测试会红 —— 那正是前端还在按旧算法预览的危险时刻。

## 技术栈

| | |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + **Quasar**，`vite-plugin-pwa` 打成 PWA |
| 后端 | FastAPI + SQLModel + **SQLite (WAL)** |
| 金额 | 整数日元，前后端都禁 float |
| 双语 | vue-i18n（界面文案）；**分类名等用户数据不翻译** |
| 部署 | 打包后 FastAPI 挂 `frontend/dist/pwa`，**一个端口一个进程** |

数据库迁移（Alembic）配置已备好但**尚未启用** —— 设计阶段表结构还在改，
用 `create_all`；录真实账目之前切过去（见 `backend/alembic/versions/README.md`）。
