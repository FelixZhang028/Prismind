"""Daily A-share market breadth, sentiment, limit-move ecology, and objective market anomalies.

Computed purely from local end-of-day bars, benchmark indices, and CSRC industry classifications:
no Level-2 feed, no intraday stream, and no stock recommendations. Every anomaly rule is
transparent and paired with full-history forward statistics so researchers can verify how the
broad market behaved after similar sessions in the past.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from quant_platform.ai_research.facts import industry_name
from quant_platform.data.industry import EXPOSURES_TABLE, industry_on

SENTIMENT_COLUMNS = [
    "trade_date",
    "total",
    "up",
    "down",
    "flat",
    "suspended",
    "up_ratio",
    "median_ret",
    "amount",
    "limit_up",
    "limit_down",
    "burst_count",
    "burst_rate",
    "max_streak",
    "prev_limit_up_ret",
    "promotion_rate",
    "above_ma20_ratio",
    "above_ma60_ratio",
]

NEEDED_BAR_COLUMNS = [
    "symbol",
    "trade_date",
    "raw_high",
    "raw_close",
    "pre_close",
    "adjusted_close",
    "amount",
    "is_suspended",
    "is_st",
    "up_limit",
    "down_limit",
]

LOOKBACK_CALENDAR_DAYS = 130
MIN_INDUSTRY_STOCKS = 5
RECENT_ANOMALY_DAYS = 10
MAX_RECENT_ANOMALIES = 12
LIMIT_TOLERANCE = 1e-4

BENCHMARK_MAP = {
    "000300.SH": "hs300_ret",
    "000905.SH": "zz500_ret",
    "399006.SZ": "cyb_ret",
}


def _finite(value: Any, digits: int | None = None) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return round(num, digits) if digits is not None else num


def _rolling_percentile(series: pd.Series, window: int = 250, min_periods: int = 20) -> pd.Series:
    """For each day, fraction of values in the trailing window strictly below or equal to today."""
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for idx in range(len(values)):
        cur = values[idx]
        if not math.isfinite(cur):
            continue
        start = max(0, idx - window + 1)
        chunk = values[start : idx + 1]
        valid = chunk[np.isfinite(chunk)]
        if len(valid) < min_periods:
            continue
        out[idx] = float(np.mean(valid <= cur))
    return pd.Series(out, index=series.index)


def _compute_chunk_daily(
    bars: pd.DataFrame,
    *,
    emit_from: pd.Timestamp,
    prev_up_limits: set[str],
    streaks: dict[str, int],
) -> tuple[list[dict[str, Any]], set[str], dict[str, int]]:
    """Aggregate daily sentiment metrics for trade dates >= emit_from within a bar chunk."""
    if bars.empty:
        return [], prev_up_limits, streaks

    frame = bars.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values(["symbol", "trade_date"]).drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )

    close_col = "adjusted_close" if "adjusted_close" in frame.columns else "raw_close"
    adj_close = pd.to_numeric(frame[close_col], errors="coerce")
    frame["_adj"] = adj_close
    grouped_adj = frame.groupby("symbol", sort=False)["_adj"]
    frame["_ma20"] = grouped_adj.transform(lambda s: s.rolling(20, min_periods=20).mean())
    frame["_ma60"] = grouped_adj.transform(lambda s: s.rolling(60, min_periods=60).mean())

    raw_close = pd.to_numeric(frame["raw_close"], errors="coerce")
    raw_high = pd.to_numeric(frame["raw_high"], errors="coerce") if "raw_high" in frame.columns else raw_close
    pre_close = pd.to_numeric(frame["pre_close"], errors="coerce") if "pre_close" in frame.columns else pd.Series(np.nan, index=frame.index)
    amount = pd.to_numeric(frame["amount"], errors="coerce") if "amount" in frame.columns else pd.Series(0.0, index=frame.index)
    up_limit = pd.to_numeric(frame["up_limit"], errors="coerce") if "up_limit" in frame.columns else pd.Series(np.nan, index=frame.index)
    down_limit = pd.to_numeric(frame["down_limit"], errors="coerce") if "down_limit" in frame.columns else pd.Series(np.nan, index=frame.index)

    if "is_suspended" in frame.columns:
        is_susp = frame["is_suspended"].astype("boolean").fillna(False).astype(bool)
    else:
        is_susp = pd.Series(False, index=frame.index)

    valid_pre = pre_close.where(pre_close > 0)
    ret_1d = raw_close / valid_pre - 1.0
    frame["_ret_1d"] = ret_1d
    frame["_amount"] = amount.fillna(0.0)
    frame["_susp"] = is_susp
    frame["_at_up"] = (~is_susp) & up_limit.notna() & (raw_close >= up_limit - LIMIT_TOLERANCE)
    frame["_at_down"] = (~is_susp) & down_limit.notna() & (raw_close <= down_limit + LIMIT_TOLERANCE)
    frame["_touched_up"] = (~is_susp) & up_limit.notna() & (raw_high >= up_limit - LIMIT_TOLERANCE)
    frame["_above_ma20"] = frame["_adj"].notna() & frame["_ma20"].notna() & (frame["_adj"] > frame["_ma20"])
    frame["_has_ma20"] = frame["_adj"].notna() & frame["_ma20"].notna()
    frame["_above_ma60"] = frame["_adj"].notna() & frame["_ma60"].notna() & (frame["_adj"] > frame["_ma60"])
    frame["_has_ma60"] = frame["_adj"].notna() & frame["_ma60"].notna()

    # Walk dates starting slightly before emit_from so streaks & prev_up_limits warm up cleanly
    # when starting from scratch without an external state.
    rows: list[dict[str, Any]] = []
    for day, grp in frame.groupby("trade_date", sort=True):
        trading = grp[~grp["_susp"]]
        cur_up_symbols = set(trading.loc[trading["_at_up"], "symbol"].astype(str))
        new_streaks = {sym: streaks.get(sym, 0) + 1 for sym in cur_up_symbols}

        if day >= emit_from:
            total = int(len(trading))
            valid_ret = trading["_ret_1d"].dropna()
            up = int((valid_ret > 0).sum())
            down = int((valid_ret < 0).sum())
            flat = int((valid_ret == 0).sum())
            suspended = int(grp["_susp"].sum())
            up_ratio = float(up / total) if total > 0 else float("nan")
            median_ret = float(valid_ret.median()) if len(valid_ret) else float("nan")
            total_amount = float(trading["_amount"].sum())

            limit_up = len(cur_up_symbols)
            limit_down = int(trading["_at_down"].sum())
            burst_count = int((trading["_touched_up"] & ~trading["_at_up"]).sum())
            touched_total = limit_up + burst_count
            burst_rate = float(burst_count / touched_total) if touched_total > 0 else float("nan")
            max_streak = max(new_streaks.values()) if new_streaks else 0

            if prev_up_limits:
                prev_today = trading[trading["symbol"].astype(str).isin(prev_up_limits)]
                prev_rets = prev_today["_ret_1d"].dropna()
                prev_limit_up_ret = float(prev_rets.mean()) if len(prev_rets) else float("nan")
                promoted = int(prev_today["_at_up"].sum())
                promotion_rate = float(promoted / len(prev_up_limits))
            else:
                prev_limit_up_ret = float("nan")
                promotion_rate = float("nan")

            has_ma20 = int(trading["_has_ma20"].sum())
            has_ma60 = int(trading["_has_ma60"].sum())
            above_ma20_ratio = float(trading["_above_ma20"].sum() / has_ma20) if has_ma20 else float("nan")
            above_ma60_ratio = float(trading["_above_ma60"].sum() / has_ma60) if has_ma60 else float("nan")

            rows.append({
                "trade_date": day,
                "total": total,
                "up": up,
                "down": down,
                "flat": flat,
                "suspended": suspended,
                "up_ratio": up_ratio,
                "median_ret": median_ret,
                "amount": total_amount,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "burst_count": burst_count,
                "burst_rate": burst_rate,
                "max_streak": max_streak,
                "prev_limit_up_ret": prev_limit_up_ret,
                "promotion_rate": promotion_rate,
                "above_ma20_ratio": above_ma20_ratio,
                "above_ma60_ratio": above_ma60_ratio,
            })

        prev_up_limits = cur_up_symbols
        streaks = new_streaks

    return rows, prev_up_limits, streaks


def build_daily_sentiment_table(
    repository: Any,
    *,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute (or incrementally extend) the full daily market sentiment table year by year."""
    bounds = repository.daily_bar_bounds()
    if bounds is None:
        return pd.DataFrame(columns=SENTIMENT_COLUMNS)
    first_date, last_date = bounds

    base = pd.DataFrame(columns=SENTIMENT_COLUMNS)
    start_emit = first_date
    if existing is not None and not existing.empty and "trade_date" in existing.columns:
        base = existing.copy()
        base["trade_date"] = pd.to_datetime(base["trade_date"]).dt.normalize()
        base = base.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        cached_last = base["trade_date"].max().date()
        if cached_last >= last_date:
            return base.reset_index(drop=True)
        # Recompute from the day after cached_last (using lookback bars for MA60 & streaks).
        start_emit = cached_last + timedelta(days=1)

    all_rows: list[dict[str, Any]] = []
    prev_up_limits: set[str] = set()
    streaks: dict[str, int] = {}

    for year in range(start_emit.year, last_date.year + 1):
        chunk_emit_start = max(start_emit, date(year, 1, 1))
        chunk_end = min(last_date, date(year, 12, 31))
        if chunk_emit_start > chunk_end:
            continue
        load_start = max(first_date, chunk_emit_start - timedelta(days=LOOKBACK_CALENDAR_DAYS))
        bars = repository.get_daily_bars(start_date=load_start, end_date=chunk_end)
        if bars.empty:
            continue
        keep = [c for c in NEEDED_BAR_COLUMNS if c in bars.columns]
        chunk_rows, prev_up_limits, streaks = _compute_chunk_daily(
            bars[keep],
            emit_from=pd.Timestamp(chunk_emit_start),
            prev_up_limits=prev_up_limits,
            streaks=streaks,
        )
        all_rows.extend(chunk_rows)

    if not all_rows:
        return base.reset_index(drop=True)

    fresh = pd.DataFrame(all_rows, columns=SENTIMENT_COLUMNS)
    if base.empty:
        combined = fresh
    else:
        combined = pd.concat([base[SENTIMENT_COLUMNS], fresh], ignore_index=True)
    combined["trade_date"] = pd.to_datetime(combined["trade_date"]).dt.normalize()
    combined = combined.sort_values("trade_date").drop_duplicates("trade_date", keep="last").reset_index(drop=True)
    return combined


