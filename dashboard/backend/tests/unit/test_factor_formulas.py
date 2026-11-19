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
from quant_platform.factors.registry import default_registry
from quant_platform.strategies.rule_based import indicator_value
from quant_platform.strategies.rule_schema import IndicatorSpec


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
    with database.get_conn() as conn:
        conn.execute(
            """INSERT INTO custom_factors
               (user_id,name,display_name,description,field,operator,window,direction,created_at,expression)
               VALUES (1,'legacy_roe','旧版 ROE','','adjusted_close','momentum',20,1,'2025-01-01','ROE / PB')"""
        )
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
    legacy = registry.get("legacy_roe")
    quality = registry.get("quality_test")
    assert legacy.formula == "ROE / PB"
    assert legacy.required_fields == ("roe_avg", "pb_mrq")
    assert quality.formula == "roe_ttm / PB"
    assert quality.required_fields == ("pb_mrq", "pe_ttm")
    assert "quality_test" not in build_factor_registry({"id": 2})

    dates = pd.bdate_range("2024-01-01", periods=4)
    bars = pd.DataFrame({
        "trade_date": dates, "symbol": "S",
        "pb_mrq": [2., 2., -1., 2.], "pe_ttm": [10., -20., 5., 0.],
    })
    with pytest.raises(ValueError, match=r"2024-01-01.*roe_avg"):
        legacy.compute(bars)
    result = quality.compute(bars).set_index("date")["value"]
    assert result.to_dict() == pytest.approx({dates[0]: .1, dates[1]: -.05})
    ttm = build_custom_factor("ttm", expression="roe_ttm")
    pd.testing.assert_frame_equal(ttm.compute(bars), default_registry().get("roe_ttm").compute(bars))


@pytest.mark.parametrize("window", [60, 120, 250])
def test_annualized_volatility_matches_rules_on_sparse_history(window):
    dates = pd.bdate_range("2024-01-01", periods=window + 7)
    days = np.arange(len(dates))
    bars = pd.DataFrame({
        "trade_date": dates, "symbol": "S", "adjusted_close": 10 + days / 100 + np.sin(days / 3) / 10,
    })
    bars.loc[[1, 4, window + 2], "adjusted_close"] = np.nan
    never_eligible = bars.iloc[:3].assign(symbol="T")
    factor = default_registry().get(f"volatility_{window}")
    assert factor.min_history == window + 1
    result = factor.compute(pd.concat((bars, never_eligible))).set_index("date")
    assert list(result.index) == list(bars.dropna(subset=["adjusted_close"]).trade_date.iloc[window:])
    assert set(result.symbol) == {"S"}
    for day, row in result.iterrows():
        history = bars.loc[bars.trade_date.le(day)]
        from_rule = indicator_value(history, IndicatorSpec("volatility", window))
        raw_returns = history.adjusted_close.dropna().tail(window + 1).pct_change(fill_method=None)
        assert row.value == pytest.approx(from_rule)
        assert row.value == pytest.approx(raw_returns.std() * np.sqrt(244))
