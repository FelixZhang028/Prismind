"""HAC mean inference, multiple-testing FDR correction, annual summaries, and point-in-time neutralization."""

from collections.abc import Sequence
from math import isfinite

import numpy as np
import pandas as pd
from scipy.stats import norm


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg FDR adjusted q-values preserving input order.

    Invalid / missing p-values are excluded from the test count ``m`` and map to ``None``.
    """
    valid: list[tuple[int, float]] = []
    for idx, raw in enumerate(p_values):
        if raw is None:
            continue
        try:
            p = float(raw)
        except (TypeError, ValueError):
            continue
        if isfinite(p) and 0.0 <= p <= 1.0:
            valid.append((idx, p))

    adjusted: list[float | None] = [None] * len(p_values)
    m = len(valid)
    if m == 0:
        return adjusted

    ordered = sorted(valid, key=lambda pair: pair[1])
    q_sorted = [0.0] * m
    running = 1.0
    for rank_idx in range(m - 1, -1, -1):
        _, p = ordered[rank_idx]
        rank = rank_idx + 1
        running = min(running, p * m / rank)
        q_sorted[rank_idx] = min(1.0, max(0.0, running))

    for (orig_idx, _), q in zip(ordered, q_sorted, strict=True):
        adjusted[orig_idx] = float(q)
    return adjusted


def fdr_verdict(q_value: float | None) -> str:
    """Plain-Chinese significance label for a BH-FDR adjusted q-value."""
    if q_value is None or not isfinite(float(q_value)):
        return "样本不足"
    q = float(q_value)
    if q < 0.05:
        return "通过 (FDR<5%)"
    if q < 0.10:
        return "边缘显著 (FDR<10%)"
    return "未通过 (可能偶然)"


def ic_statistics(values: pd.Series, lags: int) -> dict:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    result = {
        "observations": len(x),
        "rank_ic_mean": float(x.mean()),
        "hac_t": float("nan"),
        "hac_p": float("nan"),
    }
    result["rank_ic_ir"] = float(x.mean() / x.std()) if x.std() > 0 else float("nan")
    result["positive_ratio"] = float(x.gt(0).mean()) if len(x) else float("nan")
    if len(x) < max(20, lags + 2):
        return result
    residual = x.to_numpy() - x.mean()
    variance = float(residual @ residual / len(x))
    for lag in range(1, min(lags, len(x) - 1) + 1):
        variance += 2 * (1 - lag / (lags + 1)) * float(residual[lag:] @ residual[:-lag] / len(x))
    se = np.sqrt(max(variance, 0) / len(x))
    if se > 1e-15:
        result["hac_t"] = float(x.mean() / se)
        result["hac_p"] = float(2 * norm.sf(abs(result["hac_t"])))
    return result


def annual_ic(daily: pd.DataFrame, lags: int) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {"year": year, **ic_statistics(group.rank_ic, lags)}
            for year, group in daily.groupby(pd.to_datetime(daily.date).dt.year)
        ]
    )


def neutralize_exposures(values: pd.DataFrame, exposures: pd.DataFrame, mode: str) -> pd.DataFrame:
    """date denotes availability, not reporting-period end; never backward fill."""
    required = {"symbol", "date"}
    if mode in {"industry", "both"}:
        required.add("industry")
    if mode in {"size", "both"}:
        required.add("market_cap")
    if not required.issubset(exposures.columns) or exposures.empty:
        raise ValueError("中性化缺少历史暴露表 security_exposures：" + ", ".join(sorted(required)))
    left, right = values.copy(), exposures.copy()
    left["date"], right["date"] = pd.to_datetime(left.date), pd.to_datetime(right.date)
    if right.duplicated(["date", "symbol"]).any():
        raise ValueError("历史暴露表存在重复日期/股票")
    joined = pd.merge_asof(
        left.sort_values("date"),
        right.sort_values("date"),
        on="date",
        by="symbol",
        direction="backward",
    )
    outputs = []
    for _, group in joined.groupby("date"):
        features = pd.DataFrame({"intercept": 1.0}, index=group.index)
        if "industry" in required:
            if group.industry.isna().any():
                raise ValueError("部分因子样本缺少当时可得行业，不能静默跳过中性化")
            features = pd.concat(
                [features, pd.get_dummies(group.industry, drop_first=True)], axis=1
            )
        if "market_cap" in required:
            cap = pd.to_numeric(group.market_cap, errors="coerce")
            if cap.isna().any() or (cap <= 0).any() or not np.isfinite(cap).all():
                raise ValueError("部分样本缺少有效历史市值")
            features["log_size"] = np.log(cap)
        usable = group.value.notna() & np.isfinite(group.value)
        x = features.loc[usable].to_numpy(dtype=float)
        y = group.loc[usable, "value"].to_numpy(dtype=float)
        if len(y) < 3 or len(y) <= np.linalg.matrix_rank(x) + 1:
            continue
        group = group.loc[usable, ["date", "symbol", "value"]].copy()
        group["value"] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
        outputs.append(group)
    if not outputs:
        raise ValueError("中性化截面样本不足")
    return pd.concat(outputs, ignore_index=True)
