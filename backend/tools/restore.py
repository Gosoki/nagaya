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
     再把它的一份拷贝升到现在的表结构（和开机同一套 Alembic），升不上来也拒绝；
  2. **现有的库挪走不删**：万一恢复错了那份，原来的还在；
  3. **连 -wal / -shm 一起处理**，不给旧 WAL 留下任何盖上来的机会。
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app import migrate
from app.db import DB_PATH, engine
from app.models import JST
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
    if name is None:
        if not files:
            sys.exit(f"备份目录里一份都没有：{folder}")
        return files[-1]
    # 点名的那份不要求备份目录里有别的：拿开机升级前的快照（data/before-migrate-*.db）
    # 恢复时，备份目录多半正是空的。给的是绝对路径时 folder / name 就是它自己
    hit = folder / name
    if not hit.exists():
        sys.exit(f"没有这一份：{hit}\n现有的：\n  " + "\n  ".join(p.name for p in files))
    return hit


def _upgraded_copy(src: Path) -> Path:
    """把备份拷一份到临时目录，按开机那一套升到最新表结构。升不上来就抛。

    有了 Alembic 之后，加字段之前做的备份照样升上来；升不上的才拦：
    更新的代码做的、或者 2026-09-23 切 Alembic 之前的旧格式（不再接管）。
    **升的是拷贝**：出了任何事，备份原件一个字节都没动。
    """
    tmp = Path(tempfile.mkdtemp(prefix="nagaya-restore-")) / src.name
    # 那是一整份账本的明文。中途任何一条路退出（升不上、行数不对、没确认停服务）都得清掉
    atexit.register(shutil.rmtree, tmp.parent, True)
    shutil.copy2(src, tmp)
    migrate.upgrade(tmp, snapshot=False)
    # 升级时开的是 WAL，写进去的东西可能还躺在拷贝的 -wal 里，而接下来只拷主文件 ——
    # 正是这个脚本开头说的那个坑。切回普通日志模式：WAL 并回主文件、-wal 删掉，
    # 装上去的和一份普通备份长得一样（服务起来会自己再切成 WAL）。
    # 留在 WAL 模式的话，只读打开（mode=ro）连 -shm 都建不出来，直接打不开
    con = sqlite3.connect(tmp)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
    finally:
        con.close()
    return tmp


def _in_use() -> bool:
    """服务是不是还开着这本账（最近一分钟里有人用过）。

    服务没停就换库，它手里那条连接还指着被挪走的旧文件：之后回了 201 的账全写进
    replaced-*/ 里，app 里看着像「恢复没生效」，等它空闲一分钟放掉连接，新记的账
    又从备份里最大的 id 往后编号 —— 同一个 id 在两份库里指两笔不同的账。
    原来只印一句「先把服务停掉」就接着做了，加了 --yes 更是看都没人看。

    探法：另开一条连接要独占锁，拿不到（BUSY / LOCKED）就是有人开着。
    **只认这两种错**：库坏了（file is not a database、malformed）正是要恢复的时候，必须放行。
    探之前先把自己池子里的连接放掉 —— _dir() 读设置时留下的那条会让自己探到自己。
    服务空闲超过一分钟时探不出来，但那时它手里没有任何句柄，下一个请求开的就是恢复后的库，无害
    """
    engine.dispose()
    try:
        con = sqlite3.connect(
            f"{DB_PATH.resolve().as_uri()}?mode=rw", uri=True, timeout=0.5, isolation_level=None
        )
    except sqlite3.Error:
        return False
    try:
        con.execute("PRAGMA locking_mode=EXCLUSIVE")
        con.execute("BEGIN EXCLUSIVE")
        con.execute("ROLLBACK")
    except sqlite3.OperationalError as e:
        # 扩展码的低 8 位才是主码：BUSY_SNAPSHOT 517、LOCKED_SHAREDCACHE 262 都算
        return (getattr(e, "sqlite_errorcode", 0) & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    except sqlite3.DatabaseError:
        return False
    finally:
        con.close()
    return False


def _refuse_if_in_use() -> None:
    if _in_use():
        sys.exit(
            "服务还开着这本账（最近一分钟里有人用过）。先停服务再来：\n"
            "  systemctl stop nagaya    或    docker compose stop nagaya\n"
            "什么都没动。"
        )


def _jst(ts: str | None) -> str:
    """库里的时刻是 naive UTC 字符串，印成日本时间到分钟"""
    if not ts:
        return "—"
    at = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc).astimezone(JST)
    return at.strftime("%Y-%m-%d %H:%M")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _facts(con: sqlite3.Connection) -> str:
    who = ", ".join(r[0] for r in con.execute("select display_name from member order by display_order, id"))
    n, total = con.execute(
        "select count(*), coalesce(sum(amount_jpy), 0) from entry where deleted_at is null"
    ).fetchone()
    last = con.execute("select max(created_at), max(updated_at) from entry").fetchone()
    st_n, cut = con.execute("select count(*), max(cut_at) from statement").fetchone()
    return (f"{n} 笔（合计 ¥{total:,}）· {who}\n"
            f"      最后记账 {_jst(last[0])}，最后改账 {_jst(last[1])}，账单 {st_n} 张（最近一张 {_jst(cut)}）")


