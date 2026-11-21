"""Versioned, auditable schema shared by templates and the visual rule builder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import isfinite
from typing import Any

from quant_platform.core.exceptions import ConfigurationError

SCHEMA_VERSION = 1

MARKET_TIMING_BENCHMARKS: dict[str, str] = {
    "000300.SH": "沪深 300",
    "000905.SH": "中证 500",
    "000016.SH": "上证 50",
    "399006.SZ": "创业板指",
}
HOLD_BUFFER_MAX = 100
TIMING_MA_MIN, TIMING_MA_MAX = 5, 250
STOP_LOSS_MIN, STOP_LOSS_MAX = 0.02, 0.50
TRAILING_STOP_MIN, TRAILING_STOP_MAX = 0.03, 0.50

FUNDAMENTAL_INDICATORS: dict[str, str] = {
    "dividend_yield": "股息率（近一年）",
    "roe_avg": "ROE（最新已披露财报）",
    "pe_ttm": "市盈率（PE TTM）",
    "pb_mrq": "市净率（PB 最近一季）",
}

INDICATOR_LABELS: dict[str, str] = {
    "close": "收盘价",
    "return": "区间涨跌幅",
    "moving_average": "移动平均线",
    "volatility": "历史波动率",
    "average_amount": "平均成交额",
    "previous_high": "前期最高收盘价",
    "previous_low": "前期最低收盘价",
    "rsi": "RSI强弱指标",
    "drawdown": "区间回撤",
    **FUNDAMENTAL_INDICATORS,
}

OPERATOR_LABELS: dict[str, str] = {
    "greater_than": "大于",
    "greater_or_equal": "大于等于",
    "less_than": "小于",
    "less_or_equal": "小于等于",
}

_WINDOW_RULES: dict[str, tuple[int, int]] = {
    "return": (1, 500),
    "moving_average": (2, 500),
    "volatility": (2, 250),
    "average_amount": (1, 250),
    "previous_high": (2, 500),
    "previous_low": (2, 500),
    "rsi": (2, 120),
    "drawdown": (2, 500),
}


@dataclass(frozen=True)
class IndicatorSpec:
    """One approved point-in-time indicator."""

    name: str
    window: int | None = None

    @property
    def window_limits(self) -> tuple[int, int]:
        """Supported window bounds for editors of windowed indicators."""
        return _WINDOW_RULES[self.name]

    @classmethod
    def from_mapping(cls, value: Any) -> IndicatorSpec:
        if not isinstance(value, dict):
            raise ConfigurationError("指标必须是对象")
        name = str(value.get("name", "")).strip()
        raw_window = value.get("window")
        window = int(raw_window) if raw_window is not None else None
        result = cls(name=name, window=window)
        result.validate()
        return result

    def validate(self) -> None:
        if self.name not in INDICATOR_LABELS:
            raise ConfigurationError(f"不支持的指标：{self.name}")
        if self.name not in _WINDOW_RULES:
            if self.window is not None:
                raise ConfigurationError(f"{INDICATOR_LABELS[self.name]}指标不需要周期")
            return
        if self.window is None:
            raise ConfigurationError(f"{INDICATOR_LABELS[self.name]}必须设置周期")
        minimum, maximum = _WINDOW_RULES[self.name]
        if not minimum <= self.window <= maximum:
            raise ConfigurationError(
                f"{INDICATOR_LABELS[self.name]}周期必须在{minimum}至{maximum}之间"
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name}
        if self.window is not None:
            result["window"] = self.window
        return result

    def describe(self) -> str:
        label = INDICATOR_LABELS[self.name]
        return label if self.window is None else f"{self.window}日{label}"


@dataclass(frozen=True)
class RuleSpec:
    """A comparison between an indicator and a constant or another indicator."""

    left: IndicatorSpec
    operator: str
    value: float | None = None
    right: IndicatorSpec | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> RuleSpec:
        if not isinstance(value, dict):
            raise ConfigurationError("条件规则必须是对象")
        raw_value = value.get("value")
        result = cls(
            left=IndicatorSpec.from_mapping(value.get("left")),
            operator=str(value.get("operator", "")).strip(),
            value=float(raw_value) if raw_value is not None else None,
            right=(
                IndicatorSpec.from_mapping(value["right"])
                if value.get("right") is not None
                else None
            ),
        )
        result.validate()
        return result

    def validate(self) -> None:
        self.left.validate()
        if self.operator not in OPERATOR_LABELS:
            raise ConfigurationError(f"不支持的判断方式：{self.operator}")
        if (self.value is None) == (self.right is None):
            raise ConfigurationError("条件右侧必须且只能选择固定值或另一个指标")
        if self.value is not None and not isfinite(self.value):
            raise ConfigurationError("条件固定值必须是有限数字")
        if self.right is not None:
            self.right.validate()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "left": self.left.to_dict(),
            "operator": self.operator,
        }
        if self.right is not None:
            result["right"] = self.right.to_dict()
        else:
            result["value"] = self.value
        return result

    def describe(self) -> str:
        right = self.right.describe() if self.right is not None else _format_number(self.value, self.left.name)
        return f"{self.left.describe()}{OPERATOR_LABELS[self.operator]}{right}"


@dataclass(frozen=True)
class RankingSpec:
    """Cross-sectional ordering used by the portfolio's top-N selector."""

    indicator: IndicatorSpec
    direction: str = "descending"

    @classmethod
    def from_mapping(cls, value: Any) -> RankingSpec:
        if not isinstance(value, dict):
            raise ConfigurationError("排序规则必须是对象")
        result = cls(
            indicator=IndicatorSpec.from_mapping(value.get("indicator")),
            direction=str(value.get("direction", "descending")),
        )
        result.validate()
        return result

    def validate(self) -> None:
        self.indicator.validate()
        if self.direction not in {"ascending", "descending"}:
            raise ConfigurationError("排序方向只能是ascending或descending")

    def to_dict(self) -> dict[str, Any]:
        return {"indicator": self.indicator.to_dict(), "direction": self.direction}

    def describe(self) -> str:
        direction = "从高到低" if self.direction == "descending" else "从低到高"
        return f"按{self.indicator.describe()}{direction}排序"


