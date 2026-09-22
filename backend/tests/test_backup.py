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
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import Category, EntryKind, Member
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


def test_a_corrupt_artifact_is_reported_not_kept(session: Session, bk: Path) -> None:
    """备份最坏的失败方式是「文件在、却是坏的」。宁可没有，也不要一份骗人的。"""
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
    assert st["error"] == "backup_corrupt"


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