#: 比「这笔账改没改过」看的几列。version / updated_at 不算：每动一下都变，说明不了内容变没变。
#: statement_id 算：备份之后出账归进账单的那几笔，恢复之后会回到草稿里。
#: split_rule_json 算：只改了分摊的那种，金额一分没动，钱照样换了人担
_CONTENT = ("kind, date, amount_jpy, payer_id, to_member_id, category_id, title, note, "
            "statement_id, split_rule_json")


def _what_goes(live: sqlite3.Connection, back: sqlite3.Connection) -> list[str]:
    """恢复之后会退回去的那些事，一行一句。**先确认两边是同一本账**，不是就不数 ——
    另一本账的备份 id 照样从 1 编起，按 id 比出来的「会丢 0 笔」是一句假话。"""
    bm = dict(back.execute("select id, created_at from member"))
    lm = dict(live.execute("select id, created_at from member"))
    be = dict(back.execute("select id, created_at from entry"))
    le = dict(live.execute("select id, created_at from entry"))
    if any(lm.get(i) != c for i, c in bm.items()) or any(le.get(i) != c for i, c in be.items()):
        return [
            "**这份备份和现在的账本不是同一本**（成员或账目的建档时刻对不上）——",
            "恢复等于把整本账换掉，不是「退回到某一刻」。确认没挑错（--list 看每份里有谁、几笔）。",
        ]
    names = dict(live.execute("select id, display_name from member"))
    out: list[str] = []
    new = [r for r in live.execute(
        "select id, date, amount_jpy, title, payer_id from entry where deleted_at is null order by id"
    ) if r[0] not in be]
    if new:
        dates = sorted(r[1] for r in new)
        out.append(f"备份之后新记的 {len(new)} 笔会没有（合计 ¥{sum(r[2] for r in new):,}，"
                   f"日期 {dates[0]} 〜 {dates[-1]}）：")
        for eid, on, amount, title, payer in new[:5]:
            out.append(f"    #{eid}  {on}  ¥{amount:,}  {title or '—'}  {names.get(payer, payer)}")
        if len(new) > 5:
            out.append(f"    …… 还有 {len(new) - 5} 笔")
    back_rows = {r[0]: r[1:] for r in back.execute(f"select id, deleted_at, {_CONTENT} from entry")}
    edited = gone = 0
    for row in live.execute(f"select id, deleted_at, {_CONTENT} from entry"):
        was = back_rows.get(row[0])
        if was is None:
            continue
        if (row[1] is None) != (was[0] is None):
            gone += 1
        elif row[2:] != was[1:]:
            edited += 1
    if edited:
        out.append(f"备份之后改过的 {edited} 笔会退回改之前（含出账时归进账单的）")
    if gone:
        out.append(f"备份之后删掉 / 撤销删除的 {gone} 笔会退回原来的状态")
    back_st = {r[0] for r in back.execute("select id from statement")}
    cuts = [r[1] for r in live.execute("select id, cut_at from statement order by id") if r[0] not in back_st]
    if cuts:
        out.append(f"备份之后出的 {len(cuts)} 张账单会消失（{', '.join(_jst(c) for c in cuts)}）")
    return out or ["两边的账目一样：恢复不会丢账（设置、成员、密码照样回到备份那一刻）"]