@dataclass(frozen=True)
class MarketTimingSpec:
    """Point-in-time benchmark moving-average timing filter."""

    benchmark: str = "000300.SH"
    ma_window: int = 60
    off_weight: float = 0.0

    @classmethod
    def from_mapping(cls, value: Any) -> MarketTimingSpec | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ConfigurationError("大盘择时配置必须是对象")
        if value.get("enabled") is False:
            return None
        benchmark = str(value.get("benchmark", "000300.SH")).strip().upper()
        raw_ma = value.get("ma_window", 60)
        raw_off = value.get("off_weight", 0.0)
        if isinstance(raw_ma, bool) or isinstance(raw_off, bool):
            raise ConfigurationError("大盘择时的均线周期和弱势仓位必须是有效数字")
        try:
            ma_window = int(raw_ma)
            off_weight = float(raw_off)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("大盘择时的均线周期和弱势仓位必须是有效数字") from exc
        result = cls(benchmark=benchmark, ma_window=ma_window, off_weight=off_weight)
        result.validate()
        return result

    def validate(self) -> None:
        if self.benchmark not in MARKET_TIMING_BENCHMARKS:
            raise ConfigurationError(f"暂不支持的大盘择时参考指数：{self.benchmark}")
        if not TIMING_MA_MIN <= self.ma_window <= TIMING_MA_MAX:
            raise ConfigurationError(f"大盘择时均线周期必须在{TIMING_MA_MIN}至{TIMING_MA_MAX}之间")
        if not isfinite(self.off_weight) or not 0.0 <= self.off_weight < 1.0:
            raise ConfigurationError("大盘走弱时的目标仓位必须在0%至100%之间（不含100%）")

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "ma_window": self.ma_window,
            "off_weight": self.off_weight,
        }

    def describe(self) -> str:
        name = MARKET_TIMING_BENCHMARKS.get(self.benchmark, self.benchmark)
        action = "空仓等待" if self.off_weight <= 0 else f"目标总仓位降至{_trim(f'{self.off_weight * 100:.0f}')}%"
        return f"大盘择时：当{name}收盘低于{self.ma_window}日均线时，{action}。"


