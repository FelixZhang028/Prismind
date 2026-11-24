"""Unit tests for per-year backtest breakdown and annualized turnover."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.quant.backtest_annual import backtest_annual_breakdown
from test_research_integrity import api, save_run  # noqa: F401 - pytest fixture


def test_annual_breakdown_chains_returns_matches_benchmark_and_turnover(tmp_path: Path):
    run_dir = tmp_path / "run_1"
    run_dir.mkdir()

    # 2024: 100 -> 120 (+20%); 2025: 120 -> 90 (peak 120 -> 90, -25% ret, 25% dd) -> 108 (-10% ret from 120)
    nav = pd.DataFrame({
        "trade_date": pd.to_datetime([
            "2024-01-02", "2024-06-03", "2024-12-31",
            "2025-01-02", "2025-06-03", "2025-12-31",
        ]),
        "equity": [100.0, 110.0, 120.0, 100.0, 90.0, 108.0],
        "benchmark_equity": [100.0, 105.0, 110.0, 110.0, 100.0, 121.0],
    })
    nav.to_parquet(run_dir / "nav.parquet")

    # 2024 双边成交额 = 110 * 2 = 220，日均权益 = 110 -> 单边换手 220 / (2*110) = 100%
    # 2025 双边成交额 = 99.3333... * 2? 用精确整数：日均权益 = (100+90+108)/3 = 99.3333...
    fills = pd.DataFrame({
        "trade_date": pd.to_datetime(["2024-01-02", "2024-06-03", "2025-01-02"]),
        "symbol": ["600000.SH", "600000.SH", "000001.SZ"],
        "side": ["BUY", "SELL", "BUY"],
        "price": [10.0, 12.0, 10.0],
        "quantity": [10, 10, 20],  # 2024 notional = 100 + 120 = 220; 2025 notional = 200
    })
    fills.to_parquet(run_dir / "fills.parquet")
    (run_dir / "summary.json").write_text(
        json.dumps({
            "benchmark_symbol": "000300.SH",
            "portfolio_turnover": 1.85,
            "annualized_turnover": 2.40,
        }),
        encoding="utf-8",
    )

    breakdown = backtest_annual_breakdown(run_dir, {})
    assert breakdown is not None
    assert breakdown["annualized_turnover"] == 240.0
    assert breakdown["portfolio_turnover"] == 185.0
    assert breakdown["benchmark_name"] == "沪深 300"
    assert len(breakdown["rows"]) == 2

    y2024, y2025 = breakdown["rows"]
    assert y2024["year"] == 2024
    assert y2024["trading_days"] == 3
    assert y2024["return_pct"] == 20.0
    assert y2024["benchmark_return_pct"] == 10.0
    assert y2024["excess_return_pct"] == 10.0
    assert y2024["max_drawdown_pct"] == 0.0
    assert y2024["turnover_pct"] == 100.0
    assert y2024["fills"] == 2

    # 2025 以上年末 120 为基期：108/120 - 1 = -10.0%，最大回撤 (120-90)/120 = 25.0%
    assert y2025["year"] == 2025
    assert y2025["return_pct"] == -10.0
    assert y2025["benchmark_return_pct"] == 10.0  # 121 / 110 - 1
    assert y2025["excess_return_pct"] == -20.0
    assert y2025["max_drawdown_pct"] == 25.0
    assert y2025["fills"] == 1
    # 各年复利连乘应等于全区间总收益：1.2 * 0.9 - 1 = +8%
    chained = (1 + y2024["return_pct"] / 100) * (1 + y2025["return_pct"] / 100) - 1
    assert chained == pytest.approx(0.08, abs=1e-6)


def test_get_backtest_backfills_annualized_turnover_and_annual_breakdown(api):  # noqa: F811
    client, _, _ = api
    directory = save_run(api, 1, dates=["2024-12-30", "2024-12-31", "2025-01-02"], equity=[100.0, 110.0, 121.0])
    fills = pd.DataFrame({
        "trade_date": pd.to_datetime(["2024-12-30", "2025-01-02"]),
        "symbol": ["600000.SH", "600000.SH"],
        "side": ["BUY", "SELL"],
        "price": [10.0, 11.0],
        "quantity": [10, 10],
    })
    fills.to_parquet(directory / "fills.parquet")

    resp = client.get("/api/v1/backtests/1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["annual_breakdown"] is not None
    assert [r["year"] for r in body["annual_breakdown"]["rows"]] == [2024, 2025]
    assert body["result"]["annualized_turnover"] is not None
    assert body["result"]["annualized_turnover"] > 0


def test_compare_runs_includes_per_year_returns_matrix(api):  # noqa: F811
    client, _, _ = api
    save_run(api, 1, dates=["2024-12-30", "2024-12-31", "2025-01-02"], equity=[100.0, 110.0, 121.0])
    save_run(api, 2, dates=["2024-12-30", "2024-12-31", "2025-01-02"], equity=[100.0, 95.0, 114.0])

    resp = client.post("/api/v1/runs/compare", json={"run_ids": ["run-1", "run-2"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    annual = body["annual_returns"]
    assert [row["year"] for row in annual] == [2024, 2025]
    assert annual[0]["run-1"] == pytest.approx(10.0)
    assert annual[0]["run-2"] == pytest.approx(-5.0)
    assert annual[1]["run-1"] == pytest.approx(10.0)
    assert annual[1]["run-2"] == pytest.approx(20.0)
