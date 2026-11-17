"""Read explicit, auditable cash and share entitlements from the local repository."""

from datetime import date

import numpy as np
import pandas as pd

from quant_platform.accounts.models import CorporateAction

DIVIDEND_YIELD = "dividend_yield"
MISSING_DIVIDEND_YIELD_MESSAGE = "所选股票与日期没有可用的近一年股息率，请检查分红记录或调整股票范围和日期。"


def trailing_dividend_yield(bars: pd.DataFrame, actions: pd.DataFrame) -> np.ndarray:
    """Recorded cash over the preceding 365 days divided by the unadjusted close.

    Use ex-dates through the signal date and express past dividends per current share.
    No recorded cash in the window leaves the yield missing because coverage is incomplete.
    """
    result = np.full(len(bars), np.nan)
    if bars.empty or actions.empty:
        return result
    days = pd.to_datetime(bars["trade_date"]).to_numpy(dtype="datetime64[ns]")
    window_starts = days - np.timedelta64(365, "D")
    prices = pd.to_numeric(bars["raw_close"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    events = actions[actions["symbol"].isin(bars["symbol"])].copy()
    events["ex_date"] = pd.to_datetime(events["ex_date"], errors="coerce")
    events = events[events["ex_date"].between(window_starts.min(), days.max())]
    events = events.sort_values("ex_date")
    bar_positions = bars.groupby("symbol", observed=True, sort=False).indices
    for symbol, group in events.groupby("symbol", observed=True, sort=False):
        positions = bar_positions[symbol]
        ex_dates = group["ex_date"].to_numpy(dtype="datetime64[ns]")
        cash = group["cash_per_share"].to_numpy(dtype=float, na_value=np.nan)
        multipliers = group["share_multiplier"].to_numpy(dtype=float, na_value=np.nan)
        # A cash payment on a split date is quoted per share held before that split.
        shares = np.r_[1.0, multipliers.cumprod()]
        cumulative_cash = np.r_[0.0, (cash * shares[:-1]).cumsum()]
        start = ex_dates.searchsorted(window_starts[positions], side="right")
        end = ex_dates.searchsorted(days[positions], side="right")
        trailing_cash = (cumulative_cash[end] - cumulative_cash[start]) / shares[end]
        price = prices[positions]
        eligible = np.isfinite(trailing_cash) & (trailing_cash > 0) & np.isfinite(price) & (price > 0)
        result[positions[eligible]] = trailing_cash[eligible] / price[eligible]
    return result


def load_corporate_actions(repository, start: date, end: date, symbols) -> list[CorporateAction]:
    frame = repository.read_table("corporate_actions")
    if frame.empty:
        return []
    required = {"symbol", "ex_date", "cash_per_share", "share_multiplier"}
    if not required.issubset(frame.columns):
        raise ValueError(
            f"corporate_actions missing fields: {sorted(required - set(frame.columns))}"
        )
    frame = frame.copy()
    frame["ex_date"] = pd.to_datetime(frame["ex_date"], errors="raise").dt.date
    if frame["ex_date"].isna().any():
        raise ValueError("corporate_actions contains missing ex_date")
    frame = frame[frame["ex_date"].between(start, end)]
    if symbols:
        frame = frame[frame["symbol"].isin(symbols)]
    if frame.duplicated(["symbol", "ex_date"]).any():
        raise ValueError(
            "Combine cash/share entitlements into one corporate action per symbol/date"
        )
    actions = []
    for row in frame.sort_values(["ex_date", "symbol"]).to_dict("records"):
        dates = {}
        for key in ("pay_date", "share_listing_date"):
            value = row.get(key)
            dates[key] = pd.Timestamp(value).date() if pd.notna(value) else None
        actions.append(
            CorporateAction(
                symbol=str(row["symbol"]),
                ex_date=row["ex_date"],
                cash_per_share=float(row["cash_per_share"]),
                share_multiplier=float(row["share_multiplier"]),
                **dates,
            )
        )
    return actions