def _attach_derived_and_benchmarks(daily: pd.DataFrame, repository: Any) -> pd.DataFrame:
    """Attach rolling ratios, 250-day percentiles, and benchmark index daily returns."""
    if daily.empty:
        return daily.copy()

    frame = daily.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values("trade_date").reset_index(drop=True)

    amount = pd.to_numeric(frame["amount"], errors="coerce")
    amount_ma20 = amount.shift(1).rolling(20, min_periods=5).mean()
    frame["amount_ma20"] = amount_ma20
    frame["amount_ratio_20"] = amount / amount_ma20.where(amount_ma20 > 0)
    frame["amount_delta_1d"] = amount - amount.shift(1)
    frame["amount_pct_250"] = _rolling_percentile(amount, 250, min_periods=20)
    frame["up_ratio_pct_250"] = _rolling_percentile(frame["up_ratio"], 250, min_periods=20)
    frame["burst_rate_pct_250"] = _rolling_percentile(frame["burst_rate"], 250, min_periods=20)

    for col in BENCHMARK_MAP.values():
        frame[col] = np.nan

    bm = repository.read_table("benchmark_bars")
    if not bm.empty and {"symbol", "trade_date", "raw_close"} <= set(bm.columns):
        bm = bm[bm["symbol"].isin(BENCHMARK_MAP)].copy()
        bm["trade_date"] = pd.to_datetime(bm["trade_date"]).dt.normalize()
        for symbol, col in BENCHMARK_MAP.items():
            sub = bm[bm["symbol"] == symbol].sort_values("trade_date").drop_duplicates("trade_date", keep="last")
            closes = pd.to_numeric(sub["raw_close"], errors="coerce")
            if "pre_close" in sub.columns:
                prev = pd.to_numeric(sub["pre_close"], errors="coerce").where(lambda s: s > 0)
                ret = closes / prev.fillna(closes.shift(1)) - 1.0
            else:
                ret = closes.pct_change()
            mapped = pd.Series(ret.to_numpy(), index=sub["trade_date"]).to_dict()
            frame[col] = frame["trade_date"].map(mapped)

    frame["style_spread"] = pd.to_numeric(frame["median_ret"], errors="coerce") - pd.to_numeric(
        frame["hs300_ret"], errors="coerce"
    )
    return frame


