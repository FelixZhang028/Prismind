"""Safe generic strategy interpreter for versioned visual-builder definitions."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, ClassVar

import pandas as pd

from quant_platform.core.volatility import latest_annualized_volatility
from quant_platform.signals.models import Signal
from quant_platform.strategies.base import Strategy
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_schema import (
    FUNDAMENTAL_INDICATORS,
    QUANTILE_OPERATORS,
    IndicatorSpec,
    RuleSpec,
    RuleStrategyDefinition,
    indicator_direction,
    is_factor_indicator,
    resolve_factor,
)
from quant_platform.strategies.spec import ParameterKind, StrategyParameter

_NON_NUMERIC_COLUMNS = frozenset({
    "symbol",
    "trade_date",
    "industry",
    "sector",
    "quality_status",
    "is_st",
    "is_suspended",
})


@dataclass(frozen=True)
class UniverseEvaluation:
    """Cross-sectional evaluation result on a single trade date."""

    scores: dict[str, float]
    indicator_values: dict[IndicatorSpec, dict[str, float]]

@dataclass(frozen=True)
class RuleBasedParameters:
    definition: RuleStrategyDefinition


class RuleBasedStrategy(Strategy):
    """Evaluate approved indicators without executing user-supplied program code."""

    plugin_name = "rule_builder"
    display_name = "零代码规则策略"
    description = "由模板或积木编辑器生成，使用白名单指标和判断条件"
    parameters: ClassVar[tuple[StrategyParameter, ...]] = (
        StrategyParameter(
            "definition_json",
            "结构化策略规则",
            ParameterKind.STRING,
            "{}",
            "平台生成的版本化规则；普通用户无需直接编辑",
        ),
    )
    required_fields = frozenset({"symbol", "trade_date", "adjusted_close", "amount"})

    def __init__(self, strategy_id: str, parameters: RuleBasedParameters) -> None:
        self.strategy_id = strategy_id
        self.config = parameters

    @classmethod
    def from_parameters(
        cls, strategy_id: str, parameters: dict[str, Any]
    ) -> RuleBasedStrategy:
        definition = RuleStrategyDefinition.from_json(str(parameters["definition_json"]))
        return cls(strategy_id, RuleBasedParameters(definition))

    @property
    def data_fields(self) -> frozenset[str]:
        return self.config.definition.data_fields

    @property
    def min_history(self) -> int:
        return self.config.definition.minimum_history_days

    @property
    def hold_buffer(self) -> int:
        return self.config.definition.hold_buffer

    @property
    def market_timing(self):
        return self.config.definition.market_timing

    @property
    def exit_rules(self):
        return self.config.definition.exit_rules

    def generate_signals(self, context: StrategyContext) -> list[Signal]:
        context.require_fields(self.required_fields)
        definition = self.config.definition
        requested = {"adjusted_close", "amount"} | set(self.data_fields)
        optional = set(definition.optional_fields) & set(context.available_fields)
        fields = sorted(requested | optional)
        lookback = (
            definition.minimum_history_days + 1
            if definition.has_factor_indicators
            else definition.minimum_history_days
        )
        history = context.history(
            fields=fields,
            lookback=lookback,
        )
        if history.empty:
            return []
        numeric_fields = [col for col in fields if col in history.columns and col not in _NON_NUMERIC_COLUMNS]
        if numeric_fields:
            history[numeric_fields] = history[numeric_fields].apply(pd.to_numeric, errors="coerce")
        cutoff = pd.Timestamp(context.trade_date)
        evaluation = evaluate_universe(history, cutoff, definition)
        signals = [
            Signal(
                strategy_id=self.strategy_id,
                trade_date=context.trade_date,
                symbol=symbol,
                signal_type="RULE_BUILDER_SCORE",
                score=score,
                model_version=f"rule-schema-v{definition.schema_version}",
            )
            for symbol, score in evaluation.scores.items()
        ]
        return sorted(signals, key=lambda signal: (-signal.score, signal.symbol))


def _compare_values(operator: str, left: float | None, right: float | None) -> bool:
    if left is None or right is None or not isfinite(left) or not isfinite(right):
        return False
    if operator == "greater_than":
        return left > right
    if operator == "greater_or_equal":
        return left >= right
    if operator == "less_than":
        return left < right
    if operator == "less_or_equal":
        return left <= right
    return False


def _quantile_passing_symbols(
    rule: RuleSpec,
    symbol_values: dict[str, float],
) -> set[str]:
    if not symbol_values or rule.value is None:
        return set()
    series = pd.Series(symbol_values, dtype=float).replace([float("inf"), -float("inf")], float("nan")).dropna()
    if series.empty:
        return set()
    p = float(rule.value) / 100.0
    if rule.operator == "exclude_bottom_pct":
        ranks = series.rank(method="average", ascending=True, pct=True)
        return set(ranks[ranks > p].index)
    if rule.operator == "exclude_top_pct":
        ranks = series.rank(method="average", ascending=False, pct=True)
        return set(ranks[ranks > p].index)
    if rule.operator == "exclude_worst_pct":
        direction = indicator_direction(rule.left)
        ranks = series.rank(method="average", ascending=(direction >= 0), pct=True)
        return set(ranks[ranks > p].index)
    if rule.operator == "top_pct":
        ranks = series.rank(method="average", ascending=False, pct=True)
        return set(ranks[ranks <= p].index)
    if rule.operator == "bottom_pct":
        ranks = series.rank(method="average", ascending=True, pct=True)
        return set(ranks[ranks <= p].index)
    return set()


def evaluate_universe(
    history: pd.DataFrame,
    cutoff: pd.Timestamp,
    definition: RuleStrategyDefinition,
) -> UniverseEvaluation:
    """Evaluate all entry rules (including factor-library indicators & cross-sectional quantiles) on ``cutoff``."""

    if history.empty:
        return UniverseEvaluation(scores={}, indicator_values={})

    cutoff_norm = pd.Timestamp(cutoff).normalize()
    unique_indicators = list(dict.fromkeys(definition._indicators()))
    factor_indicators = [ind for ind in unique_indicators if is_factor_indicator(ind.name)]
    builtin_indicators = [ind for ind in unique_indicators if not is_factor_indicator(ind.name)]

    # 1. Active symbols that actually have a bar on ``cutoff``.
    active_groups: dict[str, pd.DataFrame] = {}
    for symbol, group in history.groupby("symbol", observed=True, sort=False):
        if group.empty or pd.Timestamp(group["trade_date"].iat[-1]).normalize() != cutoff_norm:
            continue
        active_groups[str(symbol)] = group
    if not active_groups:
        return UniverseEvaluation(scores={}, indicator_values={})
    active_symbols = set(active_groups)

    values_by_indicator: dict[IndicatorSpec, dict[str, float]] = {ind: {} for ind in unique_indicators}

    # 2. Compute factor-library indicators once across the entire cross-section.
    for ind in factor_indicators:
        factor = resolve_factor(ind)
        if factor is None:
            continue
        try:
            computed = factor.compute(history)
        except ValueError:
            continue
        if computed.empty or not {"date", "symbol", "value"} <= set(computed.columns):
            continue
        dates = pd.to_datetime(computed["date"], errors="coerce").dt.normalize()
        today = computed.loc[dates == cutoff_norm, ["symbol", "value"]]
        if today.empty:
            continue
        sym_map: dict[str, float] = {}
        for sym, raw_val in zip(today["symbol"], today["value"], strict=False):
            sym_str = str(sym)
            if sym_str not in active_symbols:
                continue
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                continue
            if isfinite(val):
                sym_map[sym_str] = val
        values_by_indicator[ind] = sym_map

    # 3. Compute built-in per-stock indicators.
    if builtin_indicators:
        for symbol, group in active_groups.items():
            for ind in builtin_indicators:
                val = _indicator_value(group, ind)
                if val is not None and isfinite(val):
                    values_by_indicator[ind][symbol] = val

    # 4. Evaluate each entry rule across active symbols.
    rule_passes: list[set[str]] = []
    for rule in definition.entry_rules:
        left_map = values_by_indicator.get(rule.left, {})
        if rule.operator in QUANTILE_OPERATORS:
            rule_passes.append(_quantile_passing_symbols(rule, left_map))
            continue
        right_map = values_by_indicator.get(rule.right, {}) if rule.right is not None else None
        passed: set[str] = set()
        for symbol in active_symbols:
            left_val = left_map.get(symbol)
            right_val = right_map.get(symbol) if right_map is not None else rule.value
            if _compare_values(rule.operator, left_val, right_val):
                passed.add(symbol)
        rule_passes.append(passed)

    if not rule_passes:
        passing_symbols = set(active_symbols)
    elif definition.entry_logic == "all":
        passing_symbols = set.intersection(*rule_passes)
    else:
        passing_symbols = set.union(*rule_passes)

    # 5. Compute ranking scores for passing stocks.
    rank_map = values_by_indicator.get(definition.ranking.indicator, {})
    scores: dict[str, float] = {}
    for symbol in passing_symbols:
        raw_score = rank_map.get(symbol)
        if raw_score is None or not isfinite(raw_score):
            continue
        scores[symbol] = -raw_score if definition.ranking.direction == "ascending" else raw_score

    return UniverseEvaluation(scores=scores, indicator_values=values_by_indicator)


def passes(group: pd.DataFrame, definition: RuleStrategyDefinition) -> bool:
    """Whether one stock (its history up to the day, oldest first) meets the entry conditions."""

    outcomes = [_evaluate_rule(group, rule) for rule in definition.entry_rules]
    return all(outcomes) if definition.entry_logic == "all" else any(outcomes)


def rank_score(group: pd.DataFrame, definition: RuleStrategyDefinition) -> float | None:
    """The stock's score for the top-N pick (higher is picked first), or None when it does not
    pass or has no ranking value. The backtest and the screen of today's stocks both use this."""

    if not passes(group, definition):
        return None
    score = _indicator_value(group, definition.ranking.indicator)
    if score is None or not isfinite(score):
        return None
    return -score if definition.ranking.direction == "ascending" else score


