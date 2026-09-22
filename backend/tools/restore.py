"""从一份备份恢复。

    .venv/bin/python -m tools.restore              # 用最新那份
    .venv/bin/python -m tools.restore nagaya-20260922-133226.db
    .venv/bin/python -m tools.restore --list

**为什么值得单独写个脚本**：恢复只有一步是危险的，而那一步长得完全不像危险。
实测「把 .db 拷回去」而**不删** `-wal` / `-shm`：SQLite 会把旧 WAL 的页盖到新文件上，
第一次读还给得出数字（44 笔的备份读出来 127 笔），再读就是
`database disk image is malformed` —— 一个混出来的怪物，而人以为自己恢复好了。
出事那天正是最不该照着四步说明手工操作的时候。

脚本做三件事，缺一不可：
  1. **先验备份**：打不开的、零张表的，当场拒绝，不动现有的库；
  2. **现有的库挪走不删**：万一恢复错了那份，原来的还在；
  3. **连 -wal / -shm 一起处理**，不给旧 WAL 留下任何盖上来的机会。
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel

from app.db import DB_PATH, engine
from app.models import Member  # noqa: F401 —— 导入即注册表，_schema_drift 要读 metadata
from app.services import backup as backup_svc

SIDECARS = ("-wal", "-shm")


def _dir(argv: list[str]) -> Path:
    """备份目录在哪。

    **不能直接开 Session 去读设置。** 需要恢复的三个场合里有两个（库被删、换新机器）
    恰恰是库不在，而第三个（库损坏）连 `PRAGMA journal_mode=WAL` 都过不去 ——
    也就是说唯一还跑得动的是「库好好的，只想回滚一下」，最不需要这个工具的那天。
    实测：库不在时是 40 行 traceback，而且**顺手在 data/ 下建出一个空的 nagaya.db**，
    人在慌的时候看到的是一堆栈和一个凭空出现的空账本。

    所以：先看文件在不在（不能只靠 try/except —— 光连一下就会把那个空库落盘），
    读不出来就退回默认目录，并且给一个 `--dir=` 让「库彻底没了」也走得完。
    """
    for a in argv:
        if a.startswith("--dir="):
            return Path(a[6:]).expanduser().resolve()
    fallback = (backup_svc.BASE_DIR / "backups").resolve()
    if not DB_PATH.exists():
        print(f"账本不在（{DB_PATH}），备份目录用默认的：{fallback}")
        return fallback
    try:
        with Session(engine) as session:
            return backup_svc.backup_dir(session)
    except SQLAlchemyError as e:
        # 库在但读不出设置 —— 正是 malformed 那天。OperationalError（没有 setting 表）
        # 和 DatabaseError（file is not a database）都是它的子类
        print(f"账本读不出设置（{type(e).__name__}），备份目录用默认的：{fallback}")
        print("备份不在默认目录的话，加 --dir=<路径>")
        return fallback


def _pick(name: str | None, argv: list[str]) -> Path:
    folder = _dir(argv)
    files = sorted(p for p in folder.iterdir() if backup_svc.NAME_RE.match(p.name)) \
        if folder.is_dir() else []
    if not files:
        sys.exit(f"备份目录里一份都没有：{folder}")
    if name is None:
        return files[-1]
    hit = folder / name
    if not hit.exists():
        sys.exit(f"没有这一份：{hit}\n现有的：\n  " + "\n  ".join(p.name for p in files))
    return hit


def _columns(path: Path) -> dict[str, list[tuple[str, int, object]]]:
    """一份库里每张表有哪些列，以及它们是不是 NOT NULL、有没有默认值。

    两个方向的漂移都要靠它：缺列（恢复后一查就 500）和多出的 NOT NULL 无默认列
    （恢复后一写就失败）。`pragma table_info` 本来就在跑，三项在同一行里。
    """
    # as_uri() 而不是手拼：路径里带 # 或 ? 时手拼会打开别的东西
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        names = [
            r[0] for r in con.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        ]
        return {
            n: [(r[1], r[3], r[4]) for r in con.execute(f'pragma table_info("{n}")')]
            for n in names
        }
    finally:
        con.close()


def _schema_drift(path: Path) -> tuple[list[str], list[str], list[str]]:
    """这份备份缺了今天的代码要用的哪些列。

    **这是恢复路上最阴的一条。** 项目至今是 `create_all` 没有迁移
    （SPEC D18：录真账之前再切 Alembic），而 create_all 对已存在的表**只加表不加列**。
    于是恢复一份改字段之前做的备份：服务起得来、完整性检查也过，
    然后每一条碰到新列的查询都是 `no such column` → 500 ——
    而那时旧库已经被挪走了。宁可现在拦下来。
    """
    want = {t.name: {c.name: c for c in t.columns} for t in SQLModel.metadata.tables.values()}
    got = _columns(path)
    tables: list[str] = []
    cols: list[str] = []
    extra: list[str] = []
    for table, spec in want.items():
        if table not in got:
            # **缺整张表不致命**：开机 init_db() 的 create_all 会把它建成空表，
            # 服务和查询都正常。拦下来的话，等于在出事那天拒绝一份完全能用的备份
            tables.append(table)
            continue
        gone = set(spec) - {c for c, _, _ in got[table]}
        if gone:
            cols.append(f"{table}.{'/'.join(sorted(gone))}")
        # 反方向：备份比代码**多**一列。多出来的列如果是 NOT NULL 且没有默认值
        # （SQLModel 的 Field(default=0) 生成的正是这种），恢复上去读账正常，
        # 但每一条写进这张表的记录都会 NOT NULL constraint failed ——
        # 而那时旧库已经被挪走了
        for name, notnull, dflt in got[table]:
            if name not in spec and notnull and dflt is None:
                extra.append(f"{table}.{name}")
    return tables, cols, extra


def main(argv: list[str]) -> None:
    if "--list" in argv:
        folder = _dir(argv)
        print(f"备份目录：{folder}")
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if not backup_svc.NAME_RE.match(p.name):
                continue
            # 把「里面有多少东西」一起列出来：种子库和真账本的备份同名同形，
            # 光看文件名分不出来，而挑错一份的代价是把假账本盖到真账本上
            try:
                con = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
                who = ", ".join(r[0] for r in con.execute("select display_name from member"))
                n = list(con.execute("select count(*) from entry"))[0][0]
                con.close()
                extra = f"{n} 笔 · {who}"
            except sqlite3.Error as e:
                extra = f"**打不开：{e}**"
            print(f"  {p.name}  {p.stat().st_size:>10,} 字节  {extra}")
        return

    src = _pick(next((a for a in argv if not a.startswith("-")), None), argv)

    # ① 先验：恢复一份坏备份 ＝ 既丢了现在的、又没拿到过去的
    try:
        counts = backup_svc.verify_file(src)
    except backup_svc.BackupError as e:
        sys.exit(f"这一份用不了：{e}\n什么都没动。换一份试试（--list 看有哪些）。")
    print(f"要恢复的这份：{src.name}（{src.stat().st_size:,} 字节，"
          f"{len(counts)} 张表，{sum(counts.values())} 行）")

    tables, cols, extra = _schema_drift(src)
    blocking = []
    if cols:
        blocking.append(
            "这份备份比现在的代码**旧**，缺这些列：\n  " + "\n  ".join(cols) +
            "\n恢复上去服务起得来，但一查到这些列就是 500。"
        )
    if extra:
        blocking.append(
            "这份备份是比现在的代码**新**的版本做的，多出这些列（NOT NULL 且无默认值）：\n  "
            + "\n  ".join(extra) +
            "\n恢复上去读账正常，但每一条写进这些表的记录都会失败。"
        )
    if blocking and "--force" not in argv:
        sys.exit(
            "\n\n".join(blocking) +
            "\n\n而那时旧库已经被挪走了。换一份（--list 看看），或者把代码切回做这份备份时的版本；\n"
            "确实要硬来就加 --force。什么都没动。"
        )
    if blocking:
        print("⚠️ " + " / ".join(cols + extra) + "（--force 了，继续）")
    if tables:
        # 不拦：开机 create_all 会把这些表建成空表
        print(f"提示：这份备份里没有 {'、'.join(tables)} —— 开机会自动建成空表。"
              f"要是其中有存账目的表，那部分数据这份备份里本来就没有。")

    if DB_PATH.exists():
        # 这句 --yes 时也要印：服务没停的话它还开着旧库的文件句柄，
        # 换完之后它写的仍然是被挪走的那一份，而屏幕上一切正常
        print(f"\n现在的账本：{DB_PATH}")
        print("**先把服务停掉**（run.sh 那个进程），否则它还在往旧库里写。")
        if "--yes" not in argv and input("停好了？输 yes 继续：").strip().lower() != "yes":
            sys.exit("没动任何东西。")

    # ② 现有的挪走，不删 —— 万一恢复错了那份，原来的还在
    if DB_PATH.exists():
        # 目录名按**这次恢复的时刻**取，不按备份的时刻。
        # 按备份取的话，同一份连着恢复两次（以为刚才没成功、或者忘了停服务想重来）
        # 会算出同一个目录名，而 shutil.move 到一个已存在的**文件**是静默覆盖 ——
        # 第二次抹掉的正是第一次好心留下的那本真账本。实测：3 笔只在活账本里的账
        # 就此永久消失，退出码 0，零提示。
        aside = DB_PATH.parent / f"replaced-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        n = 1
        while aside.exists():                 # 同一秒里跑两次也不许撞
            n += 1
            aside = aside.with_name(f"{aside.name.rsplit('-', 1)[0]}-{n}")
        aside.mkdir()
        for suffix in ("", *SIDECARS):
            old = Path(str(DB_PATH) + suffix)
            if old.exists():
                shutil.move(str(old), aside / old.name)
        print(f"原来的账本挪到了：{aside}")
    else:
        # ③ 库不在但 -wal 还在的话，旧 WAL 照样会盖上来
        for suffix in SIDECARS:
            Path(str(DB_PATH) + suffix).unlink(missing_ok=True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, DB_PATH)
    print(f"恢复完成：{DB_PATH}")
    # **设置表也一起恢复了**，包括备份目录它自己。恢复一份「目录还指着旧移动盘」
    # 时代的备份，备份目录会跟着回滚 —— 而这恰好是刚出完事、最不该再丢一次备份的时候
    try:
        con = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
        row = con.execute("select value_json from setting where key='backup_path'").fetchone()
        con.close()
        if row:
            # value_json 存的是 JSON，直接印会带一对引号
            print(f"注意：备份目录跟着回滚成了 {json.loads(row[0])} —— 不对的话去设置里改回来。")
    except sqlite3.Error:
        pass
    print(
        "起服务就行。**成员和密码也跟着回滚到这份备份那一刻**：\n"
        " · 备份之后改过密码的人，要用**当时那个**密码登录，手上的登录状态也会失效；\n"
        " · 反过来，备份之前靠改密码踢掉的设备会重新生效 —— 真是为了踢人改的，恢复完再改一次。\n"
        "换了机器的话所有人都要重登（签名密钥 data/.secret 不在备份里）。"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
