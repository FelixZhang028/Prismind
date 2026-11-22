"""Tests for Plan D: backtest plain-Chinese health check card (回测白话体检卡)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.quant.backtest_health import backtest_health_check
from test_strategy_workflow import api, create_template, workflow  # noqa: F401 - pytest fixtures


def _write_run(
    run_dir: Path,
    *,
    nav_rows: list[dict],
    trade_rows: list[dict] | None = None,
    position_rows: list[dict] | None = None,
    summary: dict | None = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(nav_rows).to_parquet(run_dir / "nav.parquet", index=False)
    if trade_rows is not None:
        pd.DataFrame(trade_rows).to_parquet(run_dir / "trades.parquet", index=False)
    if position_rows is not None:
        pd.DataFrame(position_rows).to_parquet(run_dir / "positions.parquet", index=False)
    if summary is not None:
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def test_health_check_flags_single_stock_luck_cost_fragility_industry_concentration_and_long_underwater(tmp_path):
    run_dir = tmp_path / "risky_run"
    start = date(2024, 1, 2)
    nav_rows = []
    pos_rows = []
    # 135 个交易日：第 1 天冲高 115 万，随后连续 130+ 天水下不创新高，最终 108 万（净赚 8 万，但费用高达 9 万！）
    for i in range(135):
        day = start + timedelta(days=i)
        if i == 0:
            eq, mv = 1_000_000.0, 900_000.0
        elif i == 1:
            eq, mv = 1_150_000.0, 1_000_000.0
        elif i < 20:
            eq, mv = 1_050_000.0, 0.0  # 18 天空仓
        else:
            eq, mv = 1_080_000.0, 950_000.0
        nav_rows.append({"trade_date": pd.Timestamp(day), "equity": eq, "market_value": mv})
        if mv > 0:
            pos_rows.append(
                {
                    "trade_date": pd.Timestamp(day),
                    "symbol": "000001.SZ",
                    "quantity": 10000,
                    "average_cost": 10.0,
                    "close": 10.0,
                    "market_value": 650_000.0,
                }
            )
            pos_rows.append(
                {
                    "trade_date": pd.Timestamp(day),
                    "symbol": "000002.SZ",
                    "quantity": 10000,
                    "average_cost": 10.0,
                    "close": 10.0,
                    "market_value": 300_000.0,
                }
            )

    # 单股运气：000001.SZ 赚了 12 万，其余股票亏 4 万 -> 去掉 000001.SZ 收益直接转负！
    trade_rows = [
        {"symbol": "000001.SZ", "net_pnl": 120_000.0},
        {"symbol": "000002.SZ", "net_pnl": -25_000.0},
        {"symbol": "000003.SZ", "net_pnl": -15_000.0},
    ]
    summary = {
        "initial_cash": 1_000_000.0,
        "final_equity": 1_080_000.0,
        "total_transaction_cost": 90_000.0,
    }
    _write_run(run_dir, nav_rows=nav_rows, trade_rows=trade_rows, position_rows=pos_rows, summary=summary)

    exposures = pd.DataFrame(
        [
            {"symbol": "000001.SZ", "date": pd.Timestamp("2023-12-31"), "industry": "电子"},
            {"symbol": "000002.SZ", "date": pd.Timestamp("2023-12-31"), "industry": "电子"},
        ]
    )
    fundamentals = pd.DataFrame(
        [
            {"symbol": "000001.SZ", "stat_date": pd.Timestamp("2023-09-30"), "pub_date": pd.Timestamp("2023-10-30"), "total_shares": 4e8},
            {"symbol": "000002.SZ", "stat_date": pd.Timestamp("2023-09-30"), "pub_date": pd.Timestamp("2023-10-30"), "total_shares": 5e8},
        ]
    )

    health = backtest_health_check(
        run_dir,
        {"effective_config": {"initial_capital": 1_000_000.0}},
        names={"000001.SZ": "平安银行", "000002.SZ": "万科A"},
        exposures=exposures,
        fundamentals=fundamentals,
    )
    items = {item["key"]: item for item in health["items"]}

    assert health["summary_status"] == "warn"
    assert "4 项高风险提醒" == health["summary_badge"]

    assert items["single_stock"]["status"] == "warn"
    assert items["single_stock"]["tag"] == "高度依赖单股"
    assert "平安银行" in items["single_stock"]["headline"]
    assert items["single_stock"]["metrics"]["return_without_top1"] < 0

    assert items["cost_stress"]["status"] == "warn"
    assert items["cost_stress"]["tag"] == "对成本高度敏感"
    assert items["cost_stress"]["metrics"]["doubled_cost_return"] < 0

    assert items["exposure_bias"]["status"] == "warn"
    assert items["exposure_bias"]["tag"] == "行业高度集中"
    assert items["exposure_bias"]["metrics"]["size_bucket"] == "small"

    assert items["drawdown_endurance"]["status"] == "warn"
    assert items["drawdown_endurance"]["metrics"]["max_underwater_days"] >= 120
    assert items["drawdown_endurance"]["metrics"]["underwater_unrecovered"] is True
    assert items["drawdown_endurance"]["metrics"]["empty_days"] == 18


def test_health_check_recognizes_healthy_diversified_run_and_handles_legacy_without_dir(tmp_path):
    run_dir = tmp_path / "healthy_run"
    start = date(2025, 1, 2)
    nav_rows = [
        {"trade_date": pd.Timestamp(start + timedelta(days=i)), "equity": 1_000_000.0 + i * 5_000.0, "market_value": 900_000.0}
        for i in range(30)
    ]
    # 6 只不同行业大盘股均匀贡献盈利，总收益 14.5 万，总费用仅 4000 元
    trade_rows = [
        {"symbol": f"00000{i}.SZ", "net_pnl": 24_000.0}
        for i in range(1, 7)
    ]
    pos_rows = [
        {
            "trade_date": pd.Timestamp(start + timedelta(days=d)),
            "symbol": f"00000{i}.SZ",
            "quantity": 1000,
            "average_cost": 50.0,
            "close": 50.0,
            "market_value": 150_000.0,
        }
        for d in range(30)
        for i in range(1, 7)
    ]
    summary = {"initial_cash": 1_000_000.0, "final_equity": 1_145_000.0, "total_transaction_cost": 4_000.0}
    _write_run(run_dir, nav_rows=nav_rows, trade_rows=trade_rows, position_rows=pos_rows, summary=summary)

    exposures = pd.DataFrame(
        [
            {"symbol": f"00000{i}.SZ", "date": pd.Timestamp("2024-12-31"), "industry": f"行业{i}"}
            for i in range(1, 7)
        ]
    )
    fundamentals = pd.DataFrame(
        [
            {"symbol": f"00000{i}.SZ", "stat_date": pd.Timestamp("2024-09-30"), "pub_date": pd.Timestamp("2024-10-30"), "total_shares": 2e9}
            for i in range(1, 7)
        ]
    )

    health = backtest_health_check(run_dir, {}, exposures=exposures, fundamentals=fundamentals)
    assert health["summary_status"] == "ok"
    assert health["summary_badge"] == "四项体检整体稳健"
    assert all(item["status"] == "ok" for item in health["items"])

    # 无运行目录的旧记录也不应崩溃，仍能算出成本压力和回撤时长
    legacy = backtest_health_check(
        None,
        {
            "effective_config": {"initial_capital": 1_000_000.0},
            "equity": [1_000_000.0, 1_050_000.0, 1_030_000.0, 1_080_000.0],
            "nav_dates": ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"],
            "total_cost": 3_000.0,
        },
    )
    legacy_items = {item["key"]: item for item in legacy["items"]}
    assert legacy_items["cost_stress"]["status"] == "ok"
    assert legacy_items["drawdown_endurance"]["status"] == "ok"
    assert legacy_items["single_stock"]["status"] == "neutral"


def test_backtest_detail_api_includes_health_check(workflow):
    client, *_ = workflow
    saved, _ = create_template(client)
    resp = client.post(
        "/api/v1/backtests",
        json={
            "strategy": f"package:{saved['package_id']}",
            "market": "当前股票池",
            "from_date": "2025-01-01",
            "to_date": "2025-12-31",
            "initial_capital": 250000,
            "max_positions": 5,
            "rebalance": "weekly",
        },
    )
    assert resp.status_code == 201, resp.text
    detail = client.get(f"/api/v1/backtests/{resp.json()['id']}")
    assert detail.status_code == 200
    health = detail.json().get("health_check")
    assert isinstance(health, dict)
    assert len(health["items"]) == 4
    assert {item["key"] for item in health["items"]} == {
        "single_stock",
        "cost_stress",
        "exposure_bias",
        "drawdown_endurance",
    }