@dataclass(frozen=True)
class ExitRulesSpec:
    """Optional per-position stop-loss and trailing take-profit exit rules."""

    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> ExitRulesSpec | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ConfigurationError("个股止损止盈配置必须是对象")
        if value.get("enabled") is False:
            return None
        stop_loss = cls._parse_pct(value.get("stop_loss_pct"), "个股止损比例")
        trailing_stop = cls._parse_pct(value.get("trailing_stop_pct"), "移动止盈回撤比例")
        if stop_loss is None and trailing_stop is None:
            return None
        result = cls(stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop)
        result.validate()
        return result

    @staticmethod
    def _parse_pct(raw: Any, label: str) -> float | None:
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            raise ConfigurationError(f"{label}必须是有效数字")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{label}必须是有效数字") from exc
        if value == 0.0:
            return None
        return value

    def validate(self) -> None:
        if self.stop_loss_pct is None and self.trailing_stop_pct is None:
            raise ConfigurationError("个股止损与移动止盈至少需开启一项")
        if self.stop_loss_pct is not None:
            if not isfinite(self.stop_loss_pct) or not STOP_LOSS_MIN <= self.stop_loss_pct <= STOP_LOSS_MAX:
                raise ConfigurationError(
                    f"个股止损比例必须在{int(STOP_LOSS_MIN * 100)}%至{int(STOP_LOSS_MAX * 100)}%之间"
                )
        if self.trailing_stop_pct is not None:
            if not isfinite(self.trailing_stop_pct) or not TRAILING_STOP_MIN <= self.trailing_stop_pct <= TRAILING_STOP_MAX:
                raise ConfigurationError(
                    f"移动止盈回撤比例必须在{int(TRAILING_STOP_MIN * 100)}%至{int(TRAILING_STOP_MAX * 100)}%之间"
                )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.stop_loss_pct is not None:
            result["stop_loss_pct"] = self.stop_loss_pct
        if self.trailing_stop_pct is not None:
            result["trailing_stop_pct"] = self.trailing_stop_pct
        return result

    def describe(self) -> str:
        clauses: list[str] = []
        if self.stop_loss_pct is not None:
            clauses.append(
                f"单只持仓较成本亏损达到{_trim(f'{self.stop_loss_pct * 100:.1f}')}%时次日开盘止损卖出"
            )
        if self.trailing_stop_pct is not None:
            clauses.append(
                f"从持仓以来最高价回撤达到{_trim(f'{self.trailing_stop_pct * 100:.1f}')}%时次日开盘止盈卖出"
            )
        return f"个股风控：{'；'.join(clauses)}。"