def _forward_cumulative(ret_series: pd.Series, horizon: int) -> pd.Series:
    """Cumulative return over (t+1 .. t+horizon) for each signal day t."""
    vals = pd.to_numeric(ret_series, errors="coerce").to_numpy(dtype=float)
    n = len(vals)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n - horizon):
        seg = vals[i + 1 : i + 1 + horizon]
        if np.all(np.isfinite(seg)):
            out[i] = float(np.prod(1.0 + seg) - 1.0)
    return pd.Series(out, index=ret_series.index)


def _anomaly_rules(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Transparent, objective daily anomaly detectors (market-wide facts only)."""
    touched = pd.to_numeric(frame["limit_up"], errors="coerce").fillna(0) + pd.to_numeric(
        frame["burst_count"], errors="coerce"
    ).fillna(0)
    return [
        {
            "id": "vol_surge",
            "tag": "全市场放量",
            "tone": "amber",
            "mask": pd.to_numeric(frame["amount_ratio_20"], errors="coerce") >= 1.30,
            "title": lambda r: f"全市场成交额较 20 日均量放大 {(r['amount_ratio_20'] - 1) * 100:.0f}%",
            "detail": lambda r: (
                f"当日成交额 {r['amount'] / 1e12:.2f} 万亿（20 日均量 {r['amount_ma20'] / 1e12:.2f} 万亿），"
                f"同步伴随 {r['up_ratio'] * 100:.1f}% 个股上涨。"
            ),
            "note": "统计全市场成交额较 20 日均量放大 ≥ 30% 后，后续 1/5/20 个交易日表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "vol_shrink",
            "tag": "全市场地量",
            "tone": "slate",
            "mask": pd.to_numeric(frame["amount_ratio_20"], errors="coerce") <= 0.70,
            "title": lambda r: f"全市场成交额较 20 日均量萎缩 {(1 - r['amount_ratio_20']) * 100:.0f}%",
            "detail": lambda r: (
                f"当日成交额 {r['amount'] / 1e12:.2f} 万亿（20 日均量 {r['amount_ma20'] / 1e12:.2f} 万亿），"
                f"全市场中位数涨跌幅 {r['median_ret'] * 100:+.2f}%。"
            ),
            "note": "统计全市场成交额较 20 日均量萎缩 ≥ 30% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "breadth_surge",
            "tag": "全市场普涨",
            "tone": "rose",
            "mask": pd.to_numeric(frame["up_ratio"], errors="coerce") >= 0.85,
            "title": lambda r: f"全市场 {r['up_ratio'] * 100:.1f}% 个股上涨，进入普涨区间",
            "detail": lambda r: (
                f"上涨 {int(r['up']):,} 只 / 下跌 {int(r['down']):,} 只，"
                f"全市场中位数 {r['median_ret'] * 100:+.2f}%，涨停 {int(r['limit_up'])} 只。"
            ),
            "note": "统计单日上涨家数占比 ≥ 85% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "breadth_ice",
            "tag": "普跌冰点",
            "tone": "emerald",
            "mask": pd.to_numeric(frame["up_ratio"], errors="coerce") <= 0.15,
            "title": lambda r: f"全市场仅 {r['up_ratio'] * 100:.1f}% 个股上涨，跌停 {int(r['limit_down'])} 只",
            "detail": lambda r: (
                f"上涨 {int(r['up']):,} 只 / 下跌 {int(r['down']):,} 只，"
                f"全市场中位数 {r['median_ret'] * 100:+.2f}%。"
            ),
            "note": "统计单日上涨家数占比 ≤ 15%（情绪冰点）后的历史后续表现；熊市阶段仍可能二次探底，仅供参考。",
        },
        {
            "id": "style_small_lead",
            "tag": "中小盘领涨",
            "tone": "indigo",
            "mask": pd.to_numeric(frame["style_spread"], errors="coerce") >= 0.02,
            "title": lambda r: f"中小盘明显强于权重：中位数跑赢沪深 300 {r['style_spread'] * 100:+.2f}%",
            "detail": lambda r: (
                f"全市场中位数 {r['median_ret'] * 100:+.2f}%，沪深 300 {r['hs300_ret'] * 100:+.2f}%，"
                f"涨停 {int(r['limit_up'])} 只。"
            ),
            "note": "统计全市场中位数单日跑赢沪深 300 ≥ 2% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "style_large_lead",
            "tag": "权重分化",
            "tone": "indigo",
            "mask": pd.to_numeric(frame["style_spread"], errors="coerce") <= -0.02,
            "title": lambda r: f"权重显著强于个股：沪深 300 跑赢中位数 {abs(r['style_spread']) * 100:.2f}%",
            "detail": lambda r: (
                f"沪深 300 {r['hs300_ret'] * 100:+.2f}%，全市场中位数 {r['median_ret'] * 100:+.2f}%，"
                f"上涨家数占比 {r['up_ratio'] * 100:.1f}%。"
            ),
            "note": "统计沪深 300 单日跑赢全市场中位数 ≥ 2% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "high_burst",
            "tag": "高炸板率",
            "tone": "emerald",
            "mask": (pd.to_numeric(frame["burst_rate"], errors="coerce") >= 0.40) & (touched >= 30),
            "title": lambda r: f"涨停炸板率升至 {r['burst_rate'] * 100:.1f}%，短线承接承压",
            "detail": lambda r: (
                f"当日触及涨停 {int(r['limit_up']) + int(r['burst_count'])} 只，"
                f"收盘封板 {int(r['limit_up'])} 只、炸板 {int(r['burst_count'])} 只。"
            ),
            "note": "统计当日触及涨停 ≥ 30 只且炸板率 ≥ 40% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
        {
            "id": "index_jump",
            "tag": "宽基大波动",
            "tone": "rose",
            "mask": pd.to_numeric(frame["hs300_ret"], errors="coerce").abs() >= 0.025,
            "title": lambda r: f"沪深 300 单日{'大涨' if r['hs300_ret'] >= 0 else '大跌'} {r['hs300_ret'] * 100:+.2f}%",
            "detail": lambda r: (
                f"全市场成交额 {r['amount'] / 1e12:.2f} 万亿，"
                f"上涨 {int(r['up']):,} 只 / 下跌 {int(r['down']):,} 只。"
            ),
            "note": "统计沪深 300 单日涨跌幅绝对值 ≥ 2.5% 后的历史后续表现；仅供参考，不构成投资建议。",
        },
    ]


def _recent_anomalies_with_history(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    rules = _anomaly_rules(frame)
    horizons = (1, 5, 20)
    targets = [
        ("沪深 300", "hs300_ret"),
        ("中证 500", "zz500_ret"),
        ("全市场中位数", "median_ret"),
    ]
    forward_map = {
        col: {h: _forward_cumulative(frame[col], h) for h in horizons}
        for _, col in targets
    }
    span = f"{frame['trade_date'].iloc[0].date().isoformat()} 至 {frame['trade_date'].iloc[-1].date().isoformat()}"

    recent_start = max(0, len(frame) - RECENT_ANOMALY_DAYS)
    history_cache: dict[str, dict[str, Any]] = {}

    def rule_history(rule: dict[str, Any]) -> dict[str, Any]:
        rid = rule["id"]
        if rid in history_cache:
            return history_cache[rid]
        mask = rule["mask"].fillna(False)
        count = int(mask.sum())
        rows = []
        for label, col in targets:
            entry: dict[str, Any] = {"target": label}
            for h in horizons:
                vals = forward_map[col][h][mask].dropna()
                entry[f"mean_{h}d"] = _finite(vals.mean(), 4) if len(vals) else None
                entry[f"win_{h}d"] = _finite((vals > 0).mean(), 4) if len(vals) else None
                entry[f"n_{h}d"] = int(len(vals))
            rows.append(entry)
        history_cache[rid] = {"count": count, "span": span, "rows": rows, "note": rule["note"]}
        return history_cache[rid]

    events: list[dict[str, Any]] = []
    for idx in range(len(frame) - 1, recent_start - 1, -1):
        row = frame.iloc[idx]
        day_str = row["trade_date"].date().isoformat()
        for rule in rules:
            if not bool(rule["mask"].iloc[idx]):
                continue
            tone = rule["tone"]
            if rule["id"] == "index_jump":
                tone = "rose" if float(row["hs300_ret"]) >= 0 else "emerald"
            events.append({
                "id": f"{rule['id']}-{day_str}",
                "rule_id": rule["id"],
                "date": day_str,
                "tag": rule["tag"],
                "tone": tone,
                "title": rule["title"](row),
                "detail": rule["detail"](row),
                "history": rule_history(rule),
            })
            if len(events) >= MAX_RECENT_ANOMALIES:
                return events
    return events


def industry_sentiment(repository: Any) -> list[dict[str, Any]]:
    """Latest day's CSRC industry returns, volume ratio vs prior 20 sessions, and limit counts."""
    bounds = repository.daily_bar_bounds()
    if bounds is None:
        return []
    newest = bounds[1]
    changes = repository.read_table(EXPOSURES_TABLE)
    if changes.empty or "industry" not in changes.columns:
        return []

    window = repository.get_daily_bars(start_date=newest - timedelta(days=45), end_date=newest)
    if window.empty:
        return []
    window = window.copy()
    window["trade_date"] = pd.to_datetime(window["trade_date"]).dt.normalize()
    latest_ts = window["trade_date"].max()

    is_susp = (
        window["is_suspended"].astype("boolean").fillna(False).astype(bool)
        if "is_suspended" in window.columns
        else pd.Series(False, index=window.index)
    )
    is_st = (
        window["is_st"].astype("boolean").fillna(False).astype(bool)
        if "is_st" in window.columns
        else pd.Series(False, index=window.index)
    )
    active = window[~is_susp & ~is_st].copy()
    if active.empty:
        return []

    # Map each symbol's industry as of latest_ts (fast: one lookup per unique symbol).
    unique_syms = pd.DataFrame({"symbol": active["symbol"].unique(), "date": latest_ts})
    sym_ind = dict(
        zip(
            unique_syms["symbol"],
            industry_on(unique_syms, changes, infer_early=True).map(industry_name),
            strict=True,
        )
    )
    active["industry"] = active["symbol"].map(sym_ind).fillna("")
    active = active[active["industry"].astype(bool)]
    if active.empty:
        return []

    active["_amount"] = pd.to_numeric(active["amount"], errors="coerce").fillna(0.0)
    daily_ind_amt = active.groupby(["trade_date", "industry"], observed=True)["_amount"].sum().unstack(fill_value=0.0).sort_index()
    prior_amt = daily_ind_amt.loc[daily_ind_amt.index < latest_ts].tail(20)
    avg_20d = prior_amt.mean(axis=0) if not prior_amt.empty else pd.Series(dtype=float)

    today = active[active["trade_date"] == latest_ts].copy()
    if today.empty:
        return []
    raw_close = pd.to_numeric(today["raw_close"], errors="coerce")
    pre_close = pd.to_numeric(today["pre_close"], errors="coerce").where(lambda s: s > 0)
    up_limit = pd.to_numeric(today["up_limit"], errors="coerce") if "up_limit" in today.columns else pd.Series(np.nan, index=today.index)
    down_limit = pd.to_numeric(today["down_limit"], errors="coerce") if "down_limit" in today.columns else pd.Series(np.nan, index=today.index)
    today["_ret"] = raw_close / pre_close - 1.0
    today["_up"] = today["_ret"] > 0
    today["_at_up"] = up_limit.notna() & (raw_close >= up_limit - LIMIT_TOLERANCE)
    today["_at_down"] = down_limit.notna() & (raw_close <= down_limit + LIMIT_TOLERANCE)

    market_amount = float(today["_amount"].sum())
    rows: list[dict[str, Any]] = []
    for ind, grp in today.groupby("industry", observed=True):
        count = int(len(grp))
        if count < MIN_INDUSTRY_STOCKS:
            continue
        ind_amt = float(grp["_amount"].sum())
        base_amt = float(avg_20d.get(ind, np.nan)) if ind in avg_20d.index else float("nan")
        vol_ratio = ind_amt / base_amt if math.isfinite(base_amt) and base_amt > 0 else None
        rows.append({
            "name": str(ind),
            "count": count,
            "change": _finite(grp["_ret"].mean(), 4),
            "amount": _finite(ind_amt, 0),
            "amount_share": _finite(ind_amt / market_amount, 4) if market_amount > 0 else None,
            "vol_ratio_20": _finite(vol_ratio, 3),
            "limit_up": int(grp["_at_up"].sum()),
            "limit_down": int(grp["_at_down"].sum()),
            "up_ratio": _finite(grp["_up"].mean(), 4),
        })
    rows.sort(key=lambda r: (r["vol_ratio_20"] is not None, r["vol_ratio_20"] or 0.0, r["change"] or 0.0), reverse=True)
    return rows


def build_sentiment_payload(
    daily_table: pd.DataFrame,
    repository: Any,
    *,
    window: int = 60,
    industries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the complete JSON payload for the Market Sentiment page."""
    if daily_table.empty:
        return {
            "latest": None,
            "anomalies": [],
            "series": [],
            "industries": [],
            "history_span": None,
        }

    frame = _attach_derived_and_benchmarks(daily_table, repository)
    anomalies = _recent_anomalies_with_history(frame)
    last = frame.iloc[-1]
    prev5 = frame.iloc[-6] if len(frame) >= 6 else None

    latest = {
        "day": last["trade_date"].date().isoformat(),
        "total": int(last["total"]),
        "up": int(last["up"]),
        "down": int(last["down"]),
        "flat": int(last["flat"]),
        "suspended": int(last["suspended"]),
        "up_ratio": _finite(last["up_ratio"], 4),
        "up_ratio_pct_250": _finite(last["up_ratio_pct_250"], 4),
        "median_ret": _finite(last["median_ret"], 4),
        "hs300_ret": _finite(last["hs300_ret"], 4),
        "zz500_ret": _finite(last["zz500_ret"], 4),
        "style_spread": _finite(last["style_spread"], 4),
        "amount": _finite(last["amount"], 0),
        "amount_ma20": _finite(last["amount_ma20"], 0),
        "amount_delta_1d": _finite(last["amount_delta_1d"], 0),
        "amount_ratio_20": _finite(last["amount_ratio_20"], 3),
        "amount_pct_250": _finite(last["amount_pct_250"], 4),
        "limit_up": int(last["limit_up"]),
        "limit_down": int(last["limit_down"]),
        "burst_count": int(last["burst_count"]),
        "burst_rate": _finite(last["burst_rate"], 4),
        "burst_rate_pct_250": _finite(last["burst_rate_pct_250"], 4),
        "max_streak": int(last["max_streak"]),
        "prev_limit_up_ret": _finite(last["prev_limit_up_ret"], 4),
        "promotion_rate": _finite(last["promotion_rate"], 4),
        "above_ma20_ratio": _finite(last["above_ma20_ratio"], 4),
        "above_ma60_ratio": _finite(last["above_ma60_ratio"], 4),
        "above_ma60_prev5": _finite(prev5["above_ma60_ratio"], 4) if prev5 is not None else None,
        "today_anomalies": [
            {"id": a["id"], "rule_id": a["rule_id"], "tag": a["tag"], "tone": a["tone"], "title": a["title"]}
            for a in anomalies
            if a["date"] == last["trade_date"].date().isoformat()
        ],
    }

    sliced = frame.tail(max(1, int(window))).copy()
    # Cumulative style curves rebased to 0 at start of selected window.
    for col, out_col in (
        ("hs300_ret", "hs300_cum"),
        ("zz500_ret", "zz500_cum"),
        ("median_ret", "median_cum"),
    ):
        rets = pd.to_numeric(sliced[col], errors="coerce").fillna(0.0)
        cum = (1.0 + rets).cumprod() - 1.0
        # Rebase first point to 0.0 so all three lines start cleanly together.
        first_factor = 1.0 + float(rets.iloc[0])
        if first_factor > 0:
            cum = (1.0 + cum) / first_factor - 1.0
        sliced[out_col] = cum

    series = [
        {
            "date": row["trade_date"].date().isoformat(),
            "up_ratio": _finite(row["up_ratio"], 4),
            "amount": _finite(row["amount"], 0),
            "amount_ratio_20": _finite(row["amount_ratio_20"], 3),
            "limit_up": int(row["limit_up"]),
            "limit_down": int(row["limit_down"]),
            "burst_rate": _finite(row["burst_rate"], 4),
            "prev_limit_up_ret": _finite(row["prev_limit_up_ret"], 4),
            "above_ma20_ratio": _finite(row["above_ma20_ratio"], 4),
            "above_ma60_ratio": _finite(row["above_ma60_ratio"], 4),
            "hs300_cum": _finite(row["hs300_cum"], 4),
            "zz500_cum": _finite(row["zz500_cum"], 4),
            "median_cum": _finite(row["median_cum"], 4),
        }
        for _, row in sliced.iterrows()
    ]

    return {
        "latest": latest,
        "anomalies": anomalies,
        "series": series,
        "industries": industries if industries is not None else industry_sentiment(repository),
        "history_span": {
            "start": frame["trade_date"].iloc[0].date().isoformat(),
            "end": frame["trade_date"].iloc[-1].date().isoformat(),
            "total_days": int(len(frame)),
        },
    }


def home_sentiment_summary(daily_table: pd.DataFrame, repository: Any) -> dict[str, Any] | None:
    """Compact one-line sentiment & anomaly summary for the workspace home page."""
    if daily_table.empty:
        return None
    frame = _attach_derived_and_benchmarks(daily_table, repository)
    last = frame.iloc[-1]
    day_str = last["trade_date"].date().isoformat()
    today_events = [
        {"id": a["id"], "rule_id": a["rule_id"], "tag": a["tag"], "tone": a["tone"], "title": a["title"]}
        for a in _recent_anomalies_with_history(frame)
        if a["date"] == day_str
    ]
    return {
        "day": day_str,
        "amount_ratio_20": _finite(last["amount_ratio_20"], 3),
        "burst_rate": _finite(last["burst_rate"], 4),
        "prev_limit_up_ret": _finite(last["prev_limit_up_ret"], 4),
        "above_ma20_ratio": _finite(last["above_ma20_ratio"], 4),
        "today_anomalies": today_events,
    }
