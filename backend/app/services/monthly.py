"""当前草稿账单上的固定费面板，和「照上期」（按上一期的金额、垫付人、分摊把固定费先记上）。

依赖方向是 monthly → bill / ledger，bill 不许反过来 import 这里（会成环）。
这里的 carry 指「照上期记上」，和 bill 里的 opening / carried（上期结转）不是一回事 ——
两个词根撞了，是历史原因，见 docs/AUDIT-2026-09.md 附表。
"""

from __future__ import annotations

import statistics
import unicodedata
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.rules import _prune_rule, expand
from app.core.split import split
from app.models import Category, Entry, EntryKind, Statement, today_jst
from app.services import ledger
from app.services import settings as settings_svc
from app.services.bill import (
    BillError,
    entries_of,
    last_monthly_cut,
    latest_statement_id,
    monthly_cut_ids,
    period_lock,
    unbilled,
)


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
    # 人变了（有人搬走/搬进来）就不抄：退回分类默认，由人自己重新定。
    # 上期那张单子上这一项不止一笔的也不抄（_last_multi）：挑哪一笔都是猜
    last = _last_billed(session, [c.id for c in categories]) if statement is None else {}
    multi = _last_multi(session, last)
    ids = [m.id for m in ledger.active_members(session, today_jst())] if statement is None else []
    active = set(ids)
    # 「和上期一样」这一步现在要人点（面板上那个按钮、出账时那个勾），
    # 所以得先告诉界面：点下去会记哪几项、多少钱、算谁垫的，哪几项记不了
    ready: dict[int, tuple[int, int | None]] = {}
    blocked: dict[int, dict[str, Any]] = {}
    # 下面三样只给草稿，都是「提示一句、人来定」：
    suggest: set[int] = set()                           # 最近几期一模一样 → 问要不要开「和上期一样」
    elsewhere: dict[int, list[dict[str, Any]]] = {}     # 草稿里记在别的分类下、备注里写着这一项名字的
    rhythm: dict[int, tuple[int | None, int | None]] = {}   # 隔几期出现一次（出账时「还空着」分两段）
    # 分类没定规则的行，记的时候用的是全局默认 —— 「没写到谁」也得按它判
    global_rule = settings_svc.get(session, "default_rule")
    if draft is not None:
        todo, failed = _carry_plan(session, draft)
        ready = {c.id: (prev.amount_jpy, payer) for c, prev, payer, _ in todo}
        blocked = {f["category_id"]: f for f in failed}
        cuts = monthly_cut_ids(session)
        seen = _appearances(session, [c.id for c in categories], cuts)
        suggest = _suggest_same_as_last(session, categories, cuts, seen)
        elsewhere = _maybe_elsewhere(session, categories, draft)
        rhythm = {c.id: _rhythm(cuts, seen.get(c.id, {})) for c in categories}
    rows = []
    for c in categories:
        entry = mine.get(c.id)
        prev = last.get(c.id) if c.id not in multi else None
        seed = c.default_rule_json
        prev_payer = None
        if prev is not None:
            if prev.split_rule_json and _stale_for_today(prev.split_rule_json, None, active) is None:
                pruned = _carried_rule(prev.split_rule_json, active)
                if pruned and _splits(pruned, prev.amount_jpy, ids):
                    seed = pruned
            prev_payer = prev.payer_id if prev.payer_id in active else None
        # 翻一张已经出过的账单时只列它真有的那几项。空行会诱人往里填，
        # 而填出来的是**新账目**，落进当前草稿，根本不会进这张单子。
        if statement is not None and entry is None:
            continue
        carry = ready.get(c.id)
        stop = blocked.get(c.id) or {}
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
                #: 面板上显示的那一笔是谁垫的。原来前端从账单页的明细缓存里借着猜，
                #: 缓存旧了或者本期超过 200 笔就是个猜出来的人
                "payer_id": entry.payer_id if entry else None,
                "rule": entry.split_rule_json if entry else seed,
                #: 上期那一笔是谁垫的（还在籍才给）。面板上没录的行按它预填「谁付的」
                "last_payer_id": prev_payer,
                "date": entry.date.isoformat() if entry else None,
                #: 本期这个分类一共有几笔。>1 说明面板没显示全，界面上必须提示
                "entry_count": dup.get(c.id, 0),
                #: 按「和上期一样」点一下会记多少（只有草稿、开了开关、本期还没处理过的才有）
                "carry_amount": carry[0] if carry else None,
                #: 点下去这一笔算谁垫的 —— 和真去记的是同一份（_carry_plan），前端别自己推
                "carry_payer_id": carry[1] if carry else None,
                #: 上期这一项多少钱。**只给开了「和上期一样」的**（没开的一分都不许漏过来，D21）。
                #: 本期填没填都给：展开那一行时「照上期 ¥…」一直在 —— 填过了就显示
                #: 「已照上期」，改过了就能一键改回上期的数。上期有好几笔的不给（挑哪笔都是猜）
                "last_amount": prev.amount_jpy if prev is not None and c.same_as_last and prev.amount_jpy else None,
                #: 开了开关却记不了的原因（payer_left / rule_stale / last_multi），要人自己填
                "carry_blocked": stop.get("reason"),
                #: last_multi 时上期那几笔一共几笔、合计多少（只有开了开关的项才会走到这一步，D21）
                "carry_blocked_detail": stop.get("detail"),
                #: 起步的规则点名写了谁分多少、却没写到今天在籍的这几个人 —— 他们在这一项上按 0 算。
                #: 只标不补：新室友该担多少只有住的人知道
                "rule_missing_member_ids": (
                    _missing_members(seed or global_rule, active) if draft is not None and entry is None else []
                ),
                #: 最近 same_as_last_hint_k 期这一项每期一笔、金额都一样 —— 问一句要不要开
                #: 「和上期一样」。**只是个布尔，不带金额**（没开开关的项一分钱都不许漏过来，D21）
                "suggest_same_as_last": c.id in suggest,
                #: 草稿里记在别的分类下、备注里写着这一项名字的账（「其他·电费 ¥8,700」）。
                #: 只是「是不是它？」—— 不算「已填」，不取消照上期，也不替人改分类
                "maybe_elsewhere": elsewhere.get(c.id, []),
                #: 出账时「X 还空着」分两段用：见 _rhythm
                "cuts_since_last": rhythm.get(c.id, (None, None))[0],
                "typical_gap": rhythm.get(c.id, (None, None))[1],
            }
        )

    return {
        "default_date": today_jst().isoformat(),
        "rows": rows,
        # 面板一行只显示得下一笔，所以合计**不能由行加出来** —— 同一分类有两笔时
        # 会少算一笔，而账单上的「本期固定费」是全算的，两个数当场对不上
        "total": total,
    }


