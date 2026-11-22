"""因子合成选股策略：把因子库中的因子按权重合成打分，供回测与模拟交易复用。

参数 ``factors_json`` 为 JSON 列表，元素形如::

    {"name": "momentum_20", "weight": 1.0}

策略在每个调仓日取足够长度的历史行情，逐因子计算当日截面值，按日
以 z-score 或排名标准化（含方向调整）后加权求和，分数越高越优先持有。
全部计算只依赖 ``<= 当日`` 的数据，满足平台的防未来函数约定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, ClassVar

import pandas as pd

from quant_platform.core.exceptions import ConfigurationError
from quant_platform.factors.base import FactorDefinition
from quant_platform.factors.combine import STANDARDIZATIONS, combine_factors
from quant_platform.factors.custom import CustomFactor, custom_factor_from_dict, custom_factor_to_dict
from quant_platform.factors.registry import default_registry
from quant_platform.signals.models import Signal
from quant_platform.strategies.base import Strategy
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.spec import ParameterKind, StrategyParameter


@dataclass(frozen=True)
class FactorWeight:
    """一个成分因子及其权重。"""

    name: str
    weight: float = 1.0
    custom_factor: CustomFactor | None = None
    direction: int | None = None


@dataclass(frozen=True)
class FactorCompositeParameters:
    components: tuple[FactorWeight, ...]
    clip: bool = False
    missing: str = "zero"
    standardization: str = "zscore"

    @classmethod
    def from_json(cls, text: str) -> FactorCompositeParameters:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"因子组合JSON格式错误：{exc}") from exc
        if not isinstance(raw, list) or not raw:
            raise ConfigurationError("因子组合必须是非空列表")
        if not isinstance(raw[0], dict):
            raise ConfigurationError("因子组合元素必须是对象")
        components: list[FactorWeight] = []
        clip = raw[0].get("clip", False)
        missing = raw[0].get("missing", "zero")
        standardization = raw[0].get("standardization", "zscore")
        if not isinstance(clip, bool) or missing not in ("zero", "drop", "median") or standardization not in STANDARDIZATIONS:
            raise ConfigurationError("组合清洗或标准化设置无效")
        registry = default_registry()
        for item in raw:
            if not isinstance(item, dict) or "name" not in item:
                raise ConfigurationError('因子组合元素必须形如 {"name": ..., "weight": ...}')
            name = str(item["name"]).strip()
            if (item.get("clip", False), item.get("missing", "zero"), item.get("standardization", "zscore")) != (
                clip, missing, standardization
            ):
                raise ConfigurationError("成分因子的清洗与标准化设置必须一致")
            snapshot = item.get("custom_factor")
            custom = None
            if snapshot is not None:
                if not isinstance(snapshot, dict) or snapshot.get("name") != name:
                    raise ConfigurationError("自定义因子快照与组合的因子标识不一致")
                try:
                    custom = custom_factor_from_dict(snapshot)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ConfigurationError(f"自定义因子定义无效：{name}") from exc
            if custom is None and name not in registry:
                raise ConfigurationError(f"未注册的因子：{name}")
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ConfigurationError(f"因子权重无效：{name}") from exc
            direction = item.get("direction")
            if direction is not None and (type(direction) is not int or direction not in (1, -1)):
                raise ConfigurationError(f"因子方向无效：{name}")
            components.append(FactorWeight(name, weight, custom, direction))
        names = [item.name for item in components]
        if len(set(names)) != len(names):
            raise ConfigurationError("因子组合中存在重复因子")
        if any(not isfinite(item.weight) for item in components):
            raise ConfigurationError("因子权重必须为有限数值")
        if not any(item.weight for item in components):
            raise ConfigurationError("因子权重不能全部为零")
        return cls(tuple(components), clip=clip, missing=missing, standardization=standardization)

    def to_json(self) -> str:
        return json.dumps(
            [
                {
                    "name": item.name,
                    "weight": item.weight,
                    "clip": self.clip,
                    "missing": self.missing,
                    "standardization": self.standardization,
                    **({"custom_factor": custom_factor_to_dict(item.custom_factor)} if item.custom_factor else {}),
                    **({"direction": item.direction} if item.direction is not None else {}),
                }
                for item in self.components
            ],
            ensure_ascii=False,
            sort_keys=True,
        )


class FactorCompositeStrategy(Strategy):
    """按因子库定义合成截面打分；不写死任何单一因子逻辑。"""

    plugin_name = "factor_composite"
    display_name = "因子合成策略"
    description = "由因子研究生成：多个因子按权重合成打分，等权持有高分股票"
    parameters: ClassVar[tuple[StrategyParameter, ...]] = (
        StrategyParameter(
            "factors_json",
            "因子组合定义",
            ParameterKind.STRING,
            "[]",
            'JSON 列表，如 [{"name": "momentum_20", "weight": 1.0, "direction": 1}]；direction 为 -1 表示反向（越小越好）',
        ),
    )
    required_fields = frozenset({"symbol", "trade_date"})

    def __init__(
        self,
        strategy_id: str,
        parameters: FactorCompositeParameters,
        components: tuple[FactorDefinition, ...],
    ) -> None:
        self.strategy_id = strategy_id
        self.config = parameters
        self._weighted_factors = tuple(
            (factor, component)
            for factor, component in zip(components, parameters.components, strict=True)
            if component.weight != 0
        )

    @classmethod
    def from_parameters(
        cls, strategy_id: str, parameters: dict[str, Any]
    ) -> FactorCompositeStrategy:
        config = FactorCompositeParameters.from_json(str(parameters["factors_json"]))
        registry = default_registry()
        components = tuple(item.custom_factor or registry.get(item.name) for item in config.components)
        return cls(strategy_id, config, components)

    @property
    def min_history(self) -> int:
        return max(factor.min_history for factor, _ in self._weighted_factors)

    @property
    def data_fields(self) -> frozenset[str]:
        """成分因子用到的行情字段；回测引擎据此决定要不要读取估值、换手率和财务数据。"""

        return frozenset(field for factor, _ in self._weighted_factors for field in factor.required_fields)

    def generate_signals(self, context: StrategyContext) -> list[Signal]:
        fields = set(self.data_fields)
        # 复权因子等可选列：行情里有就一起取，因子据此识别除权除息日、计算真实收益。
        fields |= {field for factor, _ in self._weighted_factors for field in factor.optional_fields} & context.available_fields
        fields = sorted(fields)
        history = context.history(fields=fields, lookback=self.min_history + 1)
        if history.empty:
            return []
        cutoff = pd.Timestamp(context.trade_date)

        frames: dict[str, pd.DataFrame] = {}
        weights: dict[str, float] = {}
        directions: dict[str, int] = {}
        for factor, component in self._weighted_factors:
            try:
                values = factor.compute(history)
            except ValueError:
                if self.config.missing != "zero":
                    return []
                continue  # 缺字段时跳过该因子而不是中断整个回测
            values["date"] = pd.to_datetime(values["date"]).dt.normalize()
            today = values[values["date"] == cutoff]
            if today.empty and self.config.missing != "median":
                if self.config.missing != "zero":
                    return []
                continue
            frames[factor.name] = today
            weights[factor.name] = component.weight
            directions[factor.name] = component.direction or factor.direction
        if not frames:
            return []

        if self.config.missing != "zero":
            universe = history.loc[
                pd.to_datetime(history["trade_date"]).dt.normalize() == cutoff,
                ["trade_date", "symbol"],
            ].rename(columns={"trade_date": "date"})
            universe["date"] = pd.to_datetime(universe["date"]).dt.normalize()
            frames = {
                name: universe.merge(frame, on=["date", "symbol"], how="left")
                for name, frame in frames.items()
            }
        composite = combine_factors(
            frames,
            weights,
            directions=directions,
            clip=self.config.clip,
            missing=self.config.missing,
            standardization=self.config.standardization,
        )
        signals: list[Signal] = []
        for row in composite.itertuples(index=False):
            signals.append(
                Signal(
                    strategy_id=self.strategy_id,
                    trade_date=context.trade_date,
                    symbol=str(row.symbol),
                    signal_type="FACTOR_COMPOSITE_SCORE",
                    score=float(row.value),
                    model_version="factor-composite-v1",
                )
            )
        return sorted(signals, key=lambda signal: (-signal.score, signal.symbol))
