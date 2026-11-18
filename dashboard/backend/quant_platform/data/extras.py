"""Data a factor or strategy can ask for beyond the daily bar itself.

Daily valuation and turnover, quarterly financial reports, industry classifications and
trailing cash dividends are aligned to each bar's date.
Callers name the columns they need; nothing extra is read otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from quant_platform.data.corporate_actions import DIVIDEND_YIELD, MISSING_DIVIDEND_YIELD_MESSAGE
from quant_platform.data.fundamentals import (
    MISSING_FUNDAMENTALS_MESSAGE,
    MISSING_OPERATING_CASH_FLOW_MESSAGE,
    fundamental_columns,
)
from quant_platform.data.indicators import MISSING_INDICATORS_MESSAGE, indicator_columns
from quant_platform.data.industry import MISSING_INDUSTRY_MESSAGE, industry_columns


def extra_columns(fields: Iterable[str]) -> list[str]:
    """The supported extra data columns among ``fields``."""

    wanted = list(fields)
    dividends = [DIVIDEND_YIELD] if DIVIDEND_YIELD in wanted else []
    return [*indicator_columns(wanted), *fundamental_columns(wanted), *industry_columns(wanted), *dividends]


def require_extra_data(bars: pd.DataFrame, columns: Iterable[str]) -> None:
    """Fail with a message the user can act on when a requested column was never downloaded."""

    wanted = list(columns)
    for names, message in ((indicator_columns(wanted), MISSING_INDICATORS_MESSAGE),
                           (fundamental_columns(wanted), MISSING_FUNDAMENTALS_MESSAGE),
                           (industry_columns(wanted), MISSING_INDUSTRY_MESSAGE),
                           ([DIVIDEND_YIELD] if DIVIDEND_YIELD in wanted else [], MISSING_DIVIDEND_YIELD_MESSAGE)):
        for column in names:
            if column not in bars.columns or not bars[column].notna().any():
                if column == "operating_cash_flow":
                    raise ValueError(MISSING_OPERATING_CASH_FLOW_MESSAGE)
                raise ValueError(message)