@dataclass(frozen=True)
class RuleStrategyDefinition:
    """Portable strategy definition generated by P0 templates or P1 blocks."""

    strategy_id: str
    name: str
    description: str
    entry_logic: str
    entry_rules: tuple[RuleSpec, ...]
    ranking: RankingSpec
    schema_version: int = SCHEMA_VERSION
    hold_buffer: int = 0
    market_timing: MarketTimingSpec | None = None
    exit_rules: ExitRulesSpec | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> RuleStrategyDefinition:
        if not isinstance(value, dict):
            raise ConfigurationError("策略配置必须是对象")
        raw_rules = value.get("entry_rules", [])
        if not isinstance(raw_rules, list):
            raise ConfigurationError("买入条件必须是列表")
        raw_buffer = value.get("hold_buffer", 0)
        if isinstance(raw_buffer, bool):
            raise ConfigurationError("防频繁换手缓冲必须是整数")
        try:
            hold_buffer = int(raw_buffer) if raw_buffer is not None else 0
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("防频繁换手缓冲必须是整数") from exc
        result = cls(
            strategy_id=str(value.get("strategy_id", "")).strip(),
            name=str(value.get("name", "")).strip(),
            description=str(value.get("description", "")).strip(),
            entry_logic=str(value.get("entry_logic", "all")).strip(),
            entry_rules=tuple(RuleSpec.from_mapping(item) for item in raw_rules),
            ranking=RankingSpec.from_mapping(value.get("ranking")),
            schema_version=int(value.get("schema_version", SCHEMA_VERSION)),
            hold_buffer=hold_buffer,
            market_timing=MarketTimingSpec.from_mapping(value.get("market_timing")),
            exit_rules=ExitRulesSpec.from_mapping(value.get("exit_rules")),
        )
        result.validate()
        return result

    @classmethod
    def from_json(cls, text: str) -> RuleStrategyDefinition:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"策略JSON格式错误：{exc}") from exc
        return cls.from_mapping(value)

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ConfigurationError(f"不支持的策略协议版本：{self.schema_version}")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", self.strategy_id):
            raise ConfigurationError("策略编号只能包含字母、数字、下划线和连字符")
        if not self.name or len(self.name) > 80:
            raise ConfigurationError("策略名称不能为空且不能超过80个字符")
        if self.entry_logic not in {"all", "any"}:
            raise ConfigurationError("条件组合只能是all或any")
        if not 1 <= len(self.entry_rules) <= 10:
            raise ConfigurationError("策略必须包含1至10条买入条件")
        if not 0 <= self.hold_buffer <= HOLD_BUFFER_MAX:
            raise ConfigurationError(f"防频繁换手缓冲必须在0至{HOLD_BUFFER_MAX}之间")
        for rule in self.entry_rules:
            rule.validate()
        self.ranking.validate()
        if self.market_timing is not None:
            self.market_timing.validate()
        if self.exit_rules is not None:
            self.exit_rules.validate()

    def _indicators(self) -> list[IndicatorSpec]:
        indicators = [self.ranking.indicator]
        for rule in self.entry_rules:
            indicators.append(rule.left)
            if rule.right is not None:
                indicators.append(rule.right)
        return indicators

    @property
    def data_fields(self) -> frozenset[str]:
        return frozenset(item.name for item in self._indicators() if item.name in FUNDAMENTAL_INDICATORS)

    @property
    def minimum_history_days(self) -> int:
        return max(_indicator_history(item) for item in self._indicators())

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "entry_logic": self.entry_logic,
            "entry_rules": [rule.to_dict() for rule in self.entry_rules],
            "ranking": self.ranking.to_dict(),
        }
        if self.hold_buffer > 0:
            result["hold_buffer"] = self.hold_buffer
        if self.market_timing is not None:
            result["market_timing"] = self.market_timing.to_dict()
        if self.exit_rules is not None:
            result["exit_rules"] = self.exit_rules.to_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def describe(self, *, top_n: int, rebalance: str) -> str:
        logic = "并且" if self.entry_logic == "all" else "或者"
        conditions = f"，{logic}".join(rule.describe() for rule in self.entry_rules)
        frequencies = {"daily": "每日", "weekly": "每周", "monthly": "每月"}
        parts = [
            f"{frequencies.get(rebalance, rebalance)}调仓；只保留满足“{conditions}”的股票；"
            f"{self.ranking.describe()}，等权持有前{top_n}只。条件失效时在下一次调仓退出。"
        ]
        if self.hold_buffer > 0:
            parts.append(f"防频繁换手：已持仓且仍满足条件的股票，排名在前{top_n + self.hold_buffer}名以内继续保留。")
        if self.market_timing is not None:
            parts.append(self.market_timing.describe())
        if self.exit_rules is not None:
            parts.append(self.exit_rules.describe())
        return "".join(parts)


def _indicator_history(indicator: IndicatorSpec) -> int:
    if indicator.window is None:
        return 1
    needs_previous = {
        "return",
        "volatility",
        "previous_high",
        "previous_low",
        "rsi",
    }
    return indicator.window + 1 if indicator.name in needs_previous else indicator.window


def _format_number(value: float | None, indicator: str = "") -> str:
    if value is None:
        return "未知值"
    if indicator in {"dividend_yield", "roe_avg"} or (
        indicator not in FUNDAMENTAL_INDICATORS and 0 < abs(value) < 1
    ):
        return f"{_trim(f'{value * 100:.2f}')}%"
    return _trim(f"{value:,.2f}")


def _trim(text: str) -> str:
    """Drop decimals that carry no information: 5.00 -> 5, 12.50 -> 12.5."""

    return text.rstrip("0").rstrip(".") if "." in text else text
