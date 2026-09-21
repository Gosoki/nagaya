"""账期回归 —— SPEC §4.6 的「边界（必须测）」逐条落实。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.period import label_for, next_period, period_bounds, start_of_month


def test_natural_month() -> None:
    """起算日 1 ＝ 自然月。"""
    assert period_bounds(date(2026, 9, 15), 1) == (date(2026, 9, 1), date(2026, 9, 30))
    assert period_bounds(date(2026, 2, 1), 1) == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds(date(2024, 2, 10), 1) == (date(2024, 2, 1), date(2024, 2, 29))  # 闰年


def test_start_day_25() -> None:
    """起算日 25：9/15 属于 8/25〜9/24 这一期，标签是 2026-09。"""
    assert period_bounds(date(2026, 9, 15), 25) == (date(2026, 8, 25), date(2026, 9, 24))
    assert period_bounds(date(2026, 9, 25), 25) == (date(2026, 9, 25), date(2026, 10, 24))
    assert label_for(date(2026, 9, 15), 25) == "2026-09"


def test_rent_paid_on_9_30_with_start_day_25() -> None:
    """SPEC §4.6：起算日 25 时，9/30 付的 10 月家賃落进「10 月期」。"""
    assert label_for(date(2026, 9, 30), 25) == "2026-10"
    # 而起算日用默认的 1 时，它落在 9 月期 —— 文档里明说了的副作用
    assert label_for(date(2026, 9, 30), 1) == "2026-09"


def test_short_month_clamps_to_last_day() -> None:
    """起算日 31 撞上 2 月，取 2/28；绝不越到 3/3。"""
    assert start_of_month(2026, 2, 31) == date(2026, 2, 28)
    assert start_of_month(2024, 2, 31) == date(2024, 2, 29)
    assert start_of_month(2026, 4, 31) == date(2026, 4, 30)
    assert period_bounds(date(2026, 2, 15), 31) == (date(2026, 1, 31), date(2026, 2, 27))
    assert period_bounds(date(2026, 3, 1), 31) == (date(2026, 2, 28), date(2026, 3, 30))


def test_year_boundary() -> None:
    assert period_bounds(date(2026, 12, 20), 25) == (date(2026, 11, 25), date(2026, 12, 24))
    assert period_bounds(date(2027, 1, 3), 25) == (date(2026, 12, 25), date(2027, 1, 24))


@pytest.mark.parametrize("start_day", [1, 15, 25, 28, 29, 30, 31])
def test_no_gaps_no_overlaps(start_day: int) -> None:
    """连续 60 期首尾相接：既不重叠也不留空隙。"""
    start, end = period_bounds(date(2024, 1, 10), start_day)
    for _ in range(60):
        nxt_start, nxt_end = next_period(start, start_day)
        assert nxt_start == end + timedelta(days=1), (start_day, start, end, nxt_start)
        assert nxt_end > nxt_start
        start, end = nxt_start, nxt_end


@pytest.mark.parametrize("start_day", [1, 15, 25, 31])
def test_every_day_belongs_to_exactly_one_period(start_day: int) -> None:
    """随便取一段连续日期，每天都能落进一个期，且期内自洽。"""
    day = date(2025, 11, 1)
    for _ in range(500):
        start, end = period_bounds(day, start_day)
        assert start <= day <= end, (start_day, day, start, end)
        day += timedelta(days=1)
