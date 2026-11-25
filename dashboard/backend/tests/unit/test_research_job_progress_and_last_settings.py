"""Unit tests for factor research background progress, job category isolation, and latest backtest settings."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app import database
from app.quant import backtest_jobs as jobs, compute
from app.routes.backtests import _latest_user_backtest_settings
from quant_platform.application.factor_research_service import research_combination
from quant_platform.core import progress
from quant_platform.factors.registry import default_registry


class _StubRepo:
    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def get_daily_bars(self, symbols=None, end_date=None, **kwargs):
        frame = self._bars.copy()
        if symbols:
            frame = frame[frame["symbol"].isin(symbols)]
        if end_date is not None:
            frame = frame[pd.to_datetime(frame["trade_date"]) <= pd.Timestamp(end_date)]
        return frame

    def read_table(self, name: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self) -> pd.DataFrame:
        return pd.DataFrame()


def test_research_combination_reports_monotonic_step_progress():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2023-01-02", periods=140)
    symbols = [f"00000{i}.SZ" for i in range(1, 9)]
    rows = []
    for idx, sym in enumerate(symbols):
        prices = 10.0 * np.cumprod(1.0 + rng.normal(0.0005 * (idx - 3), 0.015, size=len(dates)))
        for day, price in zip(dates, prices, strict=True):
            rows.append(
                {
                    "trade_date": day,
                    "symbol": sym,
                    "raw_open": float(price),
                    "raw_high": float(price * 1.01),
                    "raw_low": float(price * 0.99),
                    "raw_close": float(price),
                    "adjusted_close": float(price),
                    "pre_close": float(price),
                    "volume": 100_000.0,
                    "amount": float(price * 100_000.0),
                }
            )
    repo = _StubRepo(pd.DataFrame(rows))
    reg = default_registry()
    components = (reg.get("momentum_20"), reg.get("volatility_20"))

    events: list[tuple[str, int, int]] = []
    with progress.reporting(lambda stage, done, total: events.append((stage, done, total))):
        result = research_combination(
            repo,
            components,
            train_start=dates[30].date(),
            train_end=dates[90].date(),
            test_start=dates[91].date(),
            test_end=dates[-1].date(),
            mode="equal",
            horizon=5,
            n_groups=4,
        )

    assert not result.comparison.empty
    assert events, "Expected progress events during research_combination"
    totals = {total for _, _, total in events}
    assert len(totals) == 1 and next(iter(totals)) > 0
    done_seq = [done for _, done, _ in events]
    assert done_seq == sorted(done_seq), f"Progress must be monotonic, got {done_seq}"
    assert done_seq[-1] == next(iter(totals))


def test_factor_research_job_category_isolation_and_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id,name,email,password_hash,salt,created_at) VALUES(1,'u','u@test','x','x',?)",
            (database._now(),),
        )

    bt = jobs.enqueue(1, {"kind": "backtest", "label": "回测", "request": {"a": 1}, "snapshot": {}})
    fac = jobs.enqueue(1, {"kind": "factor", "label": "单因子", "request": {"a": 1}, "snapshot": {}})
    res = jobs.enqueue(1, {"kind": "factor_research", "label": "组合研究", "request": {"a": 1}, "snapshot": {}})

    assert [j["id"] for j in jobs.list_jobs(1, category="backtest")["items"]] == [bt["id"]]
    assert [j["id"] for j in jobs.list_jobs(1, category="factor")["items"]] == [fac["id"]]
    assert [j["id"] for j in jobs.list_jobs(1, category="factor_research")["items"]] == [res["id"]]
    assert compute.job_timeout_seconds("factor_research") == compute.job_timeout_seconds("factor")


def test_latest_user_backtest_settings_reads_most_recent_unarchived_run(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id,name,email,password_hash,salt,created_at) VALUES(1,'u','u@test','x','x',?)",
            (database._now(),),
        )
        payload = {
            "effective_config": {
                "market": "000906.SH",
                "from_date": "2020-01-01",
                "to_date": "2025-12-31",
                "initial_capital": 2_000_000,
                "max_positions": 20,
                "rebalance": "quarterly",
                "hold_buffer": 20,
                "execution": {"commission_rate": 0.00025, "slippage_rate": 0.001, "historical_fees": True},
                "filters": {"exclude_st": True, "exclude_suspended": True, "minimum_listing_days": 250},
            }
        }
        conn.execute(
            "INSERT INTO backtests(user_id,strategy,market,from_date,to_date,status,result,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (1, "factor_composite", "000906.SH", "2020-01-01", "2025-12-31", "完成", json.dumps(payload), database._now()),
        )

    latest = _latest_user_backtest_settings(1)
    assert latest is not None
    assert latest["market"] == "000906.SH"
    assert latest["max_positions"] == 20
    assert latest["rebalance"] == "quarterly"
    assert latest["hold_buffer"] == 20
    assert latest["execution"]["slippage_rate"] == pytest.approx(0.001)
    assert latest["filters"]["minimum_listing_days"] == 250
