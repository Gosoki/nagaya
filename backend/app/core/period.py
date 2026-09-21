"""账期计算 —— SPEC §4.6。

账期按**费用发生日**归期，默认自然月（起算日 1）。起算日可改成 25 之类，
届时「2026-09 期」＝ 2026-08-25 〜 2026-09-24。

两条规矩：
    * 标签取**结束日所在月** —— 结算发生在期末，人习惯用那个月称呼这一期
    * 起算日撞上短月（29/30/31）时取**该月最后一天**，绝不越到下个月
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

#: 起算日默认值。1 ＝ 自然月。
DEFAULT_PERIOD_START_DAY = 1


def start_of_month(year: int, month: int, start_day: int) -> date:
    """某个月的账期起算日。2 月遇上 start_day=31 就落在 2/28（或闰年 2/29）。"""
    if not 1 <= start_day <= 31:
        raise ValueError(f"起算日必须在 1〜31 之间，收到 {start_day}")
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(start_day, last))


def period_bounds(anchor: date, start_day: int = DEFAULT_PERIOD_START_DAY) -> tuple[date, date]:
    """anchor 这天落在哪个账期，返回该期的 [起, 止]（闭区间）。"""
    start = start_of_month(anchor.year, anchor.month, start_day)
    if anchor < start:
        # 还没到本月起算日，说明属于上个月起算的那一期
        year, month = (anchor.year, anchor.month - 1) if anchor.month > 1 else (anchor.year - 1, 12)
        start = start_of_month(year, month, start_day)
    year, month = (start.year, start.month + 1) if start.month < 12 else (start.year + 1, 1)
    end = start_of_month(year, month, start_day) - timedelta(days=1)
    return start, end


def period_label(end: date) -> str:
    """账期标签，取结束日所在月：'2026-09'。"""
    return f"{end.year:04d}-{end.month:02d}"


def label_for(anchor: date, start_day: int = DEFAULT_PERIOD_START_DAY) -> str:
    """anchor 这天属于哪个账期标签。"""
    return period_label(period_bounds(anchor, start_day)[1])


def next_period(start: date, start_day: int = DEFAULT_PERIOD_START_DAY) -> tuple[date, date]:
    """给定一期的起点，返回下一期的 [起, 止]。用来连续建账期，保证不留空隙。"""
    _, end = period_bounds(start, start_day)
    return period_bounds(end + timedelta(days=1), start_day)
