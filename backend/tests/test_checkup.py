"""tools.checkup：只读体检。

要钉住三件事：
  * 干净的账本退出码 0 —— 体检要是在好账本上也喊「必须修」，第二次就没人信它了；
  * 账本坏了（这里直接改库，让一笔的分摊合计对不上金额）退出码 1，并且点名是哪一笔；
  * **只读**：跑完之后活库的主文件和 -wal 一个字节都没变，临时快照也删干净了。

跑在子进程里：tools.checkup 要在 import app 之前把 NAGAYA_DB 指到快照，
本进程里 app.db 早就按测试库建好了连接，改不动。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_checkup_passes_a_clean_ledger_and_fails_a_broken_share(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = data / "nagaya.db"
    env = {**os.environ, "NAGAYA_DB": str(db), "TMPDIR": str(tmp_path / "tmp")}
    (tmp_path / "tmp").mkdir()

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, *a], cwd=ROOT, env=env, capture_output=True, text=True)

    assert run("-m", "tools.seed_dev").returncode == 0
    # 备份指到 tmp 并做一份：I1 要拿它和活库比。不指的话默认是 backend/backups/ ——
    # 那里放的是真账本的备份，和种子库一比全是「不是同一本」
    made = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.db import engine\n"
        "from app.services import settings as sv, backup as bk\n"
        f"s=Session(engine);sv.set_(s,'backup_path',{str(tmp_path / 'bk')!r});bk.run(s)"
    ))
    assert made.returncode == 0, made.stderr

    before = (_digest(db), _digest(Path(f"{db}-wal")))
    clean = run("-m", "tools.checkup")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "【必须修】全部通过" in clean.stdout
    assert "通过  I1" in clean.stdout and "没比" not in clean.stdout, "I1 该真的拿备份比过，而不是跳过"
    assert (_digest(db), _digest(Path(f"{db}-wal"))) == before, "体检动了活库"
    assert not list((tmp_path / "tmp").iterdir()), "临时快照（整本账的明文）没删掉"

    # 绕过 app 改一笔的分摊：金额和分摊合计对不上
    con = sqlite3.connect(db)
    eid = con.execute("select entry_id from entry_share order by id limit 1").fetchone()[0]
    con.execute("update entry_share set amount_jpy = amount_jpy + 1 where id = (select min(id) from entry_share)")
    con.commit()
    con.close()

    broken = run("-m", "tools.checkup")
    assert broken.returncode == 1, broken.stdout + broken.stderr
    assert "没过  B1" in broken.stdout and f"#{eid} " in broken.stdout, "要点名是哪一笔"
    assert "没过  G2" in broken.stdout, "库里的行和最后一条审计对不上 ＝ 有人绕过 app 改过"
    assert not list((tmp_path / "tmp").iterdir())


def test_checkup_reads_a_backup_file_without_a_live_ledger(tmp_path: Path) -> None:
    """--file 体检任意一份备份：拷回 Mac 上、或者活库已经打不开的时候用。不需要活库在"""
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "NAGAYA_DB": str(data / "nagaya.db")}
    seeded = subprocess.run([sys.executable, "-m", "tools.seed_dev"], cwd=ROOT, env=env,
                            capture_output=True, text=True)
    assert seeded.returncode == 0
    copy = tmp_path / "copy.db"
    con = sqlite3.connect(data / "nagaya.db")
    con.execute("VACUUM INTO ?", (str(copy),))
    con.close()
    for p in data.glob("nagaya.db*"):
        p.unlink()

    for args in ([f"--file={copy}"], ["--file", str(copy)]):      # 空格隔开的写法也认
        out = subprocess.run(
            [sys.executable, "-m", "tools.checkup", *args],
            cwd=ROOT, env={**env, "TMPDIR": tempfile.gettempdir()}, capture_output=True, text=True,
        )
        assert out.returncode == 0, args + [out.stdout + out.stderr]
        assert f"备份文件：{copy.resolve()}" in out.stdout, args
    assert not (data / "nagaya.db").exists(), "体检一份备份不该顺手建出一个空的活库"


def test_checkup_refuses_arguments_it_does_not_know(tmp_path: Path) -> None:
    """原来只认 `--file=`，别的参数悄悄扔掉：`--flie=备份.db`、光写一个路径，体检的都是活账本，
    照样一份干净的报告 —— 人却以为查的是那份备份"""
    env = {**os.environ, "NAGAYA_DB": str(tmp_path / "nope.db")}
    for args in (["--flie=x.db"], ["x.db"], ["--file"], ["--file="], ["--file", "--all"], ["--file=a", "--file=b"]):
        out = subprocess.run([sys.executable, "-m", "tools.checkup", *args],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        assert out.returncode == 2 and "用法" in out.stderr, (args, out.stdout, out.stderr)


# ---------------------------------------------------- I1 没比 ≠ 通过


def _seeded_with_backup(tmp_path: Path):
    """种子账本，备份目录指到 tmp 做一份。返回 (活库, 备份文件, 跑子进程)"""
    data = tmp_path / "data"
    data.mkdir()
    db = data / "nagaya.db"
    (tmp_path / "tmp").mkdir()
    env = {**os.environ, "NAGAYA_DB": str(db), "TMPDIR": str(tmp_path / "tmp")}

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, *a], cwd=ROOT, env=env, capture_output=True, text=True)

    assert run("-m", "tools.seed_dev").returncode == 0
    made = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.db import engine\n"
        "from app.services import settings as sv, backup as bk\n"
        f"s=Session(engine);sv.set_(s,'backup_path',{str(tmp_path / 'bk')!r});print(bk.run(s)['path'])"
    ))
    assert made.returncode == 0, made.stderr
    return db, Path(made.stdout.strip().splitlines()[-1]), run


def _says_i1_passed_or_all_fine(out: str) -> bool:
    return "通过  I1" in out or "全部成立" in out or "全部通过" in out


def test_a_backup_of_another_ledger_is_not_a_pass(tmp_path: Path) -> None:
    """最新那份备份和活账本不是同一本：原来记成一条空的 I1，印「通过」、结论「全部成立」。
    可这正是活账本被整本换掉（卷没挂上、放错文件）时的样子 —— 要印「没比」，进「要人核对」"""
    _, backup, run = _seeded_with_backup(tmp_path)
    con = sqlite3.connect(backup)
    con.execute("update member set created_at = '2000-01-01 00:00:00.000000' where id = 1")
    con.commit()
    con.close()

    out = run("-m", "tools.checkup")
    assert out.returncode == 0, out.stdout + out.stderr
    assert not _says_i1_passed_or_all_fine(out.stdout), out.stdout
    assert "没比  I1" in out.stdout
    review = out.stdout.split("【要人核对】")[1].split("【仅供参考】")[0]
    assert "I1 最新备份和这本账不是同一本" in review


def test_a_live_ledger_that_became_empty_is_called_out(tmp_path: Path) -> None:
    """数据卷没挂上：活账本是 init_db 新建的空库，备份目录里是真账本的备份。原来照样「全部通过」"""
    db, _, run = _seeded_with_backup(tmp_path)
    for p in db.parent.glob("nagaya.db*"):
        p.unlink()
    fresh = run("-c", (
        "import sys;sys.path.insert(0,'.')\n"
        "from sqlmodel import Session\n"
        "from app.init_db import init_db\n"
        "init_db()\n"
        "from app.db import engine\n"
        "from app.services import settings as sv\n"
        f"sv.set_(Session(engine),'backup_path',{str(tmp_path / 'bk')!r})"
    ))
    assert fresh.returncode == 0, fresh.stderr

    out = run("-m", "tools.checkup")
    assert not _says_i1_passed_or_all_fine(out.stdout), out.stdout
    review = out.stdout.split("【要人核对】")[1].split("【仅供参考】")[0]
    assert "空库" in review and "一个成员都没有" in review


# ---------------------------------------------------- 拍不了快照时说什么


def test_only_a_broken_file_is_sent_to_tools_restore(tmp_path: Path, monkeypatch) -> None:
    """拍不了快照原来一律「这本身就是要修的事：试试 tools.restore」—— 锁着、权限不对也这么说，
    照着去恢复就是拿备份盖掉一本好账。只有文件本身坏了才提 restore"""
    import functools

    import pytest

    from tools import checkup

    def says(path: Path) -> str:
        with pytest.raises(SystemExit) as e:
            checkup._snapshot(path, tmp_path)
        return str(e.value.code)

    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database at all" * 200)
    assert "tools.restore" in says(garbage)

    good = tmp_path / "good.db"
    sqlite3.connect(good).executescript("create table t(x); insert into t values (1);").close()

    holder = sqlite3.connect(good)
    holder.execute("pragma locking_mode=exclusive")
    holder.execute("begin exclusive")
    # 默认等 5 秒才认锁；这条用例不需要等那么久
    monkeypatch.setattr(sqlite3, "connect", functools.partial(sqlite3.connect, timeout=0.1))
    try:
        locked = says(good)
    finally:
        holder.rollback()
        holder.close()
    assert "锁" in locked and "restore" not in locked, locked

    good.chmod(0)
    try:
        if os.access(good, os.R_OK):          # root 跑的话 chmod 拦不住，这一半没法演
            return
        closed = says(good)                   # 原来连接在 try 外面：直接一屏 traceback
    finally:
        good.chmod(0o600)
    assert "打不开" in closed and "不是该去恢复的理由" in closed, closed


# ---------------------------------------------------- 要人核对：新的在前；日期按日本时间


_NINE_BILLS = """
import datetime as dt, sys
sys.path.insert(0, '.')
from sqlmodel import Session, select
from app.init_db import init_db
init_db()
from app.db import engine
from app.models import Category, EntryKind, Member
from app.services import settings as sv
from app.services.bill import cut_statement
from app.services.ledger import create_entry
s = Session(engine)
sv.set_(s, 'backup_path', sys.argv[1])
a = Member(name='a', display_name='A', joined_on=dt.date(2026, 1, 1))
s.add(a)
s.commit()
cat = {c.name: c.id for c in s.exec(select(Category))}
for i in range(9):
    on = dt.date(2026, 2 + i, 20)
    for amount in (60000, 60000):                     # 房租每期分两笔付：E2 每张都报
        create_entry(s, actor_id=a.id, kind=EntryKind.expense, on=on, amount=amount,
                     payer_id=a.id, category_id=cat['房租'])
    if i < 8:                                         # 第 9 张忘了电费：E1
        create_entry(s, actor_id=a.id, kind=EntryKind.expense, on=on, amount=8000,
                     payer_id=a.id, category_id=cat['电费'])
    cut_statement(s, actor_id=a.id, on=on)