#: carry 这件事整个进程里一次只许跑一个，**出账也算在里面**（锁是 bill.period_lock，和出账共用）。
#: 「读一遍本期已经有哪几项 → 把缺的记上」中间隔着好几十毫秒。原来触发它的是
#: 账单页挂载 —— 群里一句「出账了」，三个人同时点开，两个请求都在对方 commit
#: 之前读到「本期还没记房租」，于是各记一笔，当期房租翻倍。现在改成人点按钮了，
#: 可两个人同时点、或者一个人连点照样会撞，锁留着。
#: 面板一行只显示得下一笔，屏幕上的金额还是对的、合计却是两倍。
#: 不加唯一索引 —— 同一分类手工记两笔是合法的（entry_count 就是为它准备的）


def carry_same_as_last(
    session: Session,
    *,
    actor_id: int | None,
    only: set[int] | None = None,
    after_statement_id: int | None = None,
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

    `after_statement_id`：点的那一刻手机上看到的最近一张账单（没出过账给 0）。
    两台手机同时出账、都勾着「先按上期记上」时，后到的那台点下去的那一刻，
    上期已经被前一台出掉了 —— 照记就是把房租记进**下一期**，再出一张只有房租的账单。
    对不上就 409 bill_changed、一笔不记。在锁里核：和「读本期有哪几项 → 记上」是同一步，
    出账也拿着同一把锁，核完之后不会有人插进来出账。
    不给就不核（旧版前端、面板上那颗「照上期」）。
    """
    with period_lock:
        if after_statement_id is not None:
            latest = latest_statement_id(session)
            if latest != after_statement_id:
                raise BillError("bill_changed", "刚有人出过账了，刷新一下再看", latest=latest)
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
    multi = _last_multi(session, last)
    ids = [m.id for m in ledger.active_members(session, today_jst())]
    active = set(ids)

    todo: list[tuple[Category, Entry, int | None, dict[str, Any] | None]] = []
    failed: list[dict[str, Any]] = []
    for c in categories:
        prev = last.get(c.id)
        if c.id in handled or prev is None or not prev.amount_jpy:
            continue
        if c.id in multi:
            # 上期那张单子上这一项有好几笔：抄哪一笔都是猜，求和又会把同额重复翻倍。
            # 笔数和合计给出去让人看着填（只有开了开关的项走到这里，D21 不漏）
            failed.append({"category_id": c.id, "name": c.name, "reason": "last_multi", "detail": multi[c.id]})
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
        if _charged_the_departed(rule, active):
            # **人少了也拦。** 原来是剔掉搬走的人（连他的调整额）照记：上期 45,000/40,000/35,000，
            # Kan 一走就默默变成 65,000/55,000，按钮和通知只报「房租 ¥120,000，按上期」——
            # 月中搬走的人那期该不该担、调整额怎么改，全被程序替人定了。和「人多了」同样处理，
            # 请人手填一期；之后各期照抄新的那一笔。
            # **不放进 _stale_for_today**：那边一拦，面板手填的起步分法会退回分类默认（monthly_rows）
            failed.append({"category_id": c.id, "name": c.name, "reason": "rule_stale"})
            continue
        pruned = _carried_rule(rule, active)
        # 剔完人还得分得下去：上期「只算 Zen」而 Zen 搬走了，剔完是谁都不担；exact 的老规则
        # 剔掉一个人，合计就对不上总额。点下去必然失败的，按钮就别亮着 ——
        # 和「人变了」一样请人自己重填（docstring 那句「按钮上写的和点下去记的是同一份口径」）
        if pruned and not _splits(pruned, prev.amount_jpy, ids):
            failed.append({"category_id": c.id, "name": c.name, "reason": "rule_stale"})
            continue
        todo.append((c, prev, payer, pruned))
    return todo, failed


def _carried_rule(rule: dict[str, Any] | None, active: set[int]) -> dict[str, Any] | None:
    """照上期抄过来的分摊规则：剔掉搬走的人（_prune_rule），**再去掉「余数归谁」**。

    每笔存下的规则都带着记账那一刻设置里的 remainder_to（界面上没有逐笔改它的地方）。
    原样抄的话，设置里改成「按成员顺序」之后，固定费还一期一期按「给付款人」分 ——
    设置说明写的是「改了之后新账都按新的分」。去掉它，记账时按现在的设置补上
    """
    out = _prune_rule(rule, active)
    if out:
        out.pop("remainder_to", None)
    return out


def _splits(rule: dict[str, Any], amount: int, ids: list[int]) -> bool:
    """这条规则套在今天这几个人、这个金额上分不分得下去。试算一遍，不写库"""
    try:
        split(expand(rule, ids), amount, order=[str(i) for i in ids])
    except (ValueError, KeyError):
        return False
    return True


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
                # 审计里留一笔「抄自上期哪一笔」，否则它和手填的长得一模一样
                audit_via={"kind": "carry", "from_entry": prev.id},
            )
        except (ValueError, KeyError) as e:   # LedgerError / RuleError / SplitError 都是 ValueError
            session.rollback()
            # 只回码（和别处一样，文案归前端）；KeyError 之类没有码的才退回原文
            failed.append({"category_id": c.id, "name": c.name, "reason": getattr(e, "code", str(e))})
            continue
        # 付款人也报出来：通知里只写「房租 ¥120,000」的话，记成了谁垫的没人看得见
        made.append({"category_id": c.id, "name": c.name, "amount": entry.amount_jpy, "payer_id": entry.payer_id})
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

    「人少了」（上期给搬走的人记过钱）在 _carry_plan 里另拦（_charged_the_departed），
    不在这儿：monthly_rows 拿这个函数判「手填的起步分法能不能从上期那一笔抄」，
    这里一拦，起步就会退回分类默认 —— 那是另一件事，不该跟着变。
    """
    if payer is not None and payer not in active:
        return "payer_left"
    if _missing_members(rule, active):
        return "rule_stale"
    return None


def _missing_members(rule: dict[str, Any] | None, active: set[int]) -> list[int]:
    """规则**点名**写了谁分多少、却没写到的那几个今天在籍的人 —— expand 会把他们按 0 补齐。

    equal_weight 那种不点名的写法永远是空的（谁在籍就算谁）。照上期（_stale_for_today）
    和面板上的提示（monthly_rows 的 rule_missing_member_ids）共用这一条，口径不会分叉。
    """
    rule = rule or {}
    named = rule.get("exact") if rule.get("mode", "ratio") == "exact" else rule.get("weights")
    if not (isinstance(named, dict) and named):
        return []
    listed: set[int] = set()
    for key in named:
        try:
            listed.add(int(key))
        except (TypeError, ValueError):
            continue
    return sorted(active - listed)


def _charged_the_departed(rule: dict[str, Any] | None, active: set[int]) -> bool:
    """这条规则有没有给**已经不在籍**的人记过钱：权重、调整额、定额任一项不是 0。

    是 0 的不算 —— 「这一项本来就不算他」（比如只算两个人的车位）照抄不改钱。
    """
    for field in ("weights", "adjustments", "exact"):
        section = (rule or {}).get(field)
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            try:
                gone = int(key) not in active
            except (TypeError, ValueError):
                continue
            if gone and value:
                return True
    return False


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


def _last_multi(session: Session, last: dict[int, Entry]) -> dict[int, dict[str, int]]:
    """上期那一笔所在的那张账单上，这一项**不止一笔**支出的：{分类: {count, total}}。

    _last_billed 每个分类只挑一笔（日期、id 最新的那笔）。同一张单子上这一项有两笔
    （两台手机同时填、面板缓存旧了又 POST 一次，出账时没清掉）的话，挑中哪一笔全凭 id：
    ¥120,000 的房租可能被抄成 ¥20,000，垫付人也跟着换。这种不抄，也不替人求和
    （同额重复时求和就是房租翻倍）—— 交给人填。
    **只数那一笔所在的那张**：跨账单数的话，隔月的水费、历史上的每一期都会被数进来。
    删掉的不数：重复清理掉之后就该恢复照抄。
    """
    if not last:
        return {}
    out: dict[int, dict[str, int]] = {}
    for cid, sid, n, total in session.exec(
        select(Entry.category_id, Entry.statement_id, func.count(), func.sum(Entry.amount_jpy))
        .where(
            Entry.category_id.in_(list(last)),
            Entry.statement_id.in_({e.statement_id for e in last.values()}),
            Entry.deleted_at.is_(None),
            Entry.kind == EntryKind.expense,
        )
        .group_by(Entry.category_id, Entry.statement_id)
    ):
        if n > 1 and last[cid].statement_id == sid:
            out[cid] = {"count": int(n), "total": int(total)}
    return out


def _appearances(
    session: Session, category_ids: list[int], cuts: list[int]
) -> dict[int, dict[int, tuple[int, int, int]]]:
    """每个固定费分类在每张结了固定费的账单上：几笔支出、最小、最大金额（删掉的不算）。

    「隔几期出现一次」和「最近几期是不是一模一样」都从这一份数，一条 group by。
    """
    if not category_ids or not cuts:
        return {}
    out: dict[int, dict[int, tuple[int, int, int]]] = {}
    for cid, sid, n, lo, hi in session.exec(
        select(
            Entry.category_id, Entry.statement_id, func.count(),
            func.min(Entry.amount_jpy), func.max(Entry.amount_jpy),
        )
        .where(
            Entry.category_id.in_(category_ids),
            Entry.statement_id.in_(cuts),
            Entry.deleted_at.is_(None),
            Entry.kind == EntryKind.expense,
        )
        .group_by(Entry.category_id, Entry.statement_id)
    ):
        out.setdefault(cid, {})[sid] = (int(n), int(lo), int(hi))
    return out


def _suggest_same_as_last(
    session: Session,
    categories: list[Category],
    cuts: list[int],
    seen: dict[int, dict[int, tuple[int, int, int]]],
) -> set[int]:
    """该问一句「要不要开『和上期一样』」的那几项：没开、没归档，最近 k 张结了固定费的账单上
    **每张都恰好一笔、金额全一样**。

    「最近 k 期」必须按账单数（跳过不含固定费的小账），不能按分类往回找最近 k 笔：
    那样隔月收、每次金额一样的水费也会被挑中，人照提示一开，
    单月那期出账框就默认勾上「先按上期记上：水费」—— 每个单月多收一次水费。
    缺一期、某期有两笔、不满 k 张，都不问。
    """
    k = int(settings_svc.get(session, "same_as_last_hint_k") or 0)
    if k <= 0 or len(cuts) < k:
        return set()
    recent = cuts[-k:]
    out: set[int] = set()
    for c in categories:
        if c.same_as_last or c.archived:
            continue
        per = seen.get(c.id, {})
        got = [per.get(sid) for sid in recent]
        if all(g is not None and g[0] == 1 for g in got) and len({g[1] for g in got}) == 1:  # type: ignore[index]
            out.add(c.id)
    return out


def _norm(text: str) -> str:
    """比名字用：全角半角、大小写都抹平（「ＷｉＦｉ」「wifi」算同一个）"""
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _maybe_elsewhere(
    session: Session, categories: list[Category], draft: list[Entry]
) -> dict[int, list[dict[str, Any]]]:
    """草稿里记在**别的分类**下、备注里写着这一项名字的支出（「其他」备注「电费」）。

    固定费记错了分类时，面板和出账框照样说「电费还空着」，人照着再填一次就重复了；
    而那一笔在「本期其他」里看得见，却和这条提示连不上。分类名是用户自己录的，
    不需要另一张词表。子串匹配会误报（「ガス」配上「ガスコンロ」），所以只问「是不是它？」——
    不算已填、不取消照上期、不改分类。
    """
    every = list(session.exec(select(Category)))
    names = {c.id: c.name for c in every}
    fixed = {c.id for c in every if c.monthly}   # 含归档的
    pool = [
        e for e in draft
        if e.kind == EntryKind.expense and e.category_id not in fixed and _norm(e.title)
    ]
    out: dict[int, list[dict[str, Any]]] = {}
    for c in categories:
        key = _norm(c.name)
        if not key:
            continue
        hits = [
            {"entry_id": e.id, "amount": e.amount_jpy,
             "category_name": names.get(e.category_id) if e.category_id is not None else None,
             "title": e.title}
            for e in pool if key in _norm(e.title)
        ]
        if hits:
            out[c.id] = hits
    return out


def _rhythm(cuts: list[int], per: dict[int, Any]) -> tuple[int | None, int | None]:
    """这一项隔几期出现一次：(cuts_since_last, typical_gap)。

    出账时「X 还空着」有一半是隔月收的水费 —— 这期本来就轮空。界面据此把空着的项
    分成两段：「按往常这期该有」（警示）和「上期记过、往常隔 N 期一次」（灰字），
    **一项都不藏**。判据前端只用一条：cuts_since_last < typical_gap 才进灰字。

    * cuts_since_last：从它上一次出现的那一期，数到**这一期（草稿）**隔了几期 ——
      上一张就有它是 1，上上张才有是 2；从没出现过是 None。
    * typical_gap：历来隔几期出现一次（间隔的中位数）。**历史不到两个间隔、
      或者最近两个间隔不都等于它**就给 None —— 猜错的代价是把一笔真忘了的账画成灰字，
      节奏不稳就照旧当警示。
    「期」按结了固定费的账单数（monthly_cut_ids），中途的日常小账不算。
    """
    idx = [i for i, sid in enumerate(cuts) if sid in per]
    if not idx:
        return None, None
    since = len(cuts) - idx[-1]
    gaps = [b - a for a, b in zip(idx, idx[1:])]
    if len(gaps) < 2:
        return since, None
    usual = statistics.median_low(gaps)
    return since, (usual if gaps[-1] == gaps[-2] == usual else None)
