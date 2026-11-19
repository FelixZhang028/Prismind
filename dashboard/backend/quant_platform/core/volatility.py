"""Annualized volatility of a stock's observed adjusted closes."""

from math import sqrt

import pandas as pd

ANNUALIZATION_SESSIONS = 244
_ANNUALIZER = sqrt(ANNUALIZATION_SESSIONS)


def _daily_returns(close: pd.Series) -> pd.Series:
    return close.pct_change(fill_method=None)


def latest_annualized_volatility(observed_close: pd.Series, window: int) -> float:
    """Calculate only the latest value from nonmissing closes in rule evaluation."""
    if len(observed_close) <= window:
        return float("nan")
    return float(_daily_returns(observed_close.tail(window + 1)).std() * _ANNUALIZER)


def annualized_volatility(close: pd.Series, window: int) -> pd.Series:
    """Sample standard deviation of the last N returns, annualized over 244 sessions."""
    returns = _daily_returns(close.dropna())
    volatility = returns.rolling(window, min_periods=2).std()
    infinite = returns.abs().eq(float("inf"))
    if infinite.any():
        volatility = volatility.mask(infinite.rolling(window, min_periods=1).max().astype(bool))
    return (volatility * _ANNUALIZER).iloc[window:]
