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

import shutil
import sys
from pathlib import Path

from sqlmodel import Session

from app.db import DB_PATH, engine
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


def main(argv: list[str]) -> None:
    if "--list" in argv:
        folder = _dir()
        print(f"备份目录：{folder}")
        for p in sorted(folder.iterdir()) if folder.is_dir() else []:
            if backup_svc.NAME_RE.match(p.name):
                print(f"  {p.name}  {p.stat().st_size:,} 字节")
        return

    src = _pick(next((a for a in argv if not a.startswith("-")), None))

    # ① 先验：恢复一份坏备份 ＝ 既丢了现在的、又没拿到过去的
    try:
        counts = backup_svc.verify_file(src)
    except backup_svc.BackupError as e:
        sys.exit(f"这一份用不了：{e}\n什么都没动。换一份试试（--list 看有哪些）。")
    print(f"要恢复的这份：{src.name}（{src.stat().st_size:,} 字节，"
          f"{len(counts)} 张表，{sum(counts.values())} 行）")

    if DB_PATH.exists() and "--yes" not in argv:
        print(f"\n现在的账本：{DB_PATH}")
        print("**先把服务停掉**（run.sh 那个进程），否则它还在往旧库里写。")
        if input("停好了？输 yes 继续：").strip().lower() != "yes":
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
    print("起服务就行。所有人的密码没变；换了机器的话大家要重新登录一次"
          "（签名密钥 data/.secret 不在备份里）。")


if __name__ == "__main__":
    main(sys.argv[1:])
