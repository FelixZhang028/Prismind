"""Long-only allocation from trailing returns, plus explicit turnover budgets."""

from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from quant_platform.factors.base import pivot_field
from quant_platform.portfolio.equal_weight import EqualWeightPortfolio
from quant_platform.portfolio.models import TargetPosition

# Grinold-Kahn 风格缩放系数：把横截面标准化的信号分数映射到日度预期收益量级。
SIGNAL_ALPHA_SCALE = 0.05


def _shrunk_covariance(returns: pd.DataFrame) -> np.ndarray:
    """Ledoit-Wolf 风格对角收缩协方差，避免股票数接近或超过样本天数时矩阵病态。"""

    matrix = returns.to_numpy(dtype=float)
    n_obs, n_assets = matrix.shape
    sample = returns.cov().to_numpy(dtype=float)
    if n_assets <= 1 or n_obs <= 1:
        return sample + np.eye(n_assets) * 1e-8
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    target = np.diag(np.diag(sample))
    diff = sample - target
    gamma = float(np.sum(diff * diff))
    if gamma <= 1e-16:
        return sample + np.eye(n_assets) * 1e-8
    # 逐日样本外积与样本协方差的均方离差估计收缩强度。
    phi = 0.0
    for row in centered:
        outer = np.outer(row, row) - sample
        phi += float(np.sum(outer * outer))
    phi /= n_obs * n_obs
    shrinkage = float(np.clip(phi / gamma, 0.0, 1.0))
    shrunk = (1.0 - shrinkage) * sample + shrinkage * target
    return shrunk + np.eye(n_assets) * 1e-8


def _signal_expected_returns(signals, names: list[str], volatility: np.ndarray) -> np.ndarray:
    """把策略信号分数转成与资产波动率同量级的预期收益向量；无区分度时退化为全零（最小方差）。"""

    score_map = {signal.symbol: float(signal.score) for signal in signals}
    scores = np.array([score_map.get(name, float("nan")) for name in names], dtype=float)
    finite = np.isfinite(scores)
    if finite.sum() < 2:
        return np.zeros(len(names), dtype=float)
    valid = scores[finite]
    std = float(np.std(valid))
    if std <= 1e-12:
        return np.zeros(len(names), dtype=float)
    z = np.zeros(len(names), dtype=float)
    z[finite] = (valid - float(np.mean(valid))) / std
    return z * volatility * SIGNAL_ALPHA_SCALE


class RiskWeightedPortfolio(EqualWeightPortfolio):
    def __init__(self, top_n: int, method: str, lookback: int = 60) -> None:
        super().__init__(top_n)
        if method not in {"inverse_volatility", "risk_parity", "mean_variance"}:
            raise ValueError("未知组合权重方法")
        self.method = method
        self.lookback = lookback

    def construct_with_history(
        self,
        signals,
        history,
        *,
        held_symbols: set[str] | None = None,
        hold_buffer: int | None = None,
    ):
        targets = super().construct(signals, held_symbols=held_symbols, hold_buffer=hold_buffer)
        if not targets or any(signal.target_weight is not None for signal in signals):
            return targets
        names = [target.symbol for target in targets]
        cutoff = min(target.signal_date for target in targets)
        history = history[pd.to_datetime(history.trade_date) <= pd.Timestamp(cutoff)]
        close = pivot_field(history, "adjusted_close").reindex(columns=names)
        returns = close.tail(self.lookback + 1).pct_change(fill_method=None).dropna()
        if len(returns) < 20:
            raise ValueError("风险组合需要至少20个完整收益观测，请增加预热或补齐行情")
        covariance = _shrunk_covariance(returns)
        vol = np.sqrt(np.diag(covariance))
        initial = 1 / vol
        initial /= initial.sum()
        if self.method == "inverse_volatility":
            weights = initial
        else:
            expected_returns = _signal_expected_returns(signals, names, vol)

            def objective(w):
                variance = w @ covariance @ w
                if self.method == "risk_parity":
                    contribution = w * (covariance @ w) / variance
                    return float(np.sum((contribution - 1 / len(w)) ** 2))
                return float(5 * variance - w @ expected_returns)

            solution = minimize(
                objective,
                initial,
                method="SLSQP",
                bounds=[(0, 1)] * len(names),
                constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                options={"ftol": 1e-12, "maxiter": 1000},
            )
            if not solution.success:
                raise ValueError(f"组合优化失败：{solution.message}")
            weights = np.maximum(solution.x, 0)
            weights /= weights.sum()
        return [
            replace(target, target_weight=float(w))
            for target, w in zip(targets, weights, strict=True)
            if w > 1e-12
        ]


def constrain_turnover(
    targets: list[TargetPosition],
    current: dict[str, float],
    budget: float,
    *,
    reference: TargetPosition | None = None,
) -> list[TargetPosition]:
    """Limit sum(abs(delta stock weights)); a full cash-to-stock buy is 1.0."""
    desired = {target.symbol: target.target_weight for target in targets}
    names = sorted(set(current) | set(desired))
    turnover = sum(abs(desired.get(n, 0) - current.get(n, 0)) for n in names)
    if turnover <= budget:
        return targets
    scale = budget / turnover
    reference = targets[0] if targets else reference
    if reference is None:
        raise ValueError("限制清仓换手需要策略和信号日期")
    return [
        replace(reference, symbol=name, target_weight=weight)
        for name in names
        if (weight := current.get(name, 0) + scale * (desired.get(name, 0) - current.get(name, 0)))
        > 1e-12
    ]
