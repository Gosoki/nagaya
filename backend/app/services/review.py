"""草稿账单上要人看一眼的几样 —— **只标出来，不替人做决定**。

  * membership_gaps：一笔账的参与人和那天谁在籍对不上（事后补标了搬走日 / 入住日）
  * possible_duplicates：两台手机各记了一遍同一张小票、同一笔转账
  * outliers：一笔日常支出比这个分类平时大得离谱（多打一个 0、把房租记进「其他」）

三样都是**弱证据**：搬走的人可能真吃到了那天、同一天真买了两件 ¥798、真买了一台冰箱。
所以只挂签、写「请核对」，不改钱、不拦出账、不自动合并或删除 ——
看错了的代价是多看一眼，做错了的代价是记错钱。

都**只看草稿**：出账之后标记自然消失。那样就不需要「这不是重复」之类的已读状态
（那得加列），挂错的签最多挂到下次出账。
依赖方向是 bill → review，这里不许 import bill（会成环）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from app.models import Entry, EntryKind, Member
from app.services import settings as settings_svc
from app.services.ledger import ratio_label


def draft_review(
    session: Session,
    entries: list[Entry],
    shares: dict[int, dict[int, int]],
    members: list[Member],
    fixed: set[int],
    help_for: dict[int, int],
) -> dict[str, Any]:
    """草稿账单上的那三样。entries / shares 是 build_bill 手里现成的，别再查一遍。

    fixed：固定费分类（含归档的）；help_for：认作帮买的那几笔 → 帮谁买的（bill.help_buy_for）。
    """
    return {
        "membership_gaps": membership_gaps(entries, shares, members, fixed, set(help_for)),
        "possible_duplicates": possible_duplicates(
            entries, fixed, int(settings_svc.get(session, "duplicate_window_days") or 0), help_for
        ),
        "outliers": outliers(session, entries, fixed),
    }


def membership_gaps(
    entries: list[Entry],
    shares: dict[int, dict[int, int]],
    members: list[Member],
    fixed: set[int],
    help_ids: set[int],
) -> list[dict[str, Any]]:
    """参与人和这笔的日期当天谁在籍对不上的那几笔。

    分摊是记账那一刻按当天在籍的人算好、落库固化的（rules.expand 给当天在籍的每个人
    都补一行，不参与就是 0）。之后才去补标搬走日、改入住日，草稿里已经记下的账**一个数都不变**：
    10/15 搬走、10/29 才去标，这半个月的伙食照样算着他一份；新室友 10/10 入住、
    晚几天才建账号，那之后的账一笔都没算他。这本来就是对的（历史不许悄悄重算），
    但三个人谁都看不见 —— 那就标出来，让人自己决定要不要改那几笔。

    两种情况，都是结构上只有「事后改了日期」才会出现的：
      * left_but_charged：这个人份额不是 0，可那天他已经不在籍了；
      * joined_not_charged：那天他在籍，这笔里却连一行（哪怕是 0）都没有他。
        点了「不参与」的人是有一行 0 的，不会被报。

    跳过三类，它们和在籍对不上是设计如此：
      * 转账 —— 收钱的人搬走了也照样收钱；
      * 固定费（含归档的）—— 出账时日期统一盖成出账日（D30），月中有人搬走，
        房租那笔在结构上必然对不上；
      * 帮买 —— 本来就只算一个人。
    垫付人不查：「垫付人当天在籍」是另一条还挂着、等人拍板的事。
    """
    gaps: list[dict[str, Any]] = []
    for e in entries:
        if e.kind == EntryKind.settlement or e.category_id in fixed or e.id in help_ids:
            continue
        mine = shares.get(e.id, {})
        for m in members:
            if m.id in mine:
                if mine[m.id] and not m.is_active(e.date):
                    gaps.append({"entry_id": e.id, "member_id": m.id,
                                 "type": "left_but_charged", "share": mine[m.id]})
            elif m.is_active(e.date):
                gaps.append({"entry_id": e.id, "member_id": m.id,
                             "type": "joined_not_charged", "share": 0})
    return gaps


def possible_duplicates(
    entries: list[Entry], fixed: set[int], window: int, help_for: dict[int, int] | None = None
) -> list[dict[str, int]]:
    """疑似记了两遍的那几对（a < b，按 entry id）。window：日期最多差几天，0 ＝ 不查。

      * 支出：同一分类、同金额，**不看谁付的** —— 设了默认垫付人的话两台手机默认的是
        同一个付款人，没设的话各自填自己，付款人不同反倒是重复的典型样子；
      * 帮买（help_for：那一笔 → 帮谁买的）：同一个受益人、同金额，同样不看谁付的。
        新记的帮买都不挂分类，按分类分组的话所有帮买挤进同一组 —— 同一天替 Kan、替 Zen
        各买一份 ¥680 会被问「是不是记了两遍」，受益人明明不同。真记重的那种
        （Kan 记「Go 替我买」、Go 又记「我替 Kan 买」）帮的是同一个人，照样配得上；
      * 转账：同一对人、同方向、同金额 —— 转出方和转入方各记一次，余额就动了两倍。
    收入不查；固定费不查（面板上那一行已经有「另有 N 笔」）。
    """
    if window <= 0:
        return []
    help_for = help_for or {}
    groups: dict[tuple[Any, ...], list[Entry]] = {}
    for e in entries:
        if e.id in help_for:
            key: tuple[Any, ...] = ("help", help_for[e.id], abs(e.amount_jpy))
        elif e.kind == EntryKind.expense and e.category_id not in fixed:
            key = ("expense", e.category_id, abs(e.amount_jpy))
        elif e.kind == EntryKind.settlement:
            key = ("settlement", e.payer_id, e.to_member_id, abs(e.amount_jpy))
        else:
            continue
        groups.setdefault(key, []).append(e)
    pairs: list[dict[str, int]] = []
    for group in groups.values():
        for i, x in enumerate(group):
            for y in group[i + 1:]:
                if abs((x.date - y.date).days) <= window:
                    pairs.append({"a": min(x.id, y.id), "b": max(x.id, y.id)})
    return sorted(pairs, key=lambda p: (p["a"], p["b"]))


def outliers(session: Session, entries: list[Entry], fixed: set[int]) -> list[dict[str, Any]]:
    """比这个分类平时大得离谱的那几笔日常支出。**只看偏大这一头。**

    「平时」＝ 同一分类、这笔日期往前 outlier_days 天之内的支出（不管出没出过账，
    删掉的不算，**这一笔自己不算**）的中位数。用中位数不用平均：「其他」里偶尔一台
    冰箱会把平均数拽上去，中位数不动。历史不够 outlier_min_history 笔的分类不判 ——
    中位数不可信，宁可不标。

    只看有分类、不是固定费的支出（帮买新记的不挂分类，固定费有自己的量级闸）。

    不判偏小：日用这种分类里「一趟买好几样」和「单买一卷卫生纸」混在一起，¥98–¥298 的单件
    对着 ¥1,500 上下的中位数，按「几分之一以下」判，在贴近真实价位的五年模拟数据上
    四分之三的草稿都挂了「待核对」，挂的几乎全是这种单件 —— 每期都冒、出账前消不掉，
    人很快就不看这一块，偏大那头真多打了一个 0 也跟着被略过去。
    少打一个 0 记小了要判的话，得另配阈值、另量一遍误报，不能借偏大这头的设置。
    """
    limit = int(settings_svc.get(session, "outlier_ratio") or 0)
    days = int(settings_svc.get(session, "outlier_days") or 0)
    if limit <= 0 or days <= 0:
        return []
    need = max(1, int(settings_svc.get(session, "outlier_min_history") or 0))
    todo = [
        e for e in entries
        if e.kind == EntryKind.expense and e.category_id is not None and e.category_id not in fixed
    ]
    if not todo:
        return []
    span = dt.timedelta(days=days)
    # 一次取完要比的那段历史，再在内存里按每一笔各自的窗口切 ——
    # 草稿一两百笔，逐笔查就是一两百次
    history: dict[int, list[tuple[dt.date, int, int]]] = {}
    for eid, cid, on, amount in session.exec(
        select(Entry.id, Entry.category_id, Entry.date, Entry.amount_jpy).where(
            Entry.kind == EntryKind.expense,
            Entry.deleted_at.is_(None),
            Entry.category_id.in_({e.category_id for e in todo}),
            Entry.date >= min(e.date for e in todo) - span,
            Entry.date <= max(e.date for e in todo),
        )
    ):
        history.setdefault(cid, []).append((on, eid, amount))

    out: list[dict[str, Any]] = []
    for e in todo:
        since = e.date - span
        sample = sorted(
            amount for on, eid, amount in history.get(e.category_id, ())  # type: ignore[arg-type]
            if eid != e.id and since <= on <= e.date
        )
        if len(sample) < need:
            continue
        n = len(sample)
        # 中位数的两倍：偶数笔时是中间两笔之和，留在整数里，比较时两边一起乘 2
        median2 = sample[n // 2] * 2 if n % 2 else sample[n // 2 - 1] + sample[n // 2]
        twice = e.amount_jpy * 2
        if twice >= limit * median2:
            out.append({"entry_id": e.id, "median": median2 // 2, "ratio": ratio_label(twice, median2)})
    return out
