# 改表结构

2026-09-23 起表结构走 Alembic（SPEC D18）。基线 `0001_baseline.py` 就是那天的整套表
（当晚把最初的 0001、0002 合成了这一份）。那之前 create_all 建的旧格式库不再接管，开机时认出来就拒绝。

## 改了 models.py 之后

```bash
cd backend
# 对着一个**升到最新的空库**生成，别对着真账本生成
NAGAYA_DB=/tmp/nagaya-gen.db .venv/bin/python -c "from app import migrate; from pathlib import Path; migrate.upgrade(Path('/tmp/nagaya-gen.db'))"
NAGAYA_DB=/tmp/nagaya-gen.db .venv/bin/alembic revision --autogenerate -m "一句话说改了什么"
rm /tmp/nagaya-gen.db*
```

然后**读一遍生成出来的文件**再提交。autogenerate 认不出的几种要手改：

- **改名**会被认成「删一列 + 加一列」—— 数据就丢了。改成 `batch_op.alter_column(..., new_column_name=...)`。
- **新加的 NOT NULL 列**要给 `server_default`，不然老数据那几行加不进去。
- 要**搬数据**的（拆一列成两列之类），在 `upgrade()` 里自己写 `op.execute(...)`。

`tests/test_migrations.py` 会把「从空库一路升到最新」和模型逐表逐列比一遍：
改了模型忘了写迁移，它就红。

## 开机时发生什么

`app/init_db.py` → `app/migrate.py`：

1. 有要升的版本就先 `VACUUM INTO` 拍一张快照，放在 `data/before-migrate-*.db`
   （升级失败、服务反复重启时，库没动过就沿用上一张，不再一次一张）；
2. 关掉外键升级（SQLite 改列是整表重建，外键开着会连带删行）；
3. 升完核对库和模型，对不上就**拒绝启动**并说清缺了什么。

想先看看模型和迁移有没有对不上：`NAGAYA_DB=<升到最新的空库> .venv/bin/alembic check`。

不用手动跑 `alembic upgrade`。恢复备份（`tools.restore`）也会先把那份备份的拷贝升上来再装。