def indicator_value(group: pd.DataFrame, indicator: IndicatorSpec | None) -> float | None:
    """One indicator on the stock's last day, or None if the value is unavailable."""

    return _indicator_value(group, indicator)


def _evaluate_rule(group: pd.DataFrame, rule: RuleSpec) -> bool:
    left = _indicator_value(group, rule.left)
    right = _indicator_value(group, rule.right) if rule.right is not None else rule.value
    if left is None or right is None or not isfinite(left) or not isfinite(right):
        return False
    if rule.operator == "greater_than":
        return left > right
    if rule.operator == "greater_or_equal":
        return left >= right
    if rule.operator == "less_than":
        return left < right
    if rule.operator == "less_or_equal":
        return left <= right
    return False


def _indicator_value(group: pd.DataFrame, indicator: IndicatorSpec | None) -> float | None:
    if indicator is None:
        return None
    if indicator.name in FUNDAMENTAL_INDICATORS:
        if indicator.name not in group.columns or group.empty:
            return None
        value = group[indicator.name].iat[-1]
        return float(value) if pd.notna(value) and isfinite(value) else None
    close = group["adjusted_close"].dropna()
    if close.empty:
        return None
    window = indicator.window
    if indicator.name == "close":
        return float(close.iloc[-1])
    assert window is not None
    if indicator.name == "return":
        if len(close) < window + 1 or float(close.iloc[-window - 1]) <= 0:
            return None
        return float(close.iloc[-1] / close.iloc[-window - 1] - 1.0)
    if indicator.name == "moving_average":
        if len(close) < window:
            return None
        return float(close.tail(window).mean())
    if indicator.name == "volatility":
        value = latest_annualized_volatility(close, window)
        return float(value) if pd.notna(value) else None
    if indicator.name == "average_amount":
        amount = group["amount"].dropna()
        if len(amount) < window:
            return None
        return float(amount.tail(window).mean())
    if indicator.name in {"previous_high", "previous_low"}:
        if len(close) < window + 1:
            return None
        previous = close.iloc[-window - 1 : -1]
        return float(previous.max() if indicator.name == "previous_high" else previous.min())
    if indicator.name == "rsi":
        if len(close) < window + 1:
            return None
        changes = close.tail(window + 1).diff().dropna()
        average_gain = float(changes.clip(lower=0).mean())
        average_loss = float((-changes.clip(upper=0)).mean())
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)
    if indicator.name == "drawdown":
        if len(close) < window:
            return None
        recent = close.tail(window)
        peak = float(recent.max())
        return float(recent.iloc[-1] / peak - 1.0) if peak > 0 else None
    return None
