"""The stock pools a backtest can run on: the user's own pool, or an index as it was on each day."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from quant_platform.application.backtest_service import BacktestService
from quant_platform.data.index_constituents import (
    CHECKS_TABLE, CONSTITUENTS_TABLE, CSI_800, INDEX_UNIVERSES, checked_range, index_name, members_on, stored_lists,
    week_start,
)

from .runtime import market_repository

CURRENT_POOL = "当前股票池"


def market_options() -> list[dict[str, Any]]:
    """The user's pool first, then each index with the dates its member history covers."""

    repository = market_repository()
    checks = repository.read_table(CHECKS_TABLE)
    options: list[dict[str, Any]] = [{"value": CURRENT_POOL, "label": "当前股票池", "available": True}]
    for index_symbol in INDEX_UNIVERSES:
        covered = checked_range(checks, index_symbol)
        option = {
            "value": index_symbol,
            "label": f"{index_name(index_symbol)}历史成分股",
            "available": covered is not None,
            "start_date": covered[0].isoformat() if covered else None,
            "end_date": covered[1].isoformat() if covered else None,
        }
        if index_symbol == CSI_800 and covered:
            lists = stored_lists(repository.read_table(CONSTITUENTS_TABLE), index_symbol)
            start, end = covered
            dates = [start, *sorted(day for day in lists if start < day <= end), end + timedelta(days=1)]
            option["available"] = members_on(lists, start) is not None
            option["usable_through"] = (week_start(end) + timedelta(days=6)).isoformat()
            option["partial_membership"] = [
                {"start_date": first.isoformat(), "end_date": (following - timedelta(days=1)).isoformat(),
                 "count": len(members)}
                for first, following in zip(dates, dates[1:])
                if (members := members_on(lists, first)) is not None and len(members) < 800
            ]
        options.append(option)
    return options


def use_market(service: BacktestService, market: str) -> None:
    """Point the service at the chosen pool. An index is used as it was on each day, never today's list."""

    if market == CURRENT_POOL:
        return
    if market not in INDEX_UNIVERSES:
        raise ValueError("不支持这个股票范围，请选择当前股票池或列表里的指数。")
    section = service.configs["universe"].setdefault("universe", {})
    section["mode"] = "historical"
    section["index"] = market
