"""Restricted arithmetic and trailing-window functions for user factors."""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite

import pandas as pd

from quant_platform.data.corporate_actions import DIVIDEND_YIELD
from quant_platform.data.fundamentals import DERIVED_COLUMNS, FUNDAMENTAL_COLUMNS
from quant_platform.data.indicators import INDICATOR_COLUMNS

MAX_EXPRESSION_LENGTH = 300
MAX_HISTORY = 252
PRICE_FIELDS = ("adjusted_close", "raw_close", "raw_open", "raw_high", "raw_low", "pre_close", "volume", "amount")
ALIASES = {"close": "adjusted_close", "roe": "roe_avg", "pb": "pb_mrq", "pe": "pe_ttm"}
EXPRESSION_FIELDS = (*PRICE_FIELDS, *INDICATOR_COLUMNS, *FUNDAMENTAL_COLUMNS, *DERIVED_COLUMNS, DIVIDEND_YIELD)
WINDOW_FUNCTIONS = ("lag", "ret", "mean", "std", "volatility")
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _field(name: str) -> str:
    return ALIASES.get(name.lower(), name.lower())


@dataclass(frozen=True)
class FactorExpression:
    root: ast.expr
    fields: tuple[str, ...]
    min_history: int

    def compute(self, fields: dict[str, pd.DataFrame]) -> pd.DataFrame:
        template = fields[self.fields[0]]

        def finite(value: pd.DataFrame) -> pd.DataFrame:
            return value.replace([float("inf"), -float("inf")], float("nan"))

        def divide(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
            return finite(numerator / denominator.where(denominator != 0))

        def evaluate(node: ast.expr) -> pd.DataFrame:
            if isinstance(node, ast.Name):
                return finite(fields[_field(node.id)])
            if isinstance(node, ast.Constant):
                return pd.DataFrame(float(node.value), index=template.index, columns=template.columns)
            if isinstance(node, ast.UnaryOp):
                value = evaluate(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Div):
                    return divide(left, right)
                return finite(_BINARY[type(node.op)](left, right))
            function = node.func.id.lower()
            value, window = evaluate(node.args[0]), node.args[1].value
            if function == "lag":
                return value.shift(window)
            if function == "ret":
                return divide(value, value.shift(window)) - 1
            if function == "volatility":
                value = divide(value, value.shift(1)) - 1
            rolling = value.rolling(window, min_periods=window)
            return rolling.mean() if function == "mean" else rolling.std()

        return finite(evaluate(self.root))


@lru_cache(maxsize=256)
def parse_factor_expression(expression: str) -> FactorExpression:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"公式最多 {MAX_EXPRESSION_LENGTH} 个字符")
    try:
        root = ast.parse(expression, mode="eval").body
    except SyntaxError as exc:
        raise ValueError("公式格式错误，请检查运算符和括号") from exc

    fields: dict[str, None] = {}

    def lookback(node: ast.expr) -> int:
        if isinstance(node, ast.Name):
            field = _field(node.id)
            if field not in EXPRESSION_FIELDS:
                raise ValueError(f"未知公式字段：{node.id}")
            fields[field] = None
            return 1
        if isinstance(node, ast.Constant) and type(node.value) in (float, int) and abs(node.value) <= 1e308 and isfinite(node.value):
            return 1
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return lookback(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return max(lookback(node.left), lookback(node.right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.lower() in WINDOW_FUNCTIONS:
            function = node.func.id.lower()
            if len(node.args) != 2 or node.keywords:
                raise ValueError(f"{function} 的格式为 {function}(字段或表达式, 窗口)")
            window = node.args[1]
            minimum = 2 if function in {"std", "volatility"} else 1
            if not isinstance(window, ast.Constant) or type(window.value) is not int or not minimum <= window.value <= MAX_HISTORY:
                raise ValueError(f"{function} 的窗口必须是 {minimum} 至 {MAX_HISTORY} 的整数")
            required = lookback(node.args[0]) + window.value
            return required - 1 if function in {"mean", "std"} else required
        raise ValueError("公式仅支持字段、数值、四则运算和列出的历史窗口函数")

    history = lookback(root)
    if not fields:
        raise ValueError("公式至少需要引用一个行情或基本面字段")
    if history > MAX_HISTORY:
        raise ValueError(f"公式最多可依赖 {MAX_HISTORY} 个交易日的历史")
    return FactorExpression(root, tuple(fields), history)
