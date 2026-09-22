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

import json
import shutil
import sqlite3
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel

from app.db import DB_PATH, engine
from app.models import Member  # noqa: F401 —— 导入即注册表，_schema_drift 要读 metadata
from app.services import backup as backup_svc

SIDECARS = ("-wal", "-shm")


def _dir() -> Path:
    with Session(engine) as session:
        return backup_svc.backup_dir(session)


def _pick(name: str | None) -> Path:
    folder = _dir()
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


def _columns(path: Path) -> dict[str, set[str]]:
    """一份库里每张表有哪些列。用来比对「这份备份和现在的代码对不对得上」。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [
            r[0] for r in con.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        ]
        return {n: {r[1] for r in con.execute(f'pragma table_info("{n}")')} for n in names}
    finally:
        con.close()


def _schema_drift(path: Path) -> list[str]:
    """这份备份缺了今天的代码要用的哪些列。

    **这是恢复路上最阴的一条。** 项目至今是 `create_all` 没有迁移
    （SPEC D18：录真账之前再切 Alembic），而 create_all 对已存在的表**只加表不加列**。
    于是恢复一份改字段之前做的备份：服务起得来、完整性检查也过，
    然后每一条碰到新列的查询都是 `no such column` → 500 ——
    而那时旧库已经被挪走了。宁可现在拦下来。
    """
    want = {t.name: {c.name for c in t.columns} for t in SQLModel.metadata.tables.values()}
    got = _columns(path)
    missing = []
    for table, cols in want.items():
        gone = cols - got.get(table, set())
        if table not in got:
            missing.append(f"{table}（整张表都没有）")
        elif gone:
            missing.append(f"{table}.{'/'.join(sorted(gone))}")
    return missing


def main(argv: list[str]) -> None:
    if "--list" in argv:
        folder = _dir()
        print(f"备份目录：{folder}")
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if not backup_svc.NAME_RE.match(p.name):
                continue
            # 把「里面有多少东西」一起列出来：种子库和真账本的备份同名同形，
            # 光看文件名分不出来，而挑错一份的代价是把假账本盖到真账本上
            try:
                con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                who = ", ".join(r[0] for r in con.execute("select display_name from member"))
                n = list(con.execute("select count(*) from entry"))[0][0]
                con.close()
                extra = f"{n} 笔 · {who}"
            except sqlite3.Error as e:
                extra = f"**打不开：{e}**"
            print(f"  {p.name}  {p.stat().st_size:>10,} 字节  {extra}")
        return

    src = _pick(next((a for a in argv if not a.startswith("-")), None))

    # ① 先验：恢复一份坏备份 ＝ 既丢了现在的、又没拿到过去的
    try:
        counts = backup_svc.verify_file(src)
    except backup_svc.BackupError as e:
        sys.exit(f"这一份用不了：{e}\n什么都没动。换一份试试（--list 看有哪些）。")
    print(f"要恢复的这份：{src.name}（{src.stat().st_size:,} 字节，"
          f"{len(counts)} 张表，{sum(counts.values())} 行）")

    drift = _schema_drift(src)
    if drift and "--force" not in argv:
        sys.exit(
            "这份备份比现在的代码旧，缺这些列：\n  " + "\n  ".join(drift) +
            "\n\n恢复上去服务起得来，但一查到这些列就是 500，而那时旧库已经被挪走了。\n"
            "要么换一份新的（--list 看看），要么先把代码退回那个版本，\n"
            "确实要硬来就加 --force。什么都没动。"
        )
    if drift:
        print(f"⚠️ 缺列：{', '.join(drift)}（--force 了，继续）")

    if DB_PATH.exists():
        # 这句 --yes 时也要印：服务没停的话它还开着旧库的文件句柄，
        # 换完之后它写的仍然是被挪走的那一份，而屏幕上一切正常
        print(f"\n现在的账本：{DB_PATH}")
        print("**先把服务停掉**（run.sh 那个进程），否则它还在往旧库里写。")
        if "--yes" not in argv and input("停好了？输 yes 继续：").strip().lower() != "yes":
            sys.exit("没动任何东西。")

    # ② 现有的挪走，不删 —— 万一恢复错了那份，原来的还在
    if DB_PATH.exists():
        aside = DB_PATH.parent / f"replaced-{src.stem.replace('nagaya-', '')}"
        aside.mkdir(exist_ok=True)
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
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        row = con.execute("select value_json from setting where key='backup_path'").fetchone()
        con.close()
        if row:
            # value_json 存的是 JSON，直接印会带一对引号
            print(f"注意：备份目录跟着回滚成了 {json.loads(row[0])} —— 不对的话去设置里改回来。")
    except sqlite3.Error:
        pass
    print("起服务就行。所有人的密码没变；换了机器的话大家要重新登录一次"
          "（签名密钥 data/.secret 不在备份里）。")


if __name__ == "__main__":
    main(sys.argv[1:])
