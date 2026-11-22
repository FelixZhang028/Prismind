"""Trading-day eligibility filters for cross-sectional factor research."""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from quant_platform.data.index_constituents import UNIVERSE_COLUMN


@dataclass(frozen=True)
class FactorSampleFilters:
    exclude_st: bool = False
    exclude_suspended: bool = False
    exclude_recent_ipos: bool = False
    exclude_limit_moves: bool = False

    def active(self) -> bool:
        return (
            self.exclude_st
            or self.exclude_suspended
            or self.exclude_recent_ipos
            or self.exclude_limit_moves
        )

    def apply(self, bars: pd.DataFrame, start: date, end: date) -> tuple[pd.Series, list[str]]:
        """Return one eligibility mask per row, retaining histories for time-series inputs."""

        eligible = bars.get(UNIVERSE_COLUMN, pd.Series(True, index=bars.index)).fillna(False)
        days = pd.to_datetime(bars["trade_date"]).dt.normalize()
        in_period = days.between(pd.Timestamp(start), pd.Timestamp(end))
        notes = []
        for enabled, column, label in (
            (self.exclude_st, "is_st", "排除 ST"),
            (self.exclude_suspended, "is_suspended", "排除停牌"),
            (self.exclude_recent_ipos, "list_date", "上市满一年"),
        ):
            if not enabled:
                continue
            flag = bars.get(column, pd.Series(pd.NA, index=bars.index, dtype="object"))
            if column == "list_date":
                flag = pd.to_datetime(flag, errors="coerce")
                passes = days.ge(flag + pd.DateOffset(years=1))
            else:
                passes = flag.eq(False).fillna(False)
            active = eligible & in_period
            missing = int((active & flag.isna()).sum())
            excluded = int((active & ~passes).sum())
            missing_note = f"，其中 {missing} 个缺少状态或上市日期" if missing else ""
            notes.append(f"「{label}」筛掉 {excluded} 个股票交易日{missing_note}")
            eligible = eligible & passes
        if self.exclude_limit_moves:
            close = pd.to_numeric(bars.get("raw_close", pd.Series(pd.NA, index=bars.index)), errors="coerce")
            up_limit = pd.to_numeric(bars.get("up_limit", pd.Series(pd.NA, index=bars.index)), errors="coerce")
            down_limit = pd.to_numeric(bars.get("down_limit", pd.Series(pd.NA, index=bars.index)), errors="coerce")
            known = close.gt(0) & up_limit.gt(0) & down_limit.gt(0)
            at_limit = known & ((close >= up_limit - 1e-6) | (close <= down_limit + 1e-6))
            passes = known & ~at_limit
            active = eligible & in_period
            missing = int((active & ~known).sum())
            excluded = int((active & ~passes).sum())
            missing_note = f"，其中 {missing} 个缺少涨跌停价" if missing else ""
            notes.append(f"「排除涨跌停」筛掉 {excluded} 个信号日股票交易日{missing_note}")
            eligible = eligible & passes
        return eligible, notes
