import sqlite3

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app import database
from app.quant.runtime import build_factor_registry
from app.routes.workspace import CustomFactorIn, factor_custom_create
from quant_platform.factors.combine import combine_factors
from quant_platform.factors.custom import build_custom_factor
from quant_platform.factors.expression import parse_factor_expression


@pytest.mark.parametrize("expression", [
    "price", "10 + 2", "close[-1]", "close.__class__", "mean(close, window=5)",
    "lag(close, -1)", "lag(lag(close, 160), 160)", "close ** 2", "close + 1e1000",
])
def test_formula_rejects_unsupported_fields_syntax_and_history(expression):
    with pytest.raises(ValueError):
        parse_factor_expression(expression)


def test_formula_missing_values_and_trailing_windows():
    dates = pd.bdate_range("2025-01-02", periods=6)
    bars = pd.DataFrame({
        "trade_date": dates,
        "symbol": "S",
        "adjusted_close": [10., 12., np.nan, 14., 16., 18.],
        "roe_avg": [.1, .1, .1, .1, np.nan, .1],
        "pb_mrq": [2., 0., 4., 5., 5., 1.],
    })
    value = build_custom_factor("quality", expression="ROE / PB")
    result = value.compute(bars).set_index("date")["value"]
    assert result.to_dict() == pytest.approx({dates[0]: .05, dates[2]: .025, dates[3]: .02, dates[5]: .1})
    trend = build_custom_factor("trend", expression="mean(ret(close, 1), 2)")
    assert trend.min_history == 3
    scores = trend.compute(bars)
    assert list(scores.date) == [dates[5]]
    assert scores.value.iloc[0] == pytest.approx((16 / 14 - 1 + 18 / 16 - 1) / 2)
    for day in dates:
        past = trend.compute(bars[bars.trade_date <= day])
        pd.testing.assert_frame_equal(scores[scores.date <= day].reset_index(drop=True), past)

    bars["raw_close"] = 10.
    bars.loc[:1, "adjusted_close"] = np.nan
    close = build_custom_factor("adjusted_price", expression="close")
    assert close.compute(bars.iloc[:2]).empty
    assert close.compute(bars).date.min() > dates[1]


def test_daily_rank_applies_direction_and_excludes_zero_weight_components():
    first, second = pd.to_datetime(["2025-01-02", "2025-01-03"])
    keys = {"date": [first, first, first, second], "symbol": ["A", "B", "C", "B"]}
    frames = {
        "quality": pd.DataFrame({**keys, "value": [1, 4, 4, 5]}),
        "cost": pd.DataFrame({**keys, "value": [20, 10, 30, 5]}),
        "unused": pd.DataFrame({**keys, "value": [np.nan] * 4}),
    }
    scores = combine_factors(
        frames, {"quality": 6, "cost": 4, "unused": 0},
        directions={"cost": -1}, missing="drop", standardization="rank",
    )
    assert list(scores.symbol) == ["A", "B", "C", "B"]
    assert list(scores.value) == pytest.approx([-.6, .7, -.1, 0])


def test_legacy_database_migrates_and_registers_formulas_by_owner(tmp_path, monkeypatch):
    path = tmp_path / "formulas.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE custom_factors (
                id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, display_name TEXT, description TEXT,
                field TEXT, operator TEXT, window INTEGER, window2 INTEGER, direction INTEGER,
                created_at TEXT, UNIQUE (user_id, name)
            );
            INSERT INTO custom_factors VALUES
                (1, 1, 'legacy_trend', '旧因子', '', 'adjusted_close', 'momentum', 20, NULL, 1, '2025-01-01');
        """)
    database.init_db()
    database.init_db()
    user = {"id": 1}
    body = CustomFactorIn(name="quality_test", display_name="质量估值", expression="ROE / PB")
    factor_custom_create(body, user)
    with pytest.raises(HTTPException) as exc:
        factor_custom_create(body, user)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        factor_custom_create(CustomFactorIn(name="bad_formula", expression="lag(close, -2)"), user)
    assert exc.value.status_code == 422

    registry = build_factor_registry(user)
    assert registry.get("legacy_trend").operator == "momentum"
    assert registry.get("quality_test").formula == "ROE / PB"
    assert "quality_test" not in build_factor_registry({"id": 2})
