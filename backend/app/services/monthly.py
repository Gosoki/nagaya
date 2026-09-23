"""当前草稿账单上的固定费面板，和「照上期」（按上一期的金额、垫付人、分摊把固定费先记上）。

依赖方向是 monthly → bill / ledger，bill 不许反过来 import 这里（会成环）。
这里的 carry 指「照上期记上」，和 bill 里的 opening / carried（上期结转）不是一回事 ——
两个词根撞了，是历史原因，见 docs/AUDIT-2026-09.md 附表。
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Category, Entry, EntryKind, Statement, today_jst
from app.services import ledger
from app.services.bill import entries_of, last_monthly_cut, unbilled


def monthly_rows(session: Session, statement: Statement | None = None) -> dict[str, Any]:
    """每月一次的固定项在某张账单里的状态。statement 传 None ＝ 当前草稿。

    **没录的就是没录，amount 给 None**，界面上是个空框，出账时按 0 算。
    这里不给「上次记了多少」当参考：要每期照抄的项，去分类上开 `same_as_last`，
    再由人在那一行上点「照上期」（carry_same_as_last）记成**真值**（黑字，看得见）。
    """
    # 翻历史账单时**连归档的也要列**：那张单子上真有这笔钱，总额里也算着它。
    # 只按「现在还没归档」过滤的话，归档一个分类会让它名下的旧账凭空消失，
    # 而账单合计不变 —— 一眼看去就是「这几项加不出总数」
    stmt = select(Category).where(Category.monthly == True)  # noqa: E712
    categories = list(session.exec(stmt.order_by(Category.display_order, Category.id)))
    # 草稿里的账这一趟要用三次（占位、合计、「和上期一样」），只查一次
    draft = unbilled(session) if statement is None else None
    if draft is not None:
        # 草稿里归档的项默认不占位（归档＝以后不用填了），但**它名下本期已经录了钱的
        # 除外**：那笔钱还在账单的合计和每人应担里，面板上却一行都看不见，
        # 于是同一张草稿出现两个对不上的合计，而且那笔钱既改不了也删不掉
        with_money = {e.category_id for e in draft if e.category_id is not None}
        categories = [c for c in categories if not c.archived or c.id in with_money]
    # 同一个分类在这张草稿里可能有不止一笔（两个人同时填、或者填完重试了一次）。
    # 面板一行只显示得下一笔，**但账单是全都算的** —— 不把重复说出来的话，
    # 用户看到「家賃 170,000」，完全不知道还有一笔 120,000 也在总额里。
    mine: dict[int, Entry] = {}
    dup: dict[int, int] = {}
    monthly_ids = {c.id for c in categories}
    total = 0
    for e in (draft if draft is not None else entries_of(session, statement.id)):  # type: ignore[union-attr]
        if e.kind == EntryKind.settlement or e.category_id is None:
            continue
        mine[e.category_id] = e
        dup[e.category_id] = dup.get(e.category_id, 0) + 1
        if e.category_id in monthly_ids:
            total += e.amount_jpy
    # 草稿里还没录的行：垫付人和分摊从**上期那一笔**起步，和「和上期一样」同一个口径
    # （SPEC F1：分摊规则默认＝该分类上次用的规则）。原来是分类默认规则 ——
    # 而界面上改房租怎么分只能逐笔改，于是每期手填一次房租，分摊就打回均分一次。
    # 人变了（有人搬走/搬进来）就不抄：退回分类默认，由人自己重新定
    last = _last_billed(session, [c.id for c in categories]) if statement is None else {}
    active = {m.id for m in ledger.active_members(session, today_jst())} if statement is None else set()
    # 「和上期一样」这一步现在要人点（面板上那个按钮、出账时那个勾），
    # 所以得先告诉界面：点下去会记哪几项、多少钱，哪几项记不了
    ready: dict[int, int] = {}
    blocked: dict[int, str] = {}
    if draft is not None:
        todo, failed = _carry_plan(session, draft)
        ready = {c.id: prev.amount_jpy for c, prev, _, _ in todo}
        blocked = {f["category_id"]: f["reason"] for f in failed}
    rows = []
    for c in categories:
        entry = mine.get(c.id)
        prev = last.get(c.id)
        seed = c.default_rule_json
        prev_payer = None
        if prev is not None:
            if prev.split_rule_json and _stale_for_today(prev.split_rule_json, None, active) is None:
                seed = _prune_rule(prev.split_rule_json, active)
            prev_payer = prev.payer_id if prev.payer_id in active else None
        # 翻一张已经出过的账单时只列它真有的那几项。空行会诱人往里填，
        # 而填出来的是**新账目**，落进当前草稿，根本不会进这张单子。
        if statement is not None and entry is None:
            continue
        rows.append(
            {
                "category_id": c.id,
                "name": c.name,
                "icon": c.icon,
                "color": c.color,
                #: 已经删掉（归档）但本期还挂着钱的那种。界面要明说，
                #: 否则「点了删除这一行还在」看上去就是没删掉
                "archived": c.archived,
                "default_rule_json": c.default_rule_json,
                #: 这一项默认谁垫。面板据此预填「谁付的」，不再是「谁填的算谁」
                "default_payer_id": c.default_payer_id,
                #: 每期金额都一样 —— 打开的话出账前会自动按上期金额记上
                "same_as_last": c.same_as_last,
                "entry_id": entry.id if entry else None,
                "amount": entry.amount_jpy if entry else None,
                "version": entry.version if entry else None,
                "rule": entry.split_rule_json if entry else seed,
                #: 上期那一笔是谁垫的（还在籍才给）。面板上没录的行按它预填「谁付的」
                "last_payer_id": prev_payer,
                "date": entry.date.isoformat() if entry else None,
                #: 本期这个分类一共有几笔。>1 说明面板没显示全，界面上必须提示
                "entry_count": dup.get(c.id, 0),
                #: 按「和上期一样」点一下会记多少（只有草稿、开了开关、本期还没处理过的才有）
                "carry_amount": ready.get(c.id),
                #: 开了开关却记不了的原因（payer_left / rule_stale），要人自己填
                "carry_blocked": blocked.get(c.id),
            }
        )

    return {
        "default_date": today_jst().isoformat(),
        "rows": rows,
        # 面板一行只显示得下一笔，所以合计**不能由行加出来** —— 同一分类有两笔时
        # 会少算一笔，而账单上的「本期固定费」是全算的，两个数当场对不上
        "total": total,
    }


#: carry 这件事整个进程里一次只许跑一个。
#: 「读一遍本期已经有哪几项 → 把缺的记上」中间隔着好几十毫秒。原来触发它的是
#: 账单页挂载 —— 群里一句「出账了」，三个人同时点开，两个请求都在对方 commit
#: 之前读到「本期还没记房租」，于是各记一笔，当期房租翻倍。现在改成人点按钮了，
#: 可两个人同时点、或者一个人连点照样会撞，锁留着。
#: 面板一行只显示得下一笔，屏幕上的金额还是对的、合计却是两倍。
#: 服务是单端口单进程（见 main.py 的 _daily_backup），一把进程内的锁就够；
#: 不加唯一索引 —— 同一分类手工记两笔是合法的（entry_count 就是为它准备的）
_carry_lock = threading.Lock()


def carry_same_as_last(
    session: Session, *, actor_id: int | None, only: set[int] | None = None
) -> dict[str, Any]:
    """把「和上期一样」的固定费按上期金额记进当前草稿。

    **只动明确开了这个开关的项**。默认全是关的：「上期的金额不许预填、连灰色参考都不给」
    这条规矩就是为了防「某个月忘了改，带着上月的电费把账单发出去」——
    电费燃气水费恰恰每期都不一样，给它们开这个等于把那条规矩废掉。

    已经录过的一律不碰；从来没出过账的（没有上期金额可抄）跳过。
    **本期手动删掉的也不碰** —— 否则每点一次就复活一次，用户删不掉。
    `only` 给了就只记这几个分类（面板上列出来的那几项）。

    返回 `{"created": [...], "failed": [...]}`：记了哪几笔要说出来（自动记的钱
    必须看得见），**搬不过来的也要说出来**（「自动记账已经停了」同样必须看得见）。
    每一项各自兜错：原来是整个循环一把梭，中间任何一笔抛异常，
    前面那几笔**已经 commit 进草稿了**（create_entry 自己 commit），
    而返回值随异常一起丢掉、接口返 400、前端一个空 catch 吞掉 ——
    屏幕上那几行还是空框，用户照着空框再填一遍，同一分类当期就有了两笔。
    """
    with _carry_lock:
        return _carry(session, actor_id=actor_id, only=only)


def _carry_plan(
    session: Session, draft: list[Entry] | None = None
) -> tuple[list[tuple[Category, Entry, int | None, dict[str, Any] | None]], list[dict[str, Any]]]:
    """算一遍「和上期一样」**现在点下去**会记哪几项。不写库。

    返回 (要记的, 记不了的)。要记的每项是 (分类, 上期那一笔, 垫付人, 分摊规则)。
    面板预览和真正去记走的是同一个函数 —— 按钮上写的和点下去记的不会是两份口径。
    """
    categories = list(
        session.exec(
            select(Category).where(
                Category.monthly == True,  # noqa: E712
                Category.archived == False,  # noqa: E712
                Category.same_as_last == True,  # noqa: E712
            )
        )
    )
    if not categories:
        return [], []

    # 「本期已经处理过」＝ 录了 **或者** 手动删掉了。
    # 只看 unbilled() 的话删掉的那笔不在里面，下次一点又给它记回来。
    #
    # 「本期」要按**上次出账那一刻**卡：草稿里删掉的账目 statement_id 恒为 NULL，
    # 光看这一条的话，半年前删过一次的分类会从此**永远**不再自动记 ——
    # 那是另一个方向的静默失效。两条一起才圈得出「这一期手动删掉的」。
    # draft：调用方手里已经有草稿就递进来（monthly_rows），别再查一遍
    handled = {e.category_id for e in (unbilled(session) if draft is None else draft) if e.category_id is not None}
    # 「上次出账」得是**结过固定费的那一次**。中途出一张「不含固定费」的小账
    # （include_monthly=false）不算一期的边界：拿它当下界的话，它之前那段时间里
    # 手动删掉的房租就不算「本期删的」了，下次一点就被记回来。
    # 判据见 last_monthly_cut
    since = last_monthly_cut(session)
    dropped = select(Entry).where(
        Entry.deleted_at.is_not(None),
        Entry.category_id.is_not(None),
        # 而且必须是**草稿里**删的。已出账的账目软删之后 statement_id 还留着，
        # 少了这一条的话，「事后回去修一笔去年的房租」会被当成「本期删掉了房租」，
        # 整个月的房租从此不自动记，面板上就是个空框，出账时按 0 结
        Entry.statement_id.is_(None),
    )
    if since is not None:
        dropped = dropped.where(Entry.deleted_at > since.cut_at)
    handled |= {e.category_id for e in session.exec(dropped)}
    last = _last_billed(session, [c.id for c in categories])
    active = {m.id for m in ledger.active_members(session, today_jst())}

    todo: list[tuple[Category, Entry, int | None, dict[str, Any] | None]] = []
    failed: list[dict[str, Any]] = []
    for c in categories:
        prev = last.get(c.id)
        if c.id in handled or prev is None or not prev.amount_jpy:
            continue
        # **「和上期一样」就是字面意思：金额、分摊、垫付人都照上期那一笔。**
        #
        # 原来只抄金额，分摊用分类默认、垫付人回退到「全局默认 → 当前这个人」：
        #   * 分摊：界面上改房租怎么分只有一条路 —— 在固定费面板里展开那一行改，
        #     改的是那一笔、不是分类。于是「Go 多担 5,000」下一期被悄悄打回均分，
        #     以后每期都是；
        #   * 垫付人：分类和全局都没设时，谁触发了 carry，房租就记成谁垫的。
        # 分类上明写了默认垫付人的仍然优先 —— 那是面板上「谁付的」显式定下的常驻值
        # （改它会同时写分类和那一笔）。SPEC F1：分摊规则默认＝该分类上次用的规则
        payer = c.default_payer_id or prev.payer_id
        rule = prev.split_rule_json or c.default_rule_json
        stale = _stale_for_today(rule, payer, active)
        if stale is not None:
            # 自动记的钱必须看得见 —— 这一条也包括「这次没敢替你记」
            failed.append({"category_id": c.id, "name": c.name, "reason": stale})
            continue
        todo.append((c, prev, payer, _prune_rule(rule, active)))
    return todo, failed


def _carry(session: Session, *, actor_id: int | None, only: set[int] | None) -> dict[str, Any]:
    todo, failed = _carry_plan(session)
    if only is not None:
        # 按钮上列了哪几项就只记哪几项：点的那一刻有一行正在手填，
        # 它不在按钮上写着，就不该被记 —— 否则手填的那笔一存，同一项就是两笔
        todo = [t for t in todo if t[0].id in only]
        failed = [f for f in failed if f["category_id"] in only]
    made: list[dict[str, Any]] = []
    for c, prev, payer, rule in todo:
        try:
            entry = ledger.create_entry(
                session,
                actor_id=actor_id,
                kind=EntryKind.expense,
                on=today_jst(),
                amount=prev.amount_jpy,
                payer_id=payer,
                category_id=c.id,
                rule=rule,
            )
        except (ValueError, KeyError) as e:   # LedgerError / RuleError / SplitError 都是 ValueError
            session.rollback()
            failed.append({"category_id": c.id, "name": c.name, "reason": str(e)})
            continue
        made.append({"category_id": c.id, "name": c.name, "amount": entry.amount_jpy})
    return {"created": made, "failed": failed}


def _stale_for_today(rule: dict[str, Any] | None, payer: int | None, active: set[int]) -> str | None:
    """这一项还能不能照上期自动记？返回拦下来的原因，None ＝ 可以记。

    「和上期一样」抄的是**上一期**的安排，而人是会搬走搬进来的。两件事一旦发生，
    照抄就从「省事」变成「静悄悄记错钱」：

      * **垫付人搬走了** —— 记出来是「已经不住这儿的人又垫了一次房租」，
        账单反过来叫留下的两个人给他转账；
      * **有人新搬进来、而这条规则点名写了谁分多少** —— expand 的口径是
        「规则里没提到的人按 0 补齐」（rules.py），新室友于是白住一个月，
        黑字入账、一句提示都没有。而 _prune_rule 恰好把本来会抛出来的
        unknown_member 消掉了，所以连报错都不会有。

    两种都该**响一声**让人自己重新定，而不是替他记一笔错的 ——
    这跟这个函数「搬不过来的也要说出来」的既有约定是同一条。
    """
    if payer is not None and payer not in active:
        return "payer_left"
    rule = rule or {}
    named = rule.get("exact") if rule.get("mode", "ratio") == "exact" else rule.get("weights")
    if isinstance(named, dict) and named:
        listed: set[int] = set()
        for key in named:
            try:
                listed.add(int(key))
            except (TypeError, ValueError):
                continue
        if active - listed:
            return "rule_stale"
    return None


def _prune_rule(rule: dict[str, Any] | None, active: set[int]) -> dict[str, Any] | None:
    """把分类默认规则里**已经不在籍的人**剔掉。

    分类的默认分摊是当年按那时候几个人写死的（房租那条就点名了 adjustments）。
    有人搬走之后，expand() 会拿「今天在籍的人」当参与人，发现规则里多出一个
    不认识的 id，直接抛 unknown_member —— 于是那一行固定费永远存不上，
    「和上期一样」也从此一声不吭地停了。

    剔掉而不是报错：这是一条**为上一期写的**规则，拿它硬套今天的人本来就不对。
    注意剩下的人分摊会变（adjustments 是「先抠掉再按比例分」），所以调整额一并去掉
    的那份钱会回到大家头上 —— 这是唯一说得通的默认，规则本身该由用户重新定。

    **它只管「人少了」。**「人多了」是另一回事，在 _stale_for_today 那儿拦下来 ——
    往这条规则里补一个新人，补多少只有住的人知道。
    """
    if not rule:
        return rule
    out = dict(rule)
    for field in ("weights", "adjustments", "exact"):
        if isinstance(out.get(field), dict):
            out[field] = {k: v for k, v in out[field].items() if int(k) in active}
            if not out[field]:
                out.pop(field)
    # weights 全被剔光时退回「所有在籍成员同权」，别留一条空规则
    if out.get("mode", "ratio") == "ratio" and "weights" not in out:
        out.setdefault("equal_weight", 1)
    return out


def _last_billed(session: Session, category_ids: list[int]) -> dict[int, Entry]:
    """每个分类**上一次出过账的**那一笔。只给「和上期一样」那几项抄。

    按分类回溯而不是只看上一张单子：水费两个月一收，上一张本来就没有它。
    """
    if not category_ids:
        return {}
    # 每个分类只要最新那一笔：窗口函数在 SQL 里挑，一个分类回来一行。
    # 原来是把这几个分类出过账的每一笔全取出来（一年多六十笔、永远只增）再挑第一笔
    rank = (
        func.row_number()
        .over(partition_by=Entry.category_id, order_by=(Entry.date.desc(), Entry.id.desc()))
        .label("rank")
    )
    latest = (
        select(Entry.id, rank)
        .where(
            Entry.category_id.in_(category_ids),
            Entry.deleted_at.is_(None),
            Entry.statement_id.is_not(None),
            # 只抄支出。收入的金额是**负数**，抄过来 carry 以 expense 建账，
            # 当场撞 bad_sign「支出金额要填正数」—— 而那一项的「和上期一样」
            # 从此每次都失败，用户只看到它一直空着
            Entry.kind == EntryKind.expense,
        )
        .subquery()
    )
    rows = session.exec(select(Entry).join(latest, latest.c.id == Entry.id).where(latest.c.rank == 1))
    return {e.category_id: e for e in rows}
