"""留痕 —— 审计日志只在这里写。

一笔账的记、改、删、恢复，出账，以及成员、分类、设置这类会影响分钱的配置，
改动前后各拍一张快照进 audit_log。都不 commit：跟着调用方的那次事务一起落库。

**账目快照的形状只在 entry_snapshot 一处拼。** 账单上「出账后被改过」
（bill._really_changed）是拿一笔账现在的样子，和它出账后第一条审计的 before 逐键比的，
两边必须同形 —— 给快照加一个键、忘了改另一边，所有出账后被碰过的账都会被判成
「改过了」，已经发出去的账单一直挂着那句话。
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, SQLModel, select

from app.models import AuditLog, Entry, EntryShare, now_utc


def entry_snapshot(entry: Entry, shares: dict[str, int]) -> dict[str, Any]:
    """一笔账的快照：字段本身，加上每人分摊多少（键是字符串形式的成员 id，放在最后）。"""
    return entry.model_dump(mode="json") | {"shares": shares}


def snapshot(session: Session, entry: Entry) -> dict[str, Any]:
    """从库里取这笔账此刻的分摊，拍一张快照。"""
    shares = session.exec(select(EntryShare).where(EntryShare.entry_id == entry.id)).all()
    return entry_snapshot(entry, {str(s.member_id): s.amount_jpy for s in shares})


def write(
    session: Session,
    actor_id: int | None,
    action: str,
    table: str,
    target_id: int | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        AuditLog(
            at=now_utc(),
            member_id=actor_id,
            action=action,
            target_table=table,
            target_id=target_id,
            before_json=before,
            after_json=after,
        )
    )


def config(
    session: Session,
    actor_id: int | None,
    action: str,
    table: str,
    target_id: int | None,
    before: SQLModel | dict[str, Any] | None,
    after: SQLModel | dict[str, Any] | None,
    *,
    drop: tuple[str, ...] = (),
) -> None:
    """成员、分类、设置这类**会影响分钱的配置**也留痕。

    原来审计只盖 entry：谁把房租的默认分摊改了、谁把某人的搬出日往前挪了一个月、
    谁把「余数归谁」换了 —— 这些都会让之后的每一笔账换一种分法，却查不到是谁动的。
    `drop` 里的字段不进日志（密码哈希、头像这种）。
    """

    def plain(x: SQLModel | dict[str, Any] | None) -> dict[str, Any] | None:
        if x is None:
            return None
        # 先排除再序列化：头像是二进制，交给 JSON 序列化会直接抛错
        data = json.loads(x.model_dump_json(exclude=set(drop))) if isinstance(x, SQLModel) else dict(x)
        for key in drop:
            data.pop(key, None)
        return data

    write(session, actor_id, action, table, target_id, plain(before), plain(after))
