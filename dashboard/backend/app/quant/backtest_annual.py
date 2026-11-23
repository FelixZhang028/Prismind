"""Per-year return, drawdown, benchmark comparison, and turnover breakdown for one backtest."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.application.benchmarks import BENCHMARK_NAMES

TRADING_DAYS_PER_YEAR = 252.0


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 2) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _read_parquet(directory: Path | None, name: str) -> pd.DataFrame:
    if directory is None:
        return pd.DataFrame()
    path = directory / f"{name}.parquet"
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        return pd.DataFrame()


def _read_summary(directory: Path | None) -> dict[str, Any]:
    if directory is None:
        return {}
    path = directory / "summary.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_nav(directory: Path | None, result: dict[str, Any]) -> pd.DataFrame:
    frame = _read_parquet(directory, "nav")
    if not frame.empty and {"trade_date", "equity"} <= set(frame.columns):
        cols = ["trade_date", "equity"]
        if "benchmark_equity" in frame.columns:
            cols.append("benchmark_equity")
        nav = frame[cols].copy()
    else:
        dates = result.get("nav_dates") or []
        equity = result.get("equity") or []
        if not dates or len(dates) != len(equity):
            return pd.DataFrame()
        nav = pd.DataFrame({"trade_date": dates, "equity": equity})
    nav["trade_date"] = pd.to_datetime(nav["trade_date"], errors="coerce").dt.normalize()
    nav["equity"] = pd.to_numeric(nav["equity"], errors="coerce")
    if "benchmark_equity" in nav.columns:
        nav["benchmark_equity"] = pd.to_numeric(nav["benchmark_equity"], errors="coerce")
    nav = nav.dropna(subset=["trade_date", "equity"]).sort_values("trade_date")
    nav = nav[nav["equity"] > 0].drop_duplicates(subset=["trade_date"], keep="last")
    return nav.reset_index(drop=True)


def _load_fills(directory: Path | None, result: dict[str, Any]) -> pd.DataFrame:
    frame = _read_parquet(directory, "fills")
    if not frame.empty and {"trade_date", "price", "quantity"} <= set(frame.columns):
        fills = frame[["trade_date", "price", "quantity"]].copy()
        fills["trade_date"] = pd.to_datetime(fills["trade_date"], errors="coerce").dt.normalize()
        fills["notional"] = (
            pd.to_numeric(fills["price"], errors="coerce").abs()
            * pd.to_numeric(fills["quantity"], errors="coerce").abs()
        )
        return fills.dropna(subset=["trade_date", "notional"])

    trades = result.get("trades") or []
    if not trades:
        return pd.DataFrame(columns=["trade_date", "notional"])
    rows = []
    for item in trades:
        day = pd.to_datetime(item.get("date"), errors="coerce")
        amount = _finite(item.get("amount"))
        if amount is None:
            price = _finite(item.get("price"))
            qty = _finite(item.get("quantity"))
            amount = abs(price * qty) if price is not None and qty is not None else None
        if pd.notna(day) and amount is not None:
            rows.append({"trade_date": day.normalize(), "notional": abs(amount)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["trade_date", "notional"])


def _attach_benchmark_series(
    nav: pd.DataFrame,
    summary: dict[str, Any],
    benchmark_bars: pd.DataFrame | None,
    benchmark_symbol: str | None,
) -> tuple[pd.Series | None, str | None]:
    symbol = benchmark_symbol or str(summary.get("benchmark_symbol") or "") or None
    if "benchmark_equity" in nav.columns and nav["benchmark_equity"].notna().sum() >= 2:
        name = BENCHMARK_NAMES.get(symbol or "", symbol or "基准指数")
        return nav["benchmark_equity"], name
    if benchmark_bars is None or benchmark_bars.empty or not {"symbol", "trade_date", "raw_close"} <= set(benchmark_bars.columns):
        return None, None
    target = symbol or "000300.SH"
    sub = benchmark_bars[benchmark_bars["symbol"].astype(str) == target][["trade_date", "raw_close"]].copy()
    if sub.empty:
        return None, None
    sub["trade_date"] = pd.to_datetime(sub["trade_date"], errors="coerce").dt.normalize()
    sub["raw_close"] = pd.to_numeric(sub["raw_close"], errors="coerce")
    sub = sub.dropna().drop_duplicates(subset=["trade_date"], keep="last").sort_values("trade_date")
    merged = nav[["trade_date"]].merge(sub, on="trade_date", how="left")
    if merged["raw_close"].notna().sum() < 2:
        return None, None
    return merged["raw_close"], BENCHMARK_NAMES.get(target, target)


def _max_drawdown_pct(series: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for val in series:
        if val > peak:
            peak = val
        elif peak > 0:
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
    return round(max_dd * 100.0, 2)


def backtest_annual_breakdown(
    directory: Path | None,
    result: dict[str, Any],
    *,
    benchmark_bars: pd.DataFrame | None = None,
    benchmark_symbol: str | None = None,
) -> dict[str, Any] | None:
    """Compute per-year return, benchmark comparison, max drawdown, and single-side turnover."""
    nav = _load_nav(directory, result)
    if nav.empty:
        return None
    summary = _read_summary(directory)
    fills = _load_fills(directory, result)
    bench_series, bench_name = _attach_benchmark_series(nav, summary, benchmark_bars, benchmark_symbol)

    nav = nav.copy()
    nav["year"] = nav["trade_date"].dt.year
    if bench_series is not None:
        nav["bench"] = bench_series.to_numpy()
    if not fills.empty:
        fills = fills.copy()
        fills["year"] = fills["trade_date"].dt.year

    # 全区间换手率：优先取引擎 summary.json，历史旧记录缺失时用 fills + nav 实时估算。
    raw_period_to = _finite(summary.get("portfolio_turnover"))
    raw_ann_to = _finite(summary.get("annualized_turnover"))
    avg_equity_all = float(nav["equity"].mean()) if not nav.empty else 0.0
    periods_all = max(len(nav) - 1, 1)
    if raw_period_to is None and avg_equity_all > 0:
        total_notional = float(fills["notional"].sum()) if not fills.empty else 0.0
        raw_period_to = total_notional / (2.0 * avg_equity_all)
    if raw_ann_to is None and raw_period_to is not None:
        raw_ann_to = raw_period_to * TRADING_DAYS_PER_YEAR / periods_all

    rows: list[dict[str, Any]] = []
    prev_equity: float | None = None
    prev_bench: float | None = None
    for year, group in nav.groupby("year", sort=True):
        equities = group["equity"].tolist()
        start_base = prev_equity if prev_equity is not None else equities[0]
        end_equity = equities[-1]
        ret_pct = round((end_equity / start_base - 1.0) * 100.0, 2) if start_base > 0 else None
        dd_series = ([start_base] + equities) if prev_equity is not None else equities
        dd_pct = _max_drawdown_pct(dd_series)

        year_fills = fills[fills["year"] == year] if not fills.empty else pd.DataFrame()
        fill_count = int(len(year_fills))
        avg_equity = float(group["equity"].mean())
        notional = float(year_fills["notional"].sum()) if fill_count else 0.0
        turnover_pct = round((notional / (2.0 * avg_equity)) * 100.0, 2) if avg_equity > 0 else 0.0

        bench_ret_pct: float | None = None
        excess_pct: float | None = None
        if "bench" in group.columns:
            valid_bench = group["bench"].dropna()
            if not valid_bench.empty:
                b_start = prev_bench if prev_bench is not None else float(valid_bench.iloc[0])
                b_end = float(valid_bench.iloc[-1])
                if b_start > 0:
                    bench_ret_pct = round((b_end / b_start - 1.0) * 100.0, 2)
                    if ret_pct is not None:
                        excess_pct = round(ret_pct - bench_ret_pct, 2)
                prev_bench = b_end

        prev_equity = end_equity
        rows.append({
            "year": int(year),
            "trading_days": int(len(group)),
            "start_date": group["trade_date"].iloc[0].date().isoformat(),
            "end_date": group["trade_date"].iloc[-1].date().isoformat(),
            "return_pct": ret_pct,
            "benchmark_return_pct": bench_ret_pct,
            "excess_return_pct": excess_pct,
            "max_drawdown_pct": dd_pct,
            "turnover_pct": turnover_pct,
            "fills": fill_count,
        })

    return {
        "annualized_turnover": _round(raw_ann_to * 100.0) if raw_ann_to is not None else None,
        "portfolio_turnover": _round(raw_period_to * 100.0) if raw_period_to is not None else None,
        "benchmark_name": bench_name,
        "rows": rows,
    }