"""


def _samples_of(out: str, code: str) -> list[str]:
    """报告里某一项底下列出来的那几行"""
    lines = out.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(f"  {code} "))
    got = []
    for line in lines[at + 1:]:
        if not line.startswith(" " * 10):
            break
        got.append(line.strip())
    return got


def test_review_lists_put_the_newest_first_and_dates_are_jst(tmp_path: Path) -> None:
    """「要人核对」原来老的在前、每项只列 8 条：历史上看过的那些（每月分两笔付的房租）占满样本位，
    最近那张新冒出来的只剩「还有 N 处」里的一个数。改成新的在前，被截掉的注明是更早的，--all 全列。
    日期按日本时间：早上 9 点前出的账按 UTC 截是前一天，和 app 里的「M/D 出账」对不上"""
    data = tmp_path / "data"
    data.mkdir()
    db = data / "nagaya.db"
    (tmp_path / "tmp").mkdir()
    env = {**os.environ, "NAGAYA_DB": str(db), "TMPDIR": str(tmp_path / "tmp")}

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, *a], cwd=ROOT, env=env, capture_output=True, text=True)

    built = run("-c", _NINE_BILLS, str(tmp_path / "bk"))
    assert built.returncode == 0, built.stderr
    con = sqlite3.connect(db)
    for sid in range(1, 10):                          # 每月 28 号 22:30 UTC ＝ 日本时间 29 号早上
        con.execute("update statement set cut_at = ? where id = ?", (f"2026-{1 + sid:02d}-28 22:30:00.000000", sid))
    con.commit()
    con.close()

    out = run("-m", "tools.checkup").stdout
    e2 = _samples_of(out, "E2")
    assert [line.split("  ")[0] for line in e2[:8]] == [f"第 {i} 张" for i in range(9, 1, -1)], out
    assert e2[8:] == ["…… 更早的还有 1 处（--all 全部列出）"], out
    assert _samples_of(out, "E1") == ["第 9 张（2026-10-29）的 电费：前 6 张有 6 张记了，这张按 ¥0 出的"], \
        "E1 的日期要按日本时间"

    everything = run("-m", "tools.checkup", "--all").stdout
    e2 = _samples_of(everything, "E2")
    assert [line.split("  ")[0] for line in e2] == [f"第 {i} 张" for i in range(9, 0, -1)], everything

    con = sqlite3.connect(db)                          # 时钟被往回调过：第 9 张早于第 8 张
    con.execute("update statement set cut_at = '2026-10-28 23:00:00.000000' where id = 8")
    con.commit()
    con.close()
    out = run("-m", "tools.checkup").stdout
    assert "第 9 张（2026-10-29 07:30）晚于第 8 张（2026-10-29 08:00）编号" in out, out
