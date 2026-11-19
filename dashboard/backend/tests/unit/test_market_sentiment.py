"""Daily market sentiment, limit-move ecology, anomalies, caching, and route tests."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app.quant import market_sentiment as sentiment_cache
from app.routes import workspace
from quant_platform.ai_research.market_sentiment import (
    build_daily_sentiment_table,
    build_sentiment_payload,
    industry_sentiment,
)
from quant_platform.data.industry import EXPOSURES_TABLE
from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository


def _synthetic_market(tmp_path, n_days: int = 70, n_stocks: int = 12):
    repo = ParquetMarketDataRepository(tmp_path / "market")
    days = pd.bdate_range("2025-01-02", periods=n_days)
    symbols = [f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]
    rows = []
    for s_idx, sym in enumerate(symbols):
        price = 10.0 + s_idx * 0.5
        for d_idx, day in enumerate(days):
            pre = price
            # Mild steady upward drift so MA20/MA60 are well-defined.
            ret = 0.005 if (s_idx + d_idx) % 3 != 0 else -0.003
            is_susp = False
            up_lim = round(pre * 1.10, 2)
            dn_lim = round(pre * 0.90, 2)

            # Craft specific limit-up, streak, burst, and surge sessions near the end.
            if d_idx == n_days - 3 and s_idx < 3:
                # 3 stocks hit limit up on T-2
                close = up_lim
                high = up_lim
                amt = 2e8
            elif d_idx == n_days - 2:
                if s_idx == 0:
                    # 1 stock promotes to 2-day streak
                    close = up_lim
                    high = up_lim
                elif s_idx in (1, 2):
                    # 2 yesterday limit-up stocks gain +4% next day
                    close = round(pre * 1.04, 2)
                    high = close
                elif s_idx == 3:
                    # 1 stock touches limit-up intraday then closes below (burst)
                    close = round(pre * 1.03, 2)
                    high = up_lim
                else:
                    close = round(pre * 1.02, 2)
                    high = close
                amt = 3e8
            elif d_idx == n_days - 1:
                # Final day: broad volume surge + broad rally (all non-suspended up)
                if s_idx == n_stocks - 1:
                    is_susp = True
                    close = pre
                    high = pre
                    amt = 0.0
                else:
                    close = round(pre * 1.03, 2)
                    high = close
                    amt = 6e8  # ~3x normal amount -> triggers vol_surge
            else:
                close = round(pre * (1 + ret), 2)
                high = round(close * 1.01, 2)
                amt = 1e8

            rows.append({
                "symbol": sym,
                "trade_date": day,
                "raw_open": pre,
                "raw_high": high,
                "raw_low": min(pre, close),
                "raw_close": close,
                "pre_close": pre,
                "adjusted_close": close,
                "volume": 1e6,
                "amount": amt,
                "is_suspended": is_susp,
                "is_st": False,
                "up_limit": up_lim,
                "down_limit": dn_lim,
                "source": "baostock",
            })
            price = close

    bars = pd.DataFrame(rows)
    repo.save_table("daily_bars", bars)

    bm_rows = []
    for code, drift in (("000300.SH", 0.002), ("000905.SH", 0.003)):
        px = 3000.0
        for day in days:
            pre = px
            px = round(pre * (1 + drift), 2)
            bm_rows.append({"symbol": code, "trade_date": day, "raw_close": px, "pre_close": pre})
    repo.save_table("benchmark_bars", pd.DataFrame(bm_rows))

    # Two industries: 6 stocks in Software, 6 stocks in Banking (both >= MIN_INDUSTRY_STOCKS=5).
    repo.save_table(
        EXPOSURES_TABLE,
        pd.DataFrame([
            {
                "symbol": sym,
                "date": pd.Timestamp("2024-12-31"),
                "industry": "I65软件和信息技术服务业" if i < 6 else "J66货币金融服务",
                "sector": "I" if i < 6 else "J",
                "source": "baostock",
            }
            for i, sym in enumerate(symbols)
        ]),
    )
    return repo, days, bars


def test_daily_sentiment_metrics_streaks_burst_and_anomalies(tmp_path):
    repo, days, _ = _synthetic_market(tmp_path, n_days=70, n_stocks=12)
    table = build_daily_sentiment_table(repo)
    assert len(table) == 70

    # Check T-1 (n_days - 2): 1 limit-up (2-day streak), 1 burst -> burst_rate = 0.5, prev_limit_up_ret positive.
    t_minus_1 = table.iloc[-2]
    assert int(t_minus_1["limit_up"]) == 1
    assert int(t_minus_1["burst_count"]) == 1
    assert t_minus_1["burst_rate"] == pytest.approx(0.5)
    assert int(t_minus_1["max_streak"]) == 2
    assert t_minus_1["promotion_rate"] == pytest.approx(1 / 3)
    assert t_minus_1["prev_limit_up_ret"] > 0.04

    # Check final day: 11 trading stocks all up, 1 suspended, MA20/MA60 defined.
    last = table.iloc[-1]
    assert int(last["total"]) == 11
    assert int(last["up"]) == 11
    assert int(last["suspended"]) == 1
    assert last["up_ratio"] == pytest.approx(1.0)
    assert 0.0 <= last["above_ma20_ratio"] <= 1.0
    assert 0.0 <= last["above_ma60_ratio"] <= 1.0

    payload = build_sentiment_payload(table, repo, window=60)
    assert payload["latest"]["day"] == days[-1].date().isoformat()
    assert len(payload["series"]) == 60
    assert payload["series"][0]["hs300_cum"] == pytest.approx(0.0)
    # Volume surge & breadth surge triggered on final day
    today_rule_ids = {ev["rule_id"] for ev in payload["latest"]["today_anomalies"]}
    assert "vol_surge" in today_rule_ids
    assert "breadth_surge" in today_rule_ids
    # Every anomaly carries full-history stats table
    vol_ev = next(a for a in payload["anomalies"] if a["rule_id"] == "vol_surge")
    assert vol_ev["history"]["count"] >= 1
    assert [row["target"] for row in vol_ev["history"]["rows"]] == ["沪深 300", "中证 500", "全市场中位数"]


def test_incremental_update_matches_full_rebuild(tmp_path):
    repo, days, full_bars = _synthetic_market(tmp_path, n_days=68, n_stocks=8)
    # Build table on first 65 days, then extend with remaining 3 days
    partial_repo = ParquetMarketDataRepository(tmp_path / "partial")
    partial_repo.save_table("daily_bars", full_bars[full_bars["trade_date"] <= days[64]])
    first_table = build_daily_sentiment_table(partial_repo)
    assert len(first_table) == 65

    extended = build_daily_sentiment_table(repo, existing=first_table)
    rebuilt = build_daily_sentiment_table(repo)
    assert len(extended) == len(rebuilt) == 68
    for col in ("up", "down", "limit_up", "burst_count", "max_streak", "amount"):
        assert extended[col].tolist() == pytest.approx(rebuilt[col].tolist(), nan_ok=True)
    for col in ("prev_limit_up_ret", "above_ma20_ratio", "above_ma60_ratio"):
        assert extended[col].tail(3).tolist() == pytest.approx(rebuilt[col].tail(3).tolist(), nan_ok=True)


def test_industry_sentiment_and_cache_and_route(tmp_path, monkeypatch):
    repo, _, _ = _synthetic_market(tmp_path, n_days=30, n_stocks=12)
    inds = industry_sentiment(repo)
    assert len(inds) == 2
    assert {r["name"] for r in inds} == {"软件和信息技术服务业", "货币金融服务"}
    # Final day amount surged ~6x vs prior 20d avg
    assert all(r["vol_ratio_20"] > 2.0 for r in inds)
    assert sum(r["amount_share"] for r in inds) == pytest.approx(1.0, abs=1e-3)

    sentiment_cache.configure(tmp_path / "cache")
    monkeypatch.setattr(workspace, "market_repository", lambda: repo)
    admin = {"id": 1, "is_admin": True}

    res = workspace.market_sentiment_report(window=60, user=admin)
    assert res["latest"]["total"] == 11
    assert (tmp_path / "cache" / "daily_sentiment.parquet").exists()

    # Home summary reads immediately from cache
    summary = sentiment_cache.home_summary(repo)
    assert summary is not None and summary["amount_ratio_20"] > 2.0

    # Invalid window rejected with 422
    with pytest.raises(HTTPException) as exc:
        workspace.market_sentiment_report(window=99, user=admin)
    assert exc.value.status_code == 422
