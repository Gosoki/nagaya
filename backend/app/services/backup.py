"""SQLite 备份 —— VACUUM INTO 出一个单文件完整库，当场验完才改名生效。

三条是这份代码存在的全部理由：

1. **库开着 WAL。** 实测主文件 `nagaya.db` 只有 4096 字节、`nagaya.db-wal` 有 3.9MB，
   「拷一下那个 .db」拷出来的是**零张表的空库** —— 而这件事要到恢复那天才会发现。
   `VACUUM INTO` 不用停服、不改源库，产出的是把 WAL 一并结算进去的单文件。
2. **写了一半的备份比没有备份更糟**（它让人以为自己有）。所以一律先写 `.part`，
   用一条独立连接打开验一遍（integrity_check ＋ 逐表对条数），验过了才
   `os.replace` 成正式名字。断电 / kill -9 / 盘满只会留下一个 `.part`，
   绝不会留下一个半截的 `nagaya-*.db`。
3. **备份必须能被发现失败。** 这屋里没有邮件没有推送，唯一的出口是 app 自己那一屏，
   所以 `status()` 每次都**现场探一遍**目录能不能写，而不是读一条「上次成功」的记录 ——
   存下来的那种会过期：目录早被删了，它还在说「一切正常」。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.models import JST
from app.services import settings as settings_svc
from app.settings_spec import SETTINGS_SPEC

class BackupError(ValueError):
    """和 LedgerError 同一条线：{code, message, detail}，界面文案留在前端。"""

    def __init__(self, code: str, message: str, **detail: Any):
        super().__init__(message)
        self.code = code
        self.detail = detail

#: 文件名里的时间取 JST。业务日期全按日本时间算，「每天一份」这句话里的
#: 「天」得是同一个天，否则日本时间半夜那几小时会算到前一天名下
NAME_FMT = "nagaya-%Y%m%d-%H%M%S.db"
#: 清理**只认**这个模式。备份目录可能是 iCloud 里一个还放着别的东西的文件夹，
#: 手滑删掉人家的文件是不可接受的
NAME_RE = re.compile(r"^nagaya-\d{8}-\d{6}\.db$")
PART_SUFFIX = ".part"


def _is_ours(name: str) -> bool:
    """备份自己产出的名字：形状对，**日期也得是真日期**。只看形状的话
    nagaya-20261399-000000.db 也算 —— 后面解析它的那一步一抛，自动备份从此停摆、备份页 500"""
    if not NAME_RE.match(name):
        return False
    try:
        dt.datetime.strptime(name, NAME_FMT)
    except ValueError:
        return False
    return True

#: backup_path 填相对路径时相对谁：backend/。和 .gitignore 里那行
#: `backend/backups/` 对得上。
#: **锚在包自己身上，不锚在 DB_PATH 上** —— 后者会随 NAGAYA_DB 指到哪儿而漂：
#: 把库放在 /tmp/x/nagaya.db 跑一下，备份就跑去了 /tmp/backups
BASE_DIR = Path(__file__).resolve().parents[2]

#: 盘上至少要剩「源库大小 ＋ 这么多」才动手。VACUUM INTO 的产物通常比源库小，
#: 但「刚刚好够」写出来的东西没人敢信 —— 宁可在还没动手时就明说不够
FREE_MARGIN = 32 * 1024 * 1024

#: 一个 .part 放超过这么久，只可能是上一轮被 kill 掉留下的残骸
STALE_PART_SECONDS = 6 * 3600

# ---------------------------------------------------------------- 位置

def resolve_backup_path(raw: str) -> Path:
    """设置里填的那串路径最后落在哪。相对路径相对 backend/

    解析不了的一律 ValueError：`~不存在的用户/…` 在 expanduser 里抛的是 RuntimeError，
    NUL 抛 ValueError —— 统一成一种，调用方好接
    """
    try:
        path = Path(raw.strip() or "./backups").expanduser()
        return (path if path.is_absolute() else BASE_DIR / path).resolve()
    except (RuntimeError, OSError) as e:
        raise ValueError(str(e)) from e


def _raw_path(session: Session) -> str:
    """设置里填的那串备份路径，原样（还没解析）。"""
    return str(settings_svc.get(session, "backup_path") or "")


def backup_dir(session: Session) -> Path:
    return resolve_backup_path(_raw_path(session))

def source_path(session: Session) -> Path | None:
    """源库在哪 —— 问连接自己，不读模块级的 DB_PATH。

    测试用的是内存库，读 DB_PATH 会让测试去碰真账本；而问连接拿到的正是
    「这次备份的到底是哪个库」，恢复说明里也要用它。内存库返 None。
    """
    row = session.execute(text("PRAGMA database_list")).first()
    name = row[2] if row else ""
    return Path(name) if name else None

def _source_bytes(src: Path | None) -> int:
    """主文件 ＋ WAL。WAL 那半才是大头，只算主文件会把空间需求低估三个数量级。"""
    if src is None:
        return 0
    total = 0
    for suffix in ("", "-wal"):
        p = Path(str(src) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total

# ---------------------------------------------------------------- 预检

def _prepare_dir(raw: str) -> Path:
    try:
        # 解析也放进来：库里要是已经存了坏路径（NUL 之类，老版本没拦），
        # resolve() 抛的是 ValueError —— 不接住的话设置页的备份状态直接 500
        directory = resolve_backup_path(raw)
    except (OSError, ValueError) as e:
        raise BackupError("backup_dir_missing", f"备份目录用不了（{e}）", path="", parent="") from e
    try:
        existed = directory.is_dir()
        # **只建最后一级**（parents=False）。填成 /Volumes/移动盘/backups 而盘没插时，
        # parents=True 会老老实实在内置盘上把 /Volumes/移动盘 也建出来 ——
        # 从此备份全写在本机、人却以为在移动盘上。少建一级，这种错当场就报出来。
        # **这道防线只管「盘没挂上时上一级目录根本不存在」的情况**（macOS 的 /Volumes/…、
        # 插盘才建挂载点的那种自动挂载）。Linux 上 fstab / LXC bind / Docker volume 的挂载点
        # 没挂上时就是根盘上的一个空目录 —— 上一级在，mkdir 照样成功，备份悄悄写进本机。
        # 那种情况拦不住，只能说出来：status() 里 custom_path 和 same_disk 同时为真，
        # 设置页那一行升成警告色
        directory.mkdir(exist_ok=True)
        if not existed:
            directory.chmod(0o700)      # 整本账在里面。只管自己建的那个目录，
                                        # 人家已有的文件夹（同步盘之类）不去改权限
    except OSError as e:
        raise BackupError(
            "backup_dir_missing", f"备份目录用不了：{directory}（{e.strerror}）",
            path=str(directory), parent=str(directory.parent),
        ) from e

    # 「目录建得出来」不等于「文件写得进去」：只读挂载、别人的目录、满盘 ——
    # 都得真写一次才知道。名字带 pid **和线程号**：自动备份跑在后台线程、
    # 点「立即备份」走请求线程，只带 pid 的话同一进程里那两条就用同一个探针名
    probe = directory / f".nagaya-write-test-{os.getpid()}-{threading.get_ident()}"
    try:
        probe.write_bytes(b"ok")
    except OSError as e:
        raise BackupError(
            "backup_not_writable", f"备份目录写不进去：{directory}（{e.strerror}）",
            path=str(directory),
        ) from e
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return directory

def _check_space(src: Path | None, directory: Path) -> None:
    need = _source_bytes(src) + FREE_MARGIN
    free = shutil.disk_usage(directory).free
    if free < need:
        raise BackupError(
            "backup_disk_full", f"备份目录所在的盘只剩 {free} 字节，至少要 {need}",
            free=free, need=need, path=str(directory),
        )

def _sweep_parts(directory: Path) -> None:
    """扫掉上一轮被 kill 掉留下的半截文件。

    只扫**足够旧**的：另一个进程可能正在写它自己那一个（名字带秒，撞不上，
    但这一条让「每小时那次自动备份和手点同时发生」也不会互相拆台）。
    """
    now = dt.datetime.now().timestamp()
    for p in directory.glob(f"nagaya-*{PART_SUFFIX}"):
        try:
            if now - p.stat().st_mtime > STALE_PART_SECONDS:
                p.unlink()
        except OSError:
            pass

# ---------------------------------------------------------------- 验证

def _tables(con_or_session: Any) -> dict[str, int]:
    """逐表条数。表名从 sqlite_master 现读 —— 和 models.py 对不上时也照样能验。"""
    if isinstance(con_or_session, Session):
        run = lambda sql: con_or_session.execute(text(sql)).all()  # noqa: E731
    else:
        run = lambda sql: con_or_session.execute(sql).fetchall()  # noqa: E731
    names = [
        r[0] for r in run(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        )
    ]
    # 表名来自 sqlite_master、不是用户输入，但还是引号裹上：一个叫 order 的表能把
    # 这条语句整段搞坏，而那时报出来的是「备份损坏」，指不到真正的原因
    return {n: run(f'select count(*) from "{n}"')[0][0] for n in sorted(names)}

def _verify(path: Path, low: dict[str, int], high: dict[str, int]) -> dict[str, int]:
    """把刚写出来的文件当成陌生人：独立连接、只读打开、从头验一遍。

    这一步是「备份可验证」的全部含义 —— 不验的话，`VACUUM INTO` 返回成功
    只说明 SQLite 写完了，不说明写出来的东西能打开、有表、有账。
    """
    try:
        # **用 as_uri() 不要手拼**：`file:{path}?mode=ro` 没做百分号转义，
        # 路径里带 `#`（fragment）或 `?`（query）时，打开的根本不是刚写出来的那个文件 ——
        # 于是每一份备份都被判成损坏、当场删掉，一份都留不下。
        # resolve() 那一下是必须的：as_uri() 对相对路径直接抛 ValueError
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, ValueError) as e:
        raise BackupError("backup_corrupt", f"备份文件打不开：{e}", path=str(path)) from e
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()
        if not ok or ok[0] != "ok":
            raise BackupError("backup_corrupt", f"integrity_check 不过：{ok}", path=str(path))
        broken = con.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise BackupError(
                "backup_corrupt", f"外键对不上：{broken[:3]}", path=str(path), rows=len(broken),
            )
        got = _tables(con)
    except sqlite3.DatabaseError as e:
        raise BackupError("backup_corrupt", f"备份文件读不动：{e}", path=str(path)) from e
    finally:
        con.close()

    missing = sorted(set(low) - set(got))
    if missing:
        # 这正是「只拷 nagaya.db」那条老路的下场：文件在、能打开、零张表
        raise BackupError(
            "backup_corrupt", f"备份里少了 {len(missing)} 张表：{missing[:5]}",
            path=str(path), missing=missing,
        )
    for table, n in got.items():
        # 上下界：备份是某一瞬间的快照，这中间别人可能正好记了一笔。
        # 卡死等号会时不时误报一次「备份损坏」—— 假警报比不报更伤，
        # 因为下一次真坏的时候没人会当回事
        lo, hi = min(low.get(table, n), high.get(table, n)), max(low.get(table, n), high.get(table, n))
        if not lo <= n <= hi:
            raise BackupError(
                "backup_corrupt", f"{table} 条数对不上：备份 {n}，源库 {lo}〜{hi}",
                path=str(path), table=table, got=n, low=lo, high=hi,
            )
    return got

def verify_file(path: Path) -> dict[str, int]:
    """单独验一个现成的备份文件（恢复之前先跑这个）。不比对源库，只问它自己完不完整。"""
    if not path.exists():
        raise BackupError("backup_corrupt", f"文件不在：{path}", path=str(path))
    counts = _verify(path, {}, {})
    if not counts:
        raise BackupError("backup_corrupt", f"零张表：{path}", path=str(path))
    return counts


#: 账本自检的三条恒等式。每一条都是 app 写进去时就成立的整数等式，平时永远查不出东西；
#: 查出来了就只可能是有人绕过 app 改过库、迁移出了错、或者哪天的回归 —— 而那一刻
#: 这个项目最强的那条自检（Σ余额≡0）在界面上只表现成一个查不出原因的 500。
#:   B1 每一笔（含软删的：撤销删除会把它带回来）Σ分摊 ≡ 金额
#:   B2 没删的账：Σ垫付 − Σ应担 ≡ 0
#:   B3 转账的分摊只有一行，全额记在转入人头上
#: tools.checkup 跑的也是这三条（它那边编号是 B1 / B2 / B4，B3 留给了「正负和类型」）
SHARES_SQL = (
    "select e.id from entry e left join entry_share s on s.entry_id = e.id "
    "group by e.id having coalesce(sum(s.amount_jpy), 0) != e.amount_jpy"
)
BALANCE_SQL = (
    "select coalesce(sum(d), 0) from ("
    " select amount_jpy d from entry where deleted_at is null"
    " union all select -s.amount_jpy from entry_share s join entry e on e.id = s.entry_id"
    " where e.deleted_at is null)"
)
SETTLEMENT_SQL = (
    "select e.id from entry e left join entry_share s on s.entry_id = e.id "
    "where e.kind = 'settlement' group by e.id "
    "having count(s.id) != 1 or max(s.member_id) is not e.to_member_id "
    "or max(s.amount_jpy) != e.amount_jpy"
)


def ledger_problems(con: sqlite3.Connection) -> dict[str, Any] | None:
    """在一份**静止的**库上跑 B1–B3（备份文件、体检的快照）。没毛病返回 None。

    只读、只报不修。放在活库上跑的话三条 SELECT 不在同一个快照上，别人正好记了一笔
    就会误报一次 —— 所以只在备份文件上跑（它就是那一瞬间的一致快照）。
    """
    b1 = [r[0] for r in con.execute(SHARES_SQL)]
    total = con.execute(BALANCE_SQL).fetchone()[0]
    b3 = [r[0] for r in con.execute(SETTLEMENT_SQL)]
    if not b1 and not total and not b3:
        return None
    return {"entries": sorted(set(b1) | set(b3)), "total": int(total)}


def _ledger_check(path: Path) -> dict[str, Any] | None:
    """打开一份备份文件跑 ledger_problems。打不开、读不动交给 _verify 去报，这里不重复判"""
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, ValueError):
        return None
    try:
        return ledger_problems(con)
    except sqlite3.Error:
        return None
    finally:
        con.close()

# ---------------------------------------------------------------- 落盘

def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def _fsync_dir(directory: Path) -> None:
    """改名之后把目录项也刷下去，否则断电后可能「文件在、名字不在」。"""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:
        pass                      # 有的网络挂载不支持对目录 fsync，不为这个把备份判死
    finally:
        os.close(fd)

def _prune(directory: Path, keep: int, protect: Path) -> list[str]:
    """留最近 keep 份。

    按**文件名**排序而不是 mtime：名字里是零填充的时间戳，而 mtime 会被
    拷贝/rsync/同步盘改掉 —— 按 mtime 排的话，一次「把备份拷到移动硬盘再拷回来」
    就能让最老的那份排到最前面，然后被当成新的留下、把真正的新备份删掉。
    """
    if keep <= 0:
        return []
    files = sorted(p for p in directory.iterdir() if _is_ours(p.name))
    removed: list[str] = []
    for p in files[:-keep]:
        if p == protect:
            continue              # 刚做好那份永远不删
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:
            pass                  # 删不掉不算备份失败：那一份已经落地了
    return removed

def run(session: Session) -> dict[str, Any]:
    """做一份备份。成功返回文件信息，失败抛 BackupError（一个字节都不会留下）。"""
    directory = _prepare_dir(_raw_path(session))
    _check_space(source_path(session), directory)
    _sweep_parts(directory)

    before = _tables(session)
    if before.get("member", 0) == 0:
        # 空库不备份，**而且不 prune**。这一条挡的是最坏的那个剧本：
        # 账本被误删/被换成空库之后备份照跑，30 天里把每一份好备份都轮转掉。
        # 全新安装也走这一支 —— 那时本来也没有任何东西值得存
        raise BackupError(
            "backup_empty_source",
            "源库里一个成员都没有，不像是能备份的东西；旧备份原样留着",
            tables=len(before),
        )

    # 名字必须**单调往后**，不能只看「这个名字空着没有」。
    # 空着不等于没用过：上一轮轮转刚把它删掉，名字就又空出来了 ——
    # 实测连备五次，第五次拿到的是第一次那个名字，于是**最新的备份顶着最老的名字**。
    # 而 _prune / _newest / status 全靠名字排序，下一次轮转就会把新的当老的删掉。
    stamp = dt.datetime.now(JST)
    newest = _newest(directory)
    if newest is not None:
        last = dt.datetime.strptime(newest.name, NAME_FMT).replace(tzinfo=JST)
        if last >= stamp:
            stamp = last + dt.timedelta(seconds=1)
    final = directory / stamp.strftime(NAME_FMT)
    while final.exists():
        stamp += dt.timedelta(seconds=1)
        final = directory / stamp.strftime(NAME_FMT)
    # **.part 的名字必须每次都不一样**，不能从 final 推出来。
    # 推的话同一秒里的两次备份会算出同一个 .part：两边互相 unlink、
    # 互相往同一个文件里 VACUUM —— 实测 6 个并发**一份都产不出来**
    # （disk I/O error / table member already exists），而不是「一个成一个败」。
    # 定时任务和手点「立即备份」正好会撞上这一秒。
    part = final.with_name(f"{final.name}.{os.getpid()}-{threading.get_ident()}{PART_SUFFIX}")

    try:
        part.unlink(missing_ok=True)      # VACUUM INTO 拒绝写一个已存在的文件（名字带 pid+线程，撞不上别人的）
        session.execute(text("VACUUM INTO :p"), {"p": str(part)})
        os.chmod(part, 0o600)             # 密码哈希和头像都在里面
        _fsync_file(part)
        counts = _verify(part, before, _tables(session))
        # 文件本身验过了，再验里面的账平不平（B1–B3，5 年规模约 5ms）。.part 是一瞬间的
        # 一致快照，别人这时候记账也不会让它误报
        broken = _ledger_check(part)
        # 到这一刻它才配叫备份。同一秒里两个线程各自验过、都想叫这个名字时，
        # 后到的覆盖先到的 —— 两份都是那一瞬间的完整快照，覆盖不丢任何东西
        os.replace(part, final)
        _fsync_dir(directory)
    except BackupError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:                # sqlite3.OperationalError: disk I/O error 等
        part.unlink(missing_ok=True)
        # why 带上原始原因（磁盘 I/O 错、盘满…）。它是**诊断数据不是界面文案** ——
        # 备份失败这一条如果不说原因，用户在面板上只看得到「没做成」，无从下手
        raise BackupError("backup_failed", f"backup failed: {e}", path=str(part), why=str(e)) from e

    if broken:
        # 账本本身不平：**这份照留**（它忠实记下了坏掉的账本，排查时正要拿它对照），
        # 但**这一轮不轮转** —— 和空库那一支同一个道理：坏了之后备份照跑，
        # keep 天之内就把坏之前的好备份全转掉了。只报不修，点名是哪几笔
        raise BackupError(
            "ledger_invariant_broken",
            f"账本自检没通过：账目 {broken['entries'][:20]} 的分摊合计对不上，余额合计 {broken['total']}",
            name=final.name, entries=broken["entries"][:50], total=broken["total"],
        )

    keep = int(settings_svc.get(session, "backup_keep") or 0)
    pruned = _prune(directory, keep, protect=final)
    return {
        "path": str(final),
        "name": final.name,
        "bytes": final.stat().st_size,
        "at": stamp.replace(tzinfo=None).isoformat(timespec="seconds"),
        "rows": sum(counts.values()),
        "pruned": pruned,
    }

# ---------------------------------------------------------------- 状态

def _newest(directory: Path) -> Path | None:
    files = sorted(p for p in directory.iterdir() if _is_ours(p.name))
    return files[-1] if files else None

def _safe_path(raw: str) -> str:
    try:
        return str(resolve_backup_path(raw))
    except (OSError, ValueError):
        return raw


def _custom_path(raw: str) -> bool:
    """备份目录是不是人改过的（不是默认那个 ./backups）。

    默认目录和账本同盘是明摆着的、说明里写着的取舍；**自己指了一个目录、结果还和账本同盘**，
    多半是那块外接盘 / NAS 没挂上，备份悄悄写进了本机（Linux 挂载点没挂上时就是根盘上的
    一个空目录，_prepare_dir 那道「只建最后一级」挡不住）。界面拿它和 same_disk 一起判
    """
    default = SETTINGS_SPEC["backup_path"]["default"]
    try:
        return resolve_backup_path(raw) != resolve_backup_path(default)
    except (OSError, ValueError):
        return True


#: data/ 里会自己攒下来的两种整本账副本：开机升级前拍的快照、恢复时挪走的旧账本
_STALE_PATTERNS = ("before-migrate-*.db", "replaced-*")


def _stale_copies(src: Path | None) -> dict[str, Any] | None:
    """账本旁边留着几份旧副本、一共多大、最早是哪天。**只数不删**。

    它们故意不自动清（里面可能正是唯一还留着的数据，比如恢复之前多记的那几笔），
    可也从来没人提起，人就不知道哪些已经可以删了。只 stat、不打开库：
    这是设置页每次打开都要调的接口。拿不到源库位置、目录读不了，就不说（None），
    不让整个备份状态跟着报错
    """
    if src is None:
        return None
    try:
        found = [p for pattern in _STALE_PATTERNS for p in src.parent.glob(pattern)]
        size = 0
        oldest: float | None = None
        for p in found:
            # replaced-* 是目录（里面是 nagaya.db 和 -wal / -shm），大小要把里面的加起来
            files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
            size += sum(f.stat().st_size for f in files)
            mtime = p.stat().st_mtime
            oldest = mtime if oldest is None else min(oldest, mtime)
    except OSError:
        return None
    return {
        "count": len(found),
        "bytes": size,
        "oldest": (
            dt.datetime.fromtimestamp(oldest, JST).replace(tzinfo=None).isoformat(timespec="seconds")
            if oldest is not None else None
        ),
    }


def status(session: Session) -> dict[str, Any]:
    """现在这一刻备份能不能做、上一份是什么时候 —— 全部现场探，不读存下来的结论。"""
    return _probe(**_status_inputs(session))


def _status_inputs(session: Session) -> dict[str, Any]:
    """status 要从库里拿的那几样。**只读设置、不碰盘**（路径也不解析：resolve() 要 stat，
    挂死的网络盘上一样卡）—— 拿完连接就能还回池子，探目录那半段（_probe）一个库都不碰"""
    return {
        "raw": _raw_path(session),
        "every": int(settings_svc.get(session, "backup_every_hours") or 0),
        "keep": int(settings_svc.get(session, "backup_keep") or 0),
        "src": source_path(session),
    }


def _probe(raw: str, every: int, keep: int, src: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": _safe_path(raw),
        "error": None, "last_at": None, "last_name": None, "last_bytes": None,
        "count": 0, "keep": keep,
        "last_ok": None, "age_hours": None,
        "every_hours": every, "stale": True, "same_disk": None,
        "custom_path": _custom_path(raw),
        # 和备份目录能不能用无关：目录坏了也照样要说
        "stale_copies": _stale_copies(src),
    }
    try:
        directory = _prepare_dir(raw)
        _check_space(src, directory)
    except BackupError as e:
        out["error"] = e.code
        return out

    files = sorted(p for p in directory.iterdir() if _is_ours(p.name))
    out["count"] = len(files)
    newest = files[-1] if files else None
    if newest is not None:
        # **真打开看一眼**，不是数一数文件名。位腐、同步盘传了一半、
        # iCloud 把内容抽走只留占位 —— 目录里名字照样对得上，而这一屏
        # 正是那个「承诺了一件自己没检查过的事」的地方。
        # 只验最新这一份：它就是要恢复的那一份，约 60ms（5 年规模、每月约 150 笔）。
        # 全验 30 份要半秒，而这是个每开一次设置页就调的 GET
        try:
            verify_file(newest)
            out["last_ok"] = True
            # 文件是好的，里面的账平不平另说。坏账本那一份 run() 故意留着、不轮转，
            # 这里每次现场再验一遍：账修好、下一份备份做出来，这句自己就消失了
            if _ledger_check(newest):
                out["error"] = "ledger_invariant_broken"
        except BackupError:
            out["last_ok"] = False
            # **和 run() 那条路不是一回事，别共用一个码。** 这里验的是目录里
            # 现成的那一份，一个字节都没动过；run() 里验不过的是刚导出来的临时文件，
            # 那一份当场就删了。共用的话，界面上会对着一份好端端躺在那儿的文件说
            # 「已经删掉了」—— 而它恰恰是唯一能恢复的那一份
            out["error"] = "backup_last_corrupt"
        at = dt.datetime.strptime(newest.name, NAME_FMT)
        out["last_at"] = at.isoformat(timespec="seconds")
        out["last_name"] = newest.name
        out["last_bytes"] = newest.stat().st_size

        # 「多久以前」**不能只信文件名**。名字一旦漂到未来（系统时钟被调过、
        # 从别处拷进来一份、或者单调命名连着往后推），age 恒为负 →
        # run_if_due 永远觉得「刚备过」→ 自动备份从此停摆，而面板上是一行
        # 没有任何警告色的「上次备份 …」。
        # 取 min(名字时间, mtime)：mtime 会被 rsync / 同步盘改成 now，
        # 纯用它会让老备份看起来很新（漏备）；取 min 只可能让备份显得更老，
        # 方向上永远安全 —— 顶多多备一份。
        # mtime 按**日本时间**解读，和文件名、now 同一个口径。不带时区的 fromtimestamp
        # 用的是服务器本地时区 —— 部署在 UTC 的容器里，每份备份都显得比实际老 9 小时
        mtime = dt.datetime.fromtimestamp(newest.stat().st_mtime, JST).replace(tzinfo=None)
        age = (dt.datetime.now(JST).replace(tzinfo=None) - min(at, mtime)).total_seconds() / 3600
        out["age_hours"] = age
        out["stale"] = age > (every or 24) * 2
        if at - dt.datetime.now(JST).replace(tzinfo=None) > dt.timedelta(days=1):
            # 名字超前一天以上：说出来。不说的话备份已经停了而屏幕上一切正常
            out["error"] = out["error"] or "backup_clock_skew"

    if src is not None and src.exists():
        # 同一块盘上的备份挡不住「盘坏了」。不拦，只说出来 —— 默认就是同一块盘
        out["same_disk"] = os.stat(directory).st_dev == os.stat(src).st_dev
    return out

def run_if_due(session: Session) -> dict[str, Any] | None:
    """离上一份够久了才做。进程里那个每小时醒一次的任务调它（main._daily_backup）；
    设置页的「立即备份」不走这里，直接 run()。"""
    every = int(settings_svc.get(session, "backup_every_hours") or 0)
    if every <= 0:
        return None
    st = status(session)
    # 用 status 算好的 age_hours，别再各算各的 —— 两处口径一分叉，
    # 「面板说没问题、备份其实停了」这种事就又回来了。
    # 时钟偏差只是一句提醒，不是「备份坏了」：age_hours 已经按 min(名字, mtime)
    # 取了安全的那一头，照它判到没到期就行。原来当成出错，每小时备一份，
    # 30 份保留只盖得住 30 个小时
    # 账本不平也照原来的节奏备：文件本身是好的，只是里面的账有毛病。当成出错的话
    # 每小时都会多一份，而那段时间又不轮转 —— 一天 24 份整本账堆在盘上
    healthy = st["error"] in (None, "backup_clock_skew", "ledger_invariant_broken")
    # age 是负的（最新那份的名字和 mtime 都在未来）也算到期：否则自动备份一直停着，
    # 要等真实时间追上那个未来时刻。补做一份之后新文件的时间是对的，节奏自己恢复
    if healthy and st["age_hours"] is not None and 0 <= st["age_hours"] < every:
        return None
    return run(session)


#: 同一时刻只许一个 alert 在探目录。拿不到就不排队，直接回上一次探出来的（见 alert）
_alert_lock = threading.Lock()
#: 上一次探出来的红点。只在进程内存里，**只给「正有一个在探」时顶一下**，不当结论用
_alert_last: str | None = None


def alert(session: Session) -> str | None:
    """平时页面上要不要亮一个红点：给一个码，没事就是 None。和 status() 一样现场判，不存结论。

    status 里报出来的错都算（目录用不了、盘满、最新那份打不开、账本不平、时间在未来）；
    此外自动备份开着、却已经超过两个间隔没出新的 —— backup_stale。
    **故意不算的**：同盘（默认就是同盘，算了红点就常亮，真出事那天没人当回事）；
    一份都还没有、也没报错（刚改完目录、每小时那次检查还没轮到）；
    自动备份是自己关掉的（every_hours=0）时的「太久没备」。

    **读完设置就把 session 关掉，再去探目录。** 这是每次开 App、切回前台都要调的接口，
    而备份目标最常见的坏法是「卡住」而不是「报错」：NAS 掉线、网络盘 hard mount、
    同步盘的占位文件正在下载。原来探的整段时间都揣着一条库连接，池子一共 5 条 ——
    三个人各开一次 App、再切一两次前台，记账、看账单就全部等满 30 秒然后 500。
    再加 single-flight：已经有一个在探，后来的不再开新线程去排队，回上一次的结果。
    备份目标卡住时最多挂住一个线程，一条库连接都不占。
    """
    global _alert_last
    inputs = _status_inputs(session)
    session.close()
    if not _alert_lock.acquire(blocking=False):
        return _alert_last
    try:
        st = _probe(**inputs)
        code = st["error"]
        if code is None and st["every_hours"] > 0 and st["last_at"] is not None and st["stale"]:
            code = "backup_stale"
        _alert_last = code
        return code
    finally:
        _alert_lock.release()