def _compare(ready: Path) -> None:
    """确认之前把「这一下会丢掉什么」摆出来。全程只读，读不出来就说读不出来 —— 绝不印成 0 笔"""
    try:
        live = _ro(DB_PATH)
    except sqlite3.Error as e:
        print(f"现在的账本打不开（{e}），没法对比 —— 这不是「0 笔」，是不知道。")
        return
    back = _ro(ready)   # 刚验过、升过的那份，打得开
    try:
        print(f"  现在的账本：{_facts(live)}")
        print(f"  要恢复的这份：{_facts(back)}")
        print("恢复之后：")
        for line in _what_goes(live, back):
            print(f"  {line}")
        broken = backup_svc.ledger_problems(back)
        if broken:
            print(f"  **注意：这份备份里的账本自检没通过**（账目 {broken['entries'][:10]} 分摊合计对不上）")
    except sqlite3.Error as e:
        print(f"现在的账本读不出来（{e}），没法对比 —— 这不是「0 笔」，是不知道。")
    finally:
        live.close()
        back.close()


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

    # 旧备份按开机那一套升到最新；升不上来就停，现有的账本不动
    try:
        ready = _upgraded_copy(src)
    except Exception as e:  # noqa: BLE001 —— Alembic 认不出版本、缺列、外键对不上，都是「这份用不了」
        sys.exit(
            f"这份备份升不到现在的表结构：{e}\n"
            "多半是它比现在的代码**新**（换回做这份备份时的代码版本），"
            "或者是 2026-09-23 之前的旧格式备份。什么都没动，换一份试试（--list 看有哪些）。"
        )
    # 升完的那份，原有的每张表行数得一行不差（升级只许加东西）
    after = backup_svc.verify_file(ready)
    lost = [t for t, n in counts.items() if after.get(t) != n]
    if lost:
        sys.exit(f"升级之后这几张表的行数变了：{lost} —— 什么都没动。")

    if DB_PATH.exists():
        # 这些 --yes 时也要印：恢复是这个系统里最危险的一次人工确认，
        # 拍板的时候得看得见「这一下会丢掉什么」，而不只是一个文件名
        print(f"\n现在的账本：{DB_PATH}")
        _compare(ready)
        print("**先把服务停掉**（run.sh 那个进程），否则它还在往旧库里写。")
        # 停没停不靠人自觉：探一下。问之前探一次（没停就别让人白读一遍），输完 yes 再探一次
        _refuse_if_in_use()
        if "--yes" not in argv and input("停好了？输 yes 继续：").strip().lower() != "yes":
            sys.exit("没动任何东西。")
        _refuse_if_in_use()

    # ② 先在账本旁边拷好、落盘，**再**动现有的：拷到一半盘满或者 Ctrl-C，原来那本一点没动。
    # 原来是先把原件挪走、再直接往正式名字上拷 —— 半截的 nagaya.db 留在原地，
    # 服务一起来就是 malformed，原件躲在 replaced-* 里要人自己去找。盘满恰恰是出事那几天最可能的
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    part = DB_PATH.with_name(DB_PATH.name + ".restore.part")
    shutil.copy2(ready, part)
    with open(part, "rb+") as f:
        os.fsync(f.fileno())

    # ③ 现有的挪走，不删 —— 万一恢复错了那份，原来的还在
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
        # 库不在但 -wal 还在的话，旧 WAL 照样会盖上来
        for suffix in SIDECARS:
            Path(str(DB_PATH) + suffix).unlink(missing_ok=True)

    # 放上去的是**升过的那份拷贝**：验过的就是装上的，开机不用再升一遍。改名是原子的
    os.replace(part, DB_PATH)
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
        "换了机器的话所有人都要重登（签名密钥 data/.secret 不在备份里）。\n"
        "**手机上开着的编辑页退出去重进**：恢复之后新记的账会接着备份里的编号往下排，"
        "旧页面上那一笔的编号可能已经指着别人刚记的另一笔了。"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
