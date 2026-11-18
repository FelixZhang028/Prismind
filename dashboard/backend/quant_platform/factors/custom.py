"""自定义因子：由用户在因子研究室中通过结构化参数或公式定义的因子。

与内置因子一致，输出 ``(date, symbol, value)`` 三列长表；实现只使用
rolling / shift 等因果算子，满足防未来函数约定。自定义因子可直接交给
``FactorEvaluator`` 评估，也可作为 ``CompositeFactor`` 的成分参与合成，
并持久化到本地 JSON 文件以便下次启动继续使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_platform.data.extras import extra_columns, require_extra_data
from quant_platform.factors.base import (
    FACTOR_COLUMNS,
    FactorDefinition,
    melt_wide,
    pivot_field,
)
from quant_platform.factors.expression import parse_factor_expression

_PRICE = "adjusted_close"

#: 自定义因子可选的行情字段（key -> 中文名）。
FIELDS: dict[str, str] = {
    "adjusted_close": "收盘价（复权）",
    "raw_open": "开盘价",
    "raw_high": "最高价",
    "raw_low": "最低价",
    "pre_close": "昨收价",
    "volume": "成交量",
    "amount": "成交额",
}

#: 自定义因子可选的算子（key -> 元信息）。
#: ``min_extra`` 表示在窗口基础上还需多读的历史条数（如 momentum 需要 N+1）。
OPERATORS: dict[str, dict[str, object]] = {
    "momentum": {
        "label": "动量（N 日涨跌幅）",
        "window2": False,
        "min_extra": 1,
        "direction": 1,
    },
    "bias": {
        "label": "乖离率（相对 N 日均线）",
        "window2": False,
        "min_extra": 0,
        "direction": -1,
    },
    "sma": {
        "label": "N 日均值",
        "window2": False,
        "min_extra": 0,
        "direction": 1,
    },
    "rolling_std": {
        "label": "N 日滚动标准差",
        "window2": False,
        "min_extra": 0,
        "direction": -1,
    },
    "volatility": {
        "label": "N 日收益波动率",
        "window2": False,
        "min_extra": 1,
        "direction": -1,
    },
    "ma_ratio": {
        "label": "短均线 / 长均线",
        "window2": True,
        "min_extra": 0,
        "direction": 1,
    },
    "pv_corr": {
        "label": "N 日量价相关性",
        "window2": False,
        "min_extra": 0,
        "direction": -1,
    },
}

#: 自定义因子持久化文件（相对运行目录）。
DEFAULT_STORE_PATH: Path = Path("runtime") / "custom_factors.json"


def _wide(bars: pd.DataFrame, field: str) -> pd.DataFrame:
    """把某一行情字段透视为 ``index=date, columns=symbol`` 的宽表。"""
    if field == _PRICE:
        if _PRICE in bars.columns and bars[_PRICE].notna().any():
            return pivot_field(bars, _PRICE)
        return pivot_field(bars, "raw_close")
    if field not in bars.columns:
        raise ValueError(f"行情数据缺少字段: {field}")
    return pivot_field(bars, field)


def _make_formula(field: str, operator: str, window: int, window2: int | None) -> str:
    """生成人类可读的公式说明。"""
    if operator == "momentum":
        return f"{field}(t) / {field}(t-{window}) - 1"
    if operator == "bias":
        return f"{field}(t) / MA({field}, {window}) - 1"
    if operator == "sma":
        return f"MA({field}, {window})"
    if operator == "rolling_std":
        return f"std({field}, {window})"
    if operator == "volatility":
        return f"std({field} 日收益率, {window})"
    if operator == "ma_ratio":
        return f"MA({field}, {window}) / MA({field}, {window2})"
    if operator == "pv_corr":
        return f"corr(close, {field}, {window})"
    return operator


@dataclass(frozen=True)
class CustomFactor(FactorDefinition):
    """用同一个持久化格式保存结构化因子和公式因子。"""

    field: str = "adjusted_close"
    operator: str = "momentum"
    window: int = 20
    window2: int | None = None
    expression: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("direction 只能是 1 或 -1")
        if self.expression is not None:
            parsed = parse_factor_expression(self.expression)
            object.__setattr__(self, "min_history", parsed.min_history)
            object.__setattr__(self, "required_fields", parsed.fields)
            return
        if self.field not in FIELDS:
            raise ValueError(f"未知字段: {self.field}")
        op = OPERATORS.get(self.operator)
        if op is None:
            raise ValueError(f"未知算子: {self.operator}")
        if self.window < 1:
            raise ValueError("窗口 N 必须 >= 1")
        if op["window2"] and (self.window2 is None or self.window2 < 1):
            raise ValueError("该算子需要第二个窗口 N2")
        history = max(self.window, self.window2) if op["window2"] else self.window
        object.__setattr__(self, "min_history", history + int(op["min_extra"]))
        object.__setattr__(self, "required_fields", self._required_fields())

    def _required_fields(self) -> tuple[str, ...]:
        fields = [self.field]
        if self.operator == "pv_corr":
            fields.append(_PRICE)
        return tuple(dict.fromkeys(fields))

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        if self.expression is not None:
            parsed = parse_factor_expression(self.expression)
            require_extra_data(bars, extra_columns(parsed.fields))
            missing = [field for field in parsed.fields if field not in bars.columns]
            if missing:
                raise ValueError(f"行情数据缺少字段: {', '.join(missing)}")
            return melt_wide(parsed.compute({field: pivot_field(bars, field) for field in parsed.fields}))
        x = _wide(bars, self.field)
        operator = self.operator
        if operator == "momentum":
            wide = x / x.shift(self.window) - 1.0
        elif operator == "bias":
            wide = x / x.rolling(self.window, min_periods=self.window).mean() - 1.0
        elif operator == "sma":
            wide = x.rolling(self.window, min_periods=self.window).mean()
        elif operator == "rolling_std":
            wide = x.rolling(self.window, min_periods=self.window).std()
        elif operator == "volatility":
            wide = x.pct_change().rolling(self.window, min_periods=self.window).std()
        elif operator == "ma_ratio":
            short = x.rolling(self.window, min_periods=self.window).mean()
            long_ = x.rolling(self.window2, min_periods=self.window2).mean()
            wide = short / long_
        elif operator == "pv_corr":
            close = _wide(bars, _PRICE)
            result: dict[str, pd.Series] = {}
            for symbol in close.columns:
                if symbol not in x.columns:
                    continue
                result[symbol] = (
                    close[symbol].rolling(self.window, min_periods=self.window).corr(x[symbol])
                )
            if not result:
                return pd.DataFrame(columns=FACTOR_COLUMNS)
            return melt_wide(pd.DataFrame(result))
        else:
            raise ValueError(f"未知算子: {operator}")
        return melt_wide(wide)


def build_custom_factor(
    name: str,
    *,
    display_name: str = "",
    description: str = "",
    field: str = "adjusted_close",
    operator: str = "momentum",
    window: int = 20,
    window2: int | None = None,
    direction: int | None = None,
    expression: str | None = None,
) -> CustomFactor:
    """校验并构造一个自定义因子，自动补全公式、最小历史与所需字段。"""
    if not name or not name.strip():
        raise ValueError("因子标识不能为空")
    if expression is not None:
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("请输入因子公式")
        expression = expression.strip()
        return CustomFactor(
            name=name.strip(),
            display_name=display_name.strip() or name.strip(),
            description=description.strip(),
            formula=expression,
            direction=1 if direction is None else direction,
            category="自定义",
            source="自定义",
            version="custom-expression-v1",
            expression=expression,
        )
    op = OPERATORS.get(operator)
    if op is None:
        raise ValueError(f"未知算子: {operator}")
    if field not in FIELDS:
        raise ValueError(f"未知字段: {field}")
    if direction is None:
        direction = int(op["direction"])
    if direction not in (1, -1):
        raise ValueError("direction 只能是 1 或 -1")
    formula = _make_formula(field, operator, window, window2)
    desc = description.strip()
    if not desc:
        desc = f"{FIELDS[field]}的{op['label']}自定义因子"
    return CustomFactor(
        name=name.strip(),
        display_name=display_name.strip() or name.strip(),
        description=desc,
        formula=formula,
        field=field,
        operator=operator,
        window=int(window),
        window2=int(window2) if window2 is not None else None,
        direction=direction,
        category="自定义",
        source="自定义",
        version="custom",
    )


def custom_factor_to_dict(factor: CustomFactor) -> dict[str, object]:
    """把自定义因子序列化为可持久化的字典。"""
    return {
        "name": factor.name,
        "display_name": factor.display_name,
        "description": factor.description,
        "field": factor.field,
        "operator": factor.operator,
        "window": factor.window,
        "window2": factor.window2,
        "direction": factor.direction,
        **({"expression": factor.expression} if factor.expression is not None else {}),
    }


def custom_factor_from_dict(data: dict[str, object]) -> CustomFactor:
    """从持久化字典还原自定义因子。"""
    return build_custom_factor(
        name=str(data["name"]),
        display_name=str(data.get("display_name", "")),
        description=str(data.get("description", "")),
        field=str(data.get("field", "adjusted_close")),
        operator=str(data.get("operator", "momentum")),
        window=int(data.get("window", 20)),
        window2=int(data["window2"]) if data.get("window2") is not None else None,
        direction=int(data["direction"]) if data.get("direction") is not None else None,
        expression=data.get("expression"),
    )


def load_custom_factors(path: Path = DEFAULT_STORE_PATH) -> list[CustomFactor]:
    """从 JSON 文件加载自定义因子；文件缺失或损坏时返回空列表并跳过非法项。"""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    factors: list[CustomFactor] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            factors.append(custom_factor_from_dict(item))
        except (KeyError, TypeError, ValueError):
            continue
    return factors


def save_custom_factors(factors: list[CustomFactor], path: Path = DEFAULT_STORE_PATH) -> None:
    """把自定义因子持久化到 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [custom_factor_to_dict(factor) for factor in factors]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
