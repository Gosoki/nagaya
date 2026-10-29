"""备份回归。

要钉死的一条：**产出必须是一份能单独打开、内容对得上的完整库。**
只拷 nagaya.db 是不行的 —— 开着 WAL，没 checkpoint 的数据全在 -wal 里。
实测真实开发库主文件 4096 字节、-wal 3.9MB，单拷主文件那份连打开都打不开。
而这件事的可怕之处在于：它要到恢复那天才会被发现。
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import JST, Category, EntryKind, Member
from app.services import backup as backup_svc
from app.services import ledger
from app.services import settings as settings_svc


@pytest.fixture
def bk(session: Session, members, tmp_path: Path) -> Path:
    """备份目录指到 tmp，留 3 份。**源库是内存库** —— backup 问的是连接自己
    （PRAGMA database_list），不是模块级的 DB_PATH，所以测试碰不到真账本。"""
    settings_svc.set_(session, "backup_path", str(tmp_path / "bk"))
    settings_svc.set_(session, "backup_keep", 3)
    a, *_ = members
    c = Category(name="日用品")
    session.add(c)
    session.commit()
    session.refresh(c)
    ledger.create_entry(session, actor_id=a.id, kind=EntryKind.expense,
                        on=dt.date(2026, 9, 21), amount=3_000, payer_id=a.id, category_id=c.id)
    return tmp_path / "bk"


def test_a_backup_is_a_database_you_can_actually_open(session: Session, bk: Path) -> None:
    made = backup_svc.run(session)
    path = Path(made["path"])
    assert path.is_file() and made["bytes"] > 0

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert list(con.execute("PRAGMA integrity_check"))[0][0] == "ok"
    assert list(con.execute("select count(*) from member"))[0][0] == 3
    assert list(con.execute("select amount_jpy from entry"))[0][0] == 3_000
    # 分摊快照也得在 —— 只有 entry 没有 entry_share 的备份是算不出钱的
    assert list(con.execute("select count(*) from entry_share"))[0][0] > 0
    con.close()
    # 自洽的单文件，不该再拖着 -wal
    assert not Path(str(path) + "-wal").exists()
    # 里面有密码哈希和头像
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_a_half_written_backup_never_gets_the_final_name(session: Session, bk: Path) -> None:
    """断电 / kill -9 / 盘满只许留下一个 .part。

    写了一半却叫 nagaya-*.db 的文件比没有备份更糟：它让人以为自己有。
    """
    good = backup_svc.run(session)
    stray = bk / (Path(good["path"]).name + backup_svc.PART_SUFFIX)
    stray.write_bytes(b"half written")
    os.utime(stray, (0, 0))                       # 假装是上一轮被 kill 掉留下的
    backup_svc.run(session)
    assert not stray.exists(), "够旧的 .part 残骸该被扫掉"
    assert all(backup_svc.NAME_RE.match(p.name) for p in bk.iterdir()), \
        "目录里除了正式备份不该有别的"


def test_two_backups_in_the_same_second_do_not_collide(session: Session, bk: Path) -> None:
    """名字精确到秒，同一秒里跑两次（cron 撞上手点）不许覆盖已经验过的那份。"""
    names = {backup_svc.run(session)["name"] for _ in range(4)}
    assert len(names) == 4, f"四次该有四个名字，实际 {names}"


def test_pruning_keeps_the_newest_and_leaves_strangers_alone(session: Session, bk: Path) -> None:
    """留最近 keep 份，**只认自己产出的文件名**。

    备份目录很可能是 iCloud 里一个还放着别的东西的文件夹，手滑删掉人家的不可接受。
    排序按文件名不按 mtime：名字里是零填充时间戳，而 mtime 会被 rsync / 同步盘改掉。
    """
    made = [backup_svc.run(session)["name"] for _ in range(5)]
    stranger = bk / "我自己拷的.db"
    stranger.write_text("别动我")
    left = {p.name for p in bk.iterdir() if backup_svc.NAME_RE.match(p.name)}
    assert left == set(made[-3:]), f"该只剩最新三份，实际 {sorted(left)}"
    assert stranger.exists()


def test_an_empty_source_is_refused_and_nothing_is_pruned(
    session: Session, bk: Path
) -> None:
    """**账本被清空时不许备份，也不许轮转。**

    挡的是最坏的那个剧本：库被误删或换成空库之后备份照跑，
    keep 天之内把每一份好备份都轮转掉 —— 等发现时已经没有任何东西可恢复了。
    全新安装也走这一支，那时本来也没有什么值得存。
    """
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    for _ in range(3):
        backup_svc.run(session)
    before = {p.name for p in bk.iterdir()}

    # 另起一个**本来就空**的库，指向同一个备份目录 ——
    # 比把现有库删空干净：成员被 audit_log / statement / category 一路引着，
    # 删得动才怪，而那不是这条用例要验的事
    empty = create_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    SQLModel.metadata.create_all(empty)
    with Session(empty) as blank:
        settings_svc.seed_settings(blank)
        settings_svc.set_(blank, "backup_path", str(bk))
        settings_svc.set_(blank, "backup_keep", 1)      # 轮转开着才说明问题
        with pytest.raises(backup_svc.BackupError) as e:
            backup_svc.run(blank)
    assert e.value.code == "backup_empty_source"
    assert {p.name for p in bk.iterdir()} == before, "旧备份必须一份不少地留着"


def test_verify_file_rejects_a_non_database(session: Session, bk: Path) -> None:
    """备份最坏的失败方式是「文件在、却是坏的」。宁可没有，也不要一份骗人的。

    这条只验 verify_file 认得出「根本不是库」（恢复之前、状态页上用它）。
    run() 里验不过的那份有没有被删掉，见下面那条参数化的。"""
    bk.mkdir(parents=True, exist_ok=True)
    bad = bk / "nagaya-19700101-000000.db"
    bad.write_bytes(b"this is not a database")
    with pytest.raises(backup_svc.BackupError) as e:
        backup_svc.verify_file(bad)
    assert e.value.code == "backup_corrupt"


def test_an_unusable_directory_says_which_way_it_is_unusable(
    session: Session, bk: Path, tmp_path: Path
) -> None:
    settings_svc.set_(session, "backup_path", "/dev/null/nope")
    with pytest.raises(backup_svc.BackupError) as e:
        backup_svc.run(session)
    assert e.value.code == "backup_dir_missing"

    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    settings_svc.set_(session, "backup_path", str(ro))
    try:
        with pytest.raises(backup_svc.BackupError) as e:
            backup_svc.run(session)
        assert e.value.code == "backup_not_writable", "建得出目录 ≠ 写得进文件"
    finally:
        ro.chmod(0o700)


def test_it_does_not_quietly_create_the_mount_point(session: Session, tmp_path: Path) -> None:
    """外接盘没插时，**不许**把 /Volumes/移动盘 也一路建出来。

    建了的话备份从此写在内置盘上，而人以为在移动盘上 —— 盘坏了才发现一份都没有。
    """
    settings_svc.set_(session, "backup_path", str(tmp_path / "没插的盘" / "backups"))
    with pytest.raises(backup_svc.BackupError) as e:
        backup_svc.run(session)
    assert e.value.code == "backup_dir_missing"
    assert not (tmp_path / "没插的盘").exists(), "上级目录一个都不许替他建"


def test_a_quote_in_the_path_is_not_a_syntax_error(session: Session, tmp_path: Path, members) -> None:
    """路径是面板上能改的设置项，而 `VACUUM INTO '<path>'` 是拼字符串 ——
    拼的话一个单引号就是语法错，所以必须参数化传。"""
    target = tmp_path / "a'b"
    target.mkdir()
    settings_svc.set_(session, "backup_path", str(target))
    settings_svc.set_(session, "backup_keep", 3)
    made = backup_svc.run(session)
    assert Path(made["path"]).is_file()


def test_status_is_probed_not_remembered(session: Session, bk: Path) -> None:
    """状态每次现场探。存一条「上次成功」的结论会过期：目录早被删了，它还说一切正常。"""
    st = backup_svc.status(session)
    assert st["error"] is None and st["count"] == 0 and st["last_at"] is None

    name = backup_svc.run(session)["name"]
    st = backup_svc.status(session)
    assert st["count"] == 1 and st["last_name"] == name and st["stale"] is False

    (bk / name).unlink()
    st = backup_svc.status(session)
    assert st["count"] == 0 and st["last_at"] is None, "文件没了就该说没有"

    settings_svc.set_(session, "backup_path", "/dev/null/nope")
    assert backup_svc.status(session)["error"] == "backup_dir_missing"


def test_run_if_due_respects_the_interval(session: Session, bk: Path) -> None:
    settings_svc.set_(session, "backup_every_hours", 24)
    assert backup_svc.run_if_due(session) is not None, "一份都没有时该立刻备一份"
    assert backup_svc.run_if_due(session) is None, "刚备过就别再备"

    settings_svc.set_(session, "backup_every_hours", 0)
    assert backup_svc.run_if_due(session) is None, "0 ＝ 不自动备"


def test_restore_does_not_let_a_stale_wal_climb_back_on(tmp_path: Path) -> None:
    """恢复时**必须**把 -wal / -shm 一起处理掉。

    这是整条链路上唯一致命的一步，而它长得完全不像危险：实测「把 .db 拷回去」
    却留着旧 `-wal`，SQLite 会把旧 WAL 的页盖到新文件上 —— 第一次读还给得出数字
    （44 笔的备份读出来 127 笔），再读就是 `database disk image is malformed`。
    人以为自己恢复好了，拿到的是个混出来的怪物。

    跑在子进程里：DB_PATH 是模块级的，在本进程里改不动，而这条用例的全部意义
    就是验「真的换库」那条路。
    """
    import subprocess
    import sys as _sys

    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "NAGAYA_DB": str(data / "nagaya.db")}
    run = lambda *a, **k: subprocess.run(  # noqa: E731
        [_sys.executable, *a], cwd=root, env=env, capture_output=True, text=True, **k
    )

    assert run("-m", "tools.seed_dev").returncode == 0
    # 种子库不许自动备份：产物和真备份同名同形，混进同一个目录之后
    # 「恢复最新那份」会把三个假室友盖到真账本上
    off = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.db import engine\n"
        "from app.services import settings as sv\n"
        "print(sv.get(Session(engine), 'backup_every_hours'))"
    ))
    assert off.stdout.strip() == "0", "seed_dev 该把自动备份关掉"
    made = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.db import engine\n"
        "from app.services import settings as sv, backup as bk\n"
        f"s=Session(engine);sv.set_(s,'backup_path',{str(tmp_path / 'bk')!r});print(bk.run(s)['name'])"
    ))
    assert made.returncode == 0, made.stderr
    before = int(run("-c", (
        "import sys,sqlite3;sys.path.insert(0,'.')\n"
        f"print(list(sqlite3.connect({str(data / 'nagaya.db')!r}).execute('select count(*) from entry'))[0][0])"
    )).stdout)

    # 备份之后又记了几笔 —— 恢复该把它们扔掉，回到备份那一刻
    add = run("-c", (
        "import sys,datetime as dt;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session, select\n"
        "from app.db import engine\n"
        "from app.models import Member, Category, EntryKind\n"
        "from app.services import ledger\n"
        "s=Session(engine);m=s.exec(select(Member)).first();c=s.exec(select(Category)).first()\n"
        "[ledger.create_entry(s,actor_id=m.id,kind=EntryKind.expense,on=dt.date(2026,9,22),"
        "amount=9999,payer_id=m.id,category_id=c.id) for _ in range(3)]"
    ))
    assert add.returncode == 0, add.stderr
    assert (data / "nagaya.db-wal").exists(), "前提：确实有一个旧 WAL 在那儿"

    done = run("-m", "tools.restore", "--yes")
    assert done.returncode == 0, done.stderr

    assert not (data / "nagaya.db-wal").exists(), "旧 WAL 必须没了，否则它会盖回来"
    assert not (data / "nagaya.db-shm").exists()
    assert list(data.glob("replaced-*")), "被换掉的那份要留着，恢复错了还能回头"

    con = sqlite3.connect(f"file:{data / 'nagaya.db'}?mode=ro", uri=True)
    assert list(con.execute("PRAGMA integrity_check"))[0][0] == "ok"
    assert list(con.execute("select count(*) from entry"))[0][0] == before
    con.close()


def test_status_actually_opens_the_newest_one(session: Session, bk: Path) -> None:
    """「共 N 份」只是数了数文件名，而这一屏的全部价值是「它不撒谎」。

    位腐、同步盘传了一半、iCloud 把内容抽走只留个占位 —— 名字都还在。
    只验最新那一份：它就是要恢复的那一份，而全验 30 份要半秒，
    这又是个每开一次设置页就调的 GET。
    """
    name = backup_svc.run(session)["name"]
    assert backup_svc.status(session)["last_ok"] is True

    (bk / name).write_bytes(b"truncated by the sync client")
    st = backup_svc.status(session)
    assert st["last_ok"] is False, "打不开的那份不许显示成正常"
    # 和「刚导出来的那份验不过、已经删掉了」不是一回事：这一份还好端端躺在那儿，
    # 界面上不能对着它说「已经删掉了」
    assert st["error"] == "backup_last_corrupt"
    # 状态里那几条正确信息照样要给：出错的时候人更需要知道「上次是什么时候、共几份」
    assert st["count"] >= 1 and st["last_at"] and st["last_name"]


def test_tests_never_write_into_the_real_backup_folder(session: Session, members) -> None:
    """跑测试不许碰 backend/backups/ —— 那是用户真备份待的地方。

    conftest 把 backup_path 指到 tmp 了。这条用例盯着那一行别被人删掉：
    忘了设的话假备份会和真备份同名同形混在一个目录里，
    而「恢复最新那份」就会盖错东西。审计的 agent 真往里塞过 13 份。
    """
    from app.services import backup as bk

    real = Path(__file__).resolve().parents[1] / "backups"
    before = {p.name for p in real.iterdir()} if real.is_dir() else set()
    bk.run(session)                      # 故意不设 backup_path，用 conftest 给的
    after = {p.name for p in real.iterdir()} if real.is_dir() else set()
    assert after == before, f"往真实备份目录里写了：{after - before}"
    assert str(bk.backup_dir(session)).startswith("/"), "该指到 tmp 而不是仓库里"


def test_concurrent_backups_do_not_destroy_each_other(tmp_path: Path) -> None:
    """同一秒里的几次备份**互相不能踩**。

    `.part` 的名字原来是从正式名字推出来的，于是同一秒里的两次算出同一个 `.part`：
    两边互相 unlink、互相往同一个文件里 VACUUM —— 实测 6 个并发**一份都产不出来**
    （disk I/O error / table member already exists），不是「一个成一个败」。

    而这不是假想：自动备份跑在后台线程里（asyncio.to_thread），
    用户在设置页点一下「立即备份」走的是请求线程，两边撞上同一秒就是这个场面。

    跑在真文件库上（不是内存库）：内存库每个连接各自一份数据，撞不出来。
    """
    import threading

    from sqlmodel import SQLModel, create_engine

    from app.services.settings import seed_settings

    engine = create_engine(f"sqlite:///{tmp_path}/x.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_settings(s)
        settings_svc.set_(s, "backup_path", str(tmp_path / "bk"))
        settings_svc.set_(s, "backup_keep", 50)
        ms = [Member(name=f"m{i}", display_name=f"M{i}", display_order=i,
                     joined_on=dt.date(2020, 1, 1)) for i in range(3)]
        for m in ms:
            s.add(m)
        cat = Category(name="日用品")
        s.add(cat)
        s.commit()
        for x in [*ms, cat]:
            s.refresh(x)
        ledger.create_entry(s, actor_id=ms[0].id, kind=EntryKind.expense, on=dt.date(2026, 9, 1),
                            amount=3_000, payer_id=ms[0].id, category_id=cat.id)

    done: list[object] = []
    def one() -> None:
        try:
            with Session(engine) as s2:
                done.append(backup_svc.run(s2)["name"])
        except Exception as e:                       # noqa: BLE001 —— 失败了也要记下来看
            done.append(e)

    threads = [threading.Thread(target=one) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    failed = [x for x in done if isinstance(x, Exception)]
    assert not failed, f"并发备份失败了 {len(failed)} 个：{failed[:2]}"
    assert not list((tmp_path / "bk").glob("*.part")), "不许留下半截文件"
    for p in (tmp_path / "bk").iterdir():
        if backup_svc.NAME_RE.match(p.name):
            backup_svc.verify_file(p)                # 每一份都得是完整的库


def _seeded(tmp_path: Path) -> tuple[Path, Path, object]:
    """在 tmp 里备一份 seed 库 + 一份备份，返回 (data 目录, 备份目录, 跑子进程的函数)。"""
    import subprocess
    import sys as _sys

    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "NAGAYA_DB": str(data / "nagaya.db")}
    def run(*a: str):
        return subprocess.run([_sys.executable, *a], cwd=root, env=env,
                              capture_output=True, text=True)
    assert run("-m", "tools.seed_dev").returncode == 0
    made = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.db import engine\n"
        "from app.services import settings as sv, backup as bk\n"
        f"s=Session(engine);sv.set_(s,'backup_path',{str(tmp_path / 'bk')!r});print(bk.run(s)['name'])"
    ))
    assert made.returncode == 0, made.stderr
    return data, tmp_path / "bk", run


def test_restore_works_when_the_ledger_is_gone(tmp_path: Path) -> None:
    """**库不在的时候恢复工具必须还能跑** —— 那正是唯一需要它的那天。

    原来它要先开 Session 读设置才知道备份在哪，于是「库被删」「换新机器」两种
    最需要恢复的场合都是 40 行 traceback，而且**顺手在 data/ 下建出一个空账本**：
    人在慌的时候看到的是一堆栈和一个凭空出现的空库。
    """
    data, bk, run = _seeded(tmp_path)
    for p in data.glob("nagaya.db*"):
        p.unlink()

    listed = run("-m", "tools.restore", f"--dir={bk}", "--list")
    assert listed.returncode == 0, listed.stderr
    assert "44 笔" in listed.stdout

    done = run("-m", "tools.restore", f"--dir={bk}", "--yes")
    assert done.returncode == 0, done.stderr
    assert not list(data.glob("replaced-*")), "库本来就不在，不该凭空挪出一个空壳"
    con = sqlite3.connect(f"file:{data / 'nagaya.db'}?mode=ro", uri=True)
    assert list(con.execute("PRAGMA integrity_check"))[0][0] == "ok"
    assert list(con.execute("select count(*) from entry"))[0][0] == 44
    con.close()


def test_restoring_twice_keeps_both_copies_of_the_old_ledger(tmp_path: Path) -> None:
    """「现有的库挪走不删」这张安全网，在第二次恢复时**不许**被自己抹掉。

    挪走的目录名原来按**备份**的时刻取，于是同一份连着恢复两次（以为刚才没成功、
    或者忘了停服务想重来）会算出同一个目录名，而 shutil.move 到一个已存在的文件
    是静默覆盖 —— 第二次抹掉的正是第一次好心留下的那本真账本。
    """
    data, _, run = _seeded(tmp_path)
    add = run("-c", (
        "import sys,datetime as dt;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session, select\n"
        "from app.db import engine\n"
        "from app.models import Member, Category, EntryKind\n"
        "from app.services import ledger\n"
        "s=Session(engine);m=s.exec(select(Member)).first();c=s.exec(select(Category)).first()\n"
        "[ledger.create_entry(s,actor_id=m.id,kind=EntryKind.expense,on=dt.date(2026,9,22),"
        "amount=7777,payer_id=m.id,category_id=c.id) for _ in range(3)]"
    ))
    assert add.returncode == 0, add.stderr

    for _ in range(2):
        time.sleep(1.1)                       # 名字精确到秒，隔开才看得出是两个目录
        assert run("-m", "tools.restore", "--yes").returncode == 0

    kept = sorted(data.glob("replaced-*"))
    assert len(kept) == 2, f"两次恢复该留下两份，实际 {[p.name for p in kept]}"
    counts = []
    for d in kept:
        con = sqlite3.connect(f"file:{d / 'nagaya.db'}?mode=ro", uri=True)
        counts.append(list(con.execute("select count(*) from entry where amount_jpy=7777"))[0][0])
        con.close()
    assert 3 in counts, "只存在于活账本里的那 3 笔被抹掉了 —— 后悔药没了"


def test_a_lookalike_name_with_an_impossible_date_is_ignored(session: Session, bk: Path) -> None:
    """名字形状对、日期不存在（13 月 99 日）：不算备份产出的，不许让自动备份和备份页跟着 500"""
    backup_svc.run(session)
    (bk / "nagaya-20261399-000000.db").write_bytes(b"not ours")
    backup_svc.status(session)
    for _ in range(4):                       # 留 3 份：多备几次让轮转真的跑起来
        backup_svc.run(session)
    assert (bk / "nagaya-20261399-000000.db").exists(), "不是自己产出的，轮转也不许删"


# ---------------------------------------------------------------- run() 里那几道验（#36）


def _tamper_integrity(part: Path) -> None:
    """只有 integrity_check 看得出的坏：条数、外键、表都对，空闲页链表的头被抹掉了。
    （改索引根页那种会先被「条数对不上」抓住，钉不住 integrity 这一道）"""
    con = sqlite3.connect(part)
    con.execute("create table zz(x)")
    con.executemany("insert into zz values (?)", [(b"x" * 3000,) for _ in range(20)])
    con.commit()
    con.execute("drop table zz")
    con.commit()
    con.close()
    raw = bytearray(part.read_bytes())
    raw[32:40] = bytes(8)                 # 空闲页链表的起点和页数
    part.write_bytes(bytes(raw))


def _tamper_sql(*sql: str):
    def go(part: Path) -> None:
        con = sqlite3.connect(part)
        con.execute("PRAGMA foreign_keys=OFF")
        for q in sql:
            con.execute(q)
        con.commit()
        con.close()
    return go


@pytest.mark.parametrize("tamper", [
    pytest.param(_tamper_integrity, id="integrity"),
    # update 不是 insert：条数不变，只让外键那一道认得出来
    pytest.param(_tamper_sql("update entry_share set member_id = 999 "
                             "where rowid = (select min(rowid) from entry_share)"), id="foreign-key"),
    pytest.param(_tamper_sql("drop table memo"), id="missing-table"),
    pytest.param(_tamper_sql("delete from audit_log where rowid = (select max(rowid) from audit_log)"), id="row-count"),
])
def test_a_bad_artifact_in_run_is_rejected_and_not_kept(
    session: Session, bk: Path, monkeypatch: pytest.MonkeyPatch, tamper
) -> None:
    """「当场验过才算数」那四道检查，**每一道单独钉住**，而且验不过的那份**一个字节都不留**。

    原来四道各删掉一道、甚至把 run() 里的整个 _verify 调用删掉、或者验不过时不删 .part，
    全套测试照样全绿 —— 而 README 承诺的是「宁可没有备份，也不要一份骗人的备份」。
    钩子挂在 VACUUM INTO 之后、验之前唯一的那一步（_fsync_file），在 .part 上动手脚。
    """
    real = backup_svc._fsync_file

    def hooked(path: Path) -> None:
        tamper(path)
        real(path)

    monkeypatch.setattr(backup_svc, "_fsync_file", hooked)
    with pytest.raises(backup_svc.BackupError) as e:
        backup_svc.run(session)
    assert e.value.code == "backup_corrupt"
    left = [p.name for p in bk.iterdir()]
    assert not [n for n in left if backup_svc.NAME_RE.match(n)], f"验不过的那份拿到了正式名字：{left}"
    assert not [n for n in left if n.endswith(backup_svc.PART_SUFFIX)], f".part 没删：{left}"


# ---------------------------------------------------------------- 账本自检（#25）


def test_a_broken_ledger_is_backed_up_but_nothing_is_pruned(session: Session, bk: Path) -> None:
    """账本本身不平（这里绕过 app 改一笔的分摊）：**这份照留，这一轮不轮转**，状态和红点都说出来。

    不这样的话，坏掉之后备份照跑、照轮转，keep 天之内坏之前的好备份全被转掉 ——
    而那时账单页只是一个查不出原因的 500。账修好之后一切自己恢复，不存任何结论。
    """
    from sqlalchemy import text

    good = [backup_svc.run(session)["name"] for _ in range(3)]          # keep=3：已经满了
    eid = session.execute(text("select entry_id from entry_share order by id limit 1")).scalar()
    session.execute(text("update entry_share set amount_jpy = amount_jpy + 1 "
                         "where id = (select min(id) from entry_share)"))
    session.commit()

    with pytest.raises(backup_svc.BackupError) as e:
        backup_svc.run(session)
    assert e.value.code == "ledger_invariant_broken"
    assert e.value.detail["entries"] == [eid], "要点名是哪一笔"
    kept = sorted(p.name for p in bk.iterdir() if backup_svc.NAME_RE.match(p.name))
    assert kept[:3] == good and len(kept) == 4, f"坏账本那份该留着、好的一份都不许转掉：{kept}"

    st = backup_svc.status(session)
    assert st["error"] == "ledger_invariant_broken" and st["last_ok"] is True, "文件本身是好的"
    assert backup_svc.alert(session) == "ledger_invariant_broken"
    settings_svc.set_(session, "backup_every_hours", 24)
    assert backup_svc.run_if_due(session) is None, "账不平也照原来的节奏备，不是每小时来一份"

    session.execute(text("update entry_share set amount_jpy = amount_jpy - 1 "
                         "where id = (select min(id) from entry_share)"))
    session.commit()
    made = backup_svc.run(session)
    assert made["pruned"], "账修好之后照常轮转"
    assert backup_svc.status(session)["error"] is None


def test_ledger_problems_names_each_kind_of_break() -> None:
    """三条恒等式各自认得出自己那种坏：分摊合计 ≠ 金额（含软删的）、余额合计 ≠ 0、转账形状不对"""
    con = sqlite3.connect(":memory:")
    con.executescript(
        "create table entry(id integer primary key, kind text, amount_jpy int, payer_id int,"
        " to_member_id int, deleted_at text);"
        "create table entry_share(id integer primary key, entry_id int, member_id int, amount_jpy int);"
        "insert into entry values (1,'expense',300,1,null,null),(2,'settlement',100,2,1,null),"
        " (3,'expense',90,1,null,'2026-09-01');"
        "insert into entry_share(entry_id,member_id,amount_jpy) values (1,1,100),(1,2,100),(1,3,100),(2,1,100),"
        " (3,1,30),(3,2,30),(3,3,30);"
    )
    assert backup_svc.ledger_problems(con) is None
    con.execute("update entry_share set amount_jpy = 31 where entry_id = 3 and member_id = 3")
    assert backup_svc.ledger_problems(con) == {"entries": [3], "total": 0}, "软删的那笔也要查"
    con.execute("update entry_share set amount_jpy = 30 where entry_id = 3 and member_id = 3")
    con.execute("update entry_share set member_id = 3 where entry_id = 2")
    assert backup_svc.ledger_problems(con) == {"entries": [2], "total": 0}, "转账记到了别人头上"


# ---------------------------------------------------------------- 状态里的另外几样（#74 #27 #28）


def _file_ledger(tmp_path: Path):
    """一个真文件上的库：stale_copies 要问「账本在哪个目录」，内存库答不出来"""
    from sqlalchemy.pool import NullPool
    from sqlmodel import SQLModel, create_engine

    data = tmp_path / "data"
    data.mkdir()
    engine = create_engine(f"sqlite:///{data}/nagaya.db", poolclass=NullPool)
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    settings_svc.seed_settings(s)
    settings_svc.set_(s, "backup_path", str(tmp_path / "bk"))
    s.add(Member(name="a", display_name="A", joined_on=dt.date(2026, 1, 1)))
    s.commit()
    return data, s


def test_status_counts_the_old_copies_lying_next_to_the_ledger(tmp_path: Path) -> None:
    """升级前的快照、恢复时挪走的旧账本：**只数不删**，可得让人看见它们在那儿。"""
    data, s = _file_ledger(tmp_path)
    try:
        assert backup_svc.status(s)["stale_copies"] == {"count": 0, "bytes": 0, "oldest": None}
        shot = data / "before-migrate-0001-20261001-120000.db"
        shot.write_bytes(b"x" * 1000)
        os.utime(shot, (dt.datetime(2026, 10, 1, 12, tzinfo=JST).timestamp(),) * 2)
        aside = data / "replaced-20261020-000000"
        aside.mkdir()
        (aside / "nagaya.db").write_bytes(b"y" * 300)
        (aside / "nagaya.db-wal").write_bytes(b"z" * 200)
        (data / "nagaya.db.restore.part").write_bytes(b"not counted")   # 只认那两种前缀
        got = backup_svc.status(s)["stale_copies"]
        assert got["count"] == 2 and got["bytes"] == 1500
        assert got["oldest"].startswith("2026-10-01")
        assert shot.exists() and aside.exists(), "一个都不许删"
    finally:
        s.close()


def test_stale_copies_is_unknown_for_an_in_memory_ledger(session: Session, members) -> None:
    assert backup_svc.status(session)["stale_copies"] is None


def test_custom_path_means_someone_pointed_it_elsewhere() -> None:
    """自己指了目录、却和账本同盘：多半是外接盘 / NAS 没挂上（Linux 挂载点没挂上时就是根盘上
    一个空目录，「只建最后一级」挡不住）。界面拿 custom_path + same_disk 升警告色。
    只解析路径，不碰盘 —— 默认目录就是真备份待的地方"""
    for same in ("./backups", "backups", "./backups/", str(backup_svc.BASE_DIR / "backups")):
        assert backup_svc._custom_path(same) is False, same
    assert backup_svc._custom_path("/mnt/nas/nagaya") is True


def test_alert_lights_up_only_when_something_is_wrong(
    client, auth, session: Session, tmp_path: Path
) -> None:
    """红点只在真出事时亮：报错了、或者自动备份开着却超过两个间隔没出新的。

    **不亮的**：一份都还没有（刚改完目录）、自动备份是自己关掉的、和账本同盘（默认就同盘）。
    红点常亮的话，到真出事那天没人当回事。"""
    get = lambda: client.get("/api/backup/alert", headers=auth).json()["alert"]  # noqa: E731
    settings_svc.set_(session, "backup_every_hours", 24)
    assert get() is None, "一份都还没有、也没报错：不是警报"

    made = Path(backup_svc.run(session)["path"])
    assert get() is None
    old = (dt.datetime.now() - dt.timedelta(days=5)).timestamp()
    os.utime(made, (old, old))                 # 名字和 mtime 取小的那个：mtime 一老就算老
    assert get() == "backup_stale"
    settings_svc.set_(session, "backup_every_hours", 0)
    assert get() is None, "自动备份是自己关的，太久没备不算出事"

    settings_svc.set_(session, "backup_path", "/dev/null/nope")
    assert get() == "backup_dir_missing"


def test_a_stuck_backup_target_does_not_starve_the_rest_of_the_app(tmp_path: Path, monkeypatch) -> None:
    """备份目标卡住了（NAS 掉线、网络盘 hard mount、同步盘占位文件在下载）：红点那个接口
    每次开 App、切回前台都要探一遍目录。原来探的整段时间都揣着一条库连接，池子一共 5 条，
    几次开 App 就占满 —— 之后记账、看账单全部等到超时然后 500。

    池子照生产的配（常驻 1、最多再开 4），超时压到 2 秒好让没修的时候快点失败。
    最新那份「读不动」：verify_file 一直卡到用例放行。"""
    import threading
    import time as time_mod

    from fastapi.testclient import TestClient
    from sqlmodel import SQLModel, create_engine

    from app.auth import hash_password
    from app.db import get_session
    from app.main import app as fastapi_app

    engine = create_engine(f"sqlite:///{tmp_path / 'nagaya.db'}", connect_args={"check_same_thread": False},
                           pool_size=1, max_overflow=4, pool_timeout=2)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        settings_svc.seed_settings(s)
        settings_svc.set_(s, "backup_path", str(tmp_path / "bk"))
        s.add(Member(name="a", display_name="A", joined_on=dt.date(2026, 1, 1),
                     password_hash=hash_password("pw123456")))
        s.commit()
        backup_svc.run(s)

    stuck, release = threading.Event(), threading.Event()

    def hangs(path: Path) -> dict[str, int]:
        stuck.set()
        release.wait(timeout=15)
        return {"member": 1}

    def per_request():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(backup_svc, "verify_file", hangs)
    fastapi_app.dependency_overrides[get_session] = per_request
    alerts: list[threading.Thread] = []
    try:
        client = TestClient(fastapi_app)
        token = client.post("/api/auth/login", json={"name": "a", "password": "pw123456"}).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        codes: list[int] = []

        def open_app() -> None:
            codes.append(client.get("/api/backup/alert", headers=auth).status_code)

        alerts += [threading.Thread(target=open_app) for _ in range(6)]
        for t in alerts:
            t.start()
        assert stuck.wait(timeout=5)
        deadline = time_mod.monotonic() + 3
        while len(codes) < 5 and time_mod.monotonic() < deadline:
            time_mod.sleep(0.02)
        assert len(codes) == 5, "已经有一个在探：后来的不排队，当场回上一次的结果"
        assert engine.pool.checkedout() == 0, "正卡在探目录的那一个也不许揣着库连接"
        t0 = time_mod.monotonic()
        r = client.get("/api/members", headers=auth)
        took = time_mod.monotonic() - t0
        assert r.status_code == 200 and took < 1, f"{r.status_code}，等了 {took:.1f} 秒：库连接被卡住的红点占光了"
    finally:
        release.set()
        for t in alerts:
            t.join()
        fastapi_app.dependency_overrides.clear()
        engine.dispose()
    assert codes == [200] * 6


# ---------------------------------------------------------------- 恢复：先说清楚、服务开着不动（#29 #30）


def test_restore_refuses_while_the_service_still_has_the_ledger_open(tmp_path: Path) -> None:
    """服务没停就换库：它手里那条连接还指着被挪走的旧文件，之后回了 201 的账全写进 replaced-*，
    空闲一分钟之后新记的又从备份里最大的 id 往后编号 —— 同一个 id 指两笔不同的账。
    --yes 也一样拒绝，**什么都不动**。"""
    import subprocess
    import sys as _sys

    data, bk, run = _seeded(tmp_path)
    root = Path(__file__).resolve().parents[1]
    holder = subprocess.Popen(
        [_sys.executable, "-c", (
            "import sys,time;sys.path.insert(0,'.')\n"
            "from sqlmodel import Session, select\n"
            "from app.db import engine\n"
            "from app.models import Member\n"
            # 真读一张表：服务每处理一个请求都会，连接从此挂着 WAL 的共享锁
            "s=Session(engine);s.exec(select(Member)).all();s.close()\n"
            "print('ready',flush=True);time.sleep(30)"
        )],
        cwd=root, env={**os.environ, "NAGAYA_DB": str(data / "nagaya.db")},
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        before = sorted(p.name for p in data.iterdir())
        done = run("-m", "tools.restore", f"--dir={bk}", "--yes")
        assert done.returncode != 0, done.stdout
        assert "服务还开着" in done.stderr
        assert sorted(p.name for p in data.iterdir()) == before, "拒绝了就一样都不许动"
        assert not list(data.glob("replaced-*"))
    finally:
        holder.kill()
        holder.wait()

    # 服务停了（持有连接的进程没了）就照常能恢复
    assert run("-m", "tools.restore", f"--dir={bk}", "--yes").returncode == 0


def test_restore_says_what_it_will_throw_away(tmp_path: Path) -> None:
    """确认之前把「这一下会丢掉什么」摆出来：备份之后新记的几笔、改过的、删过的。

    **先认是不是同一本账**：另一本账的备份 id 照样从 1 编起，按 id 比出来「会丢 0 笔」
    是一句假话 —— 那种只说「不是同一本，恢复等于整本换掉」，不给数。"""
    data, bk, run = _seeded(tmp_path)
    add = run("-c", (
        "import sys,datetime as dt;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session, select\n"
        "from app.db import engine\n"
        "from app.models import Member, Category, EntryKind, Entry\n"
        "from app.services import ledger\n"
        "s=Session(engine);m=s.exec(select(Member)).first();c=s.exec(select(Category)).first()\n"
        "[ledger.create_entry(s,actor_id=m.id,kind=EntryKind.expense,on=dt.date(2026,9,22),"
        "amount=7777,payer_id=m.id,category_id=c.id,title='备份之后') for _ in range(3)]\n"
        "e=s.get(Entry,40);ledger.delete_entry(s,e,actor_id=m.id)\n"
        "e=s.get(Entry,41);ledger.update_entry(s,e,actor_id=m.id,version=e.version,fields={'amount_jpy':9999})"
    ))
    assert add.returncode == 0, add.stderr
    done = run("-m", "tools.restore", f"--dir={bk}", "--yes")
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "备份之后新记的 3 笔会没有（合计 ¥23,331" in out
    assert "#45  2026-09-22  ¥7,777  备份之后" in out
    assert "改过的 1 笔" in out and "删掉 / 撤销删除的 1 笔" in out

    # 另一本账（另起一个种子库）的备份：不许按 id 比出一个「会丢几笔」
    other = tmp_path / "other"
    other.mkdir()
    o_data, o_bk, _ = _seeded(other)
    done = run("-m", "tools.restore", f"--dir={o_bk}", "--yes")
    assert done.returncode == 0, done.stderr
    assert "不是同一本" in done.stdout
    assert "会没有" not in done.stdout
