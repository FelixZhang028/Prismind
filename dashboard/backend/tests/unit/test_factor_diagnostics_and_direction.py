"""Tests for factor diagnostics (annual IC, HAC t/p, style correlations) and per-factor direction overrides."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.quant.result_adapter import factor_report_to_dict
from app.routes import workspace
from quant_platform.application.factor_research_service import research_combination
from quant_platform.factors.base import FactorDefinition
from quant_platform.factors.evaluation import FactorEvaluator
from quant_platform.factors.sample import FactorSampleFilters
from test_research_integrity import api  # noqa: F401 - pytest fixture


def _trading_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    cur = start
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


class _SyntheticFactorRepo:
    def __init__(self, bars: pd.DataFrame, fundamentals: pd.DataFrame | None = None) -> None:
        self._bars = bars.copy()
        self._fundamentals = fundamentals.copy() if fundamentals is not None else pd.DataFrame()

    def get_daily_bars(
        self,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        extras: tuple[str, ...] | list[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._bars
        mask = pd.Series(True, index=frame.index)
        if symbols is not None:
            mask &= frame["symbol"].isin(symbols)
        if start_date is not None:
            mask &= frame["trade_date"] >= pd.Timestamp(start_date)
        if end_date is not None:
            mask &= frame["trade_date"] <= pd.Timestamp(end_date)
        result = frame.loc[mask].copy()
        # 模拟真实仓库：只返回核心列 + 本次 extras 请求的扩展列，用来严格回归验证缺失列不会被覆盖丢掉
        base_cols = [c for c in result.columns if c not in {"turnover_rate", "pe_ttm", "pb_mrq"}]
        requested = [c for c in (extras or ()) if c in result.columns]
        return result[base_cols + requested]

    def get_fundamentals(self) -> pd.DataFrame:
        return self._fundamentals.copy()

    def read_table(self, name: str) -> pd.DataFrame:
        return pd.DataFrame()


def _make_multi_year_panel() -> tuple[pd.DataFrame, pd.DataFrame, list[date]]:
    """Build 2024 + 2025 synthetic cross-sectional panel (10 stocks, 90 trading days)."""
    days = _trading_days(date(2024, 10, 15), 90)
    symbols = [f"0000{i:02d}.SZ" for i in range(1, 11)]
    rng = np.random.default_rng(42)
    rows = []
    fund_rows = []
    for idx, symbol in enumerate(symbols):
        # 股票编号越小市值越小、长期涨幅越强（构造可预测的小盘/低价结构）
        shares = 1e8 * (idx + 1) ** 2
        fund_rows.append(
            {
                "symbol": symbol,
                "stat_date": pd.Timestamp("2024-06-30"),
                "pub_date": pd.Timestamp("2024-08-31"),
                "total_shares": shares,
            }
        )
        drift = 0.0025 - idx * 0.0004
        vol = 0.008 + idx * 0.002
        rets = rng.normal(drift, vol, len(days))
        prices = 10.0 * np.cumprod(1.0 + rets)
        for day_i, (d, p) in enumerate(zip(days, prices, strict=True)):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp(d),
                    "raw_close": float(p),
                    "adjusted_close": float(p),
                    "volume": float(1e6 * (idx + 1)),
                    "amount": float(1e6 * (idx + 1) * p),
                    "turnover_rate": float(1.0 + idx * 0.4 + 0.01 * (day_i % 5)),
                    "pe_ttm": float(8.0 + idx * 3.0),
                    "pb_mrq": float(1.0 + idx * 0.35),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(fund_rows), days


class _SmallCapProxyFactor(FactorDefinition):
    """Factor positively scoring smaller-cap / lower-PE stocks."""

    name = "small_cap_proxy"
    display_name = "小盘测试因子"
    direction = 1

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        # 构造与市值严格负相关的横截面信号
        order = bars["symbol"].astype(str).str.slice(0, 6).astype(float)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(bars["trade_date"]).dt.normalize(),
                "symbol": bars["symbol"],
                "value": -order,
            }
        )


class _InverseSignalFactor(FactorDefinition):
    """Defined as direction=+1, but higher values predict LOWER returns (needs direction=-1 flip)."""

    name = "inverse_alpha"
    display_name = "需反转测试因子"
    direction = 1

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        order = bars["symbol"].astype(str).str.slice(0, 6).astype(float)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(bars["trade_date"]).dt.normalize(),
                "symbol": bars["symbol"],
                "value": order,
            }
        )


def test_factor_report_exposes_annual_ic_hac_significance_and_style_correlations():
    bars, fundamentals, days = _make_multi_year_panel()
    repo = _SyntheticFactorRepo(bars, fundamentals)
    report = FactorEvaluator(repo).evaluate(
        _SmallCapProxyFactor(name="small_cap_proxy", display_name="小盘测试因子", direction=1),
        days[25],
        days[-1],
        horizon=3,
        n_groups=5,
        diagnostics=True,
    )
    payload = factor_report_to_dict(report)

    # 1. HAC 显著性透传
    sig = payload["significance"]
    assert sig["observations"] >= 20
    assert sig["hac_t"] is not None
    assert sig["hac_p"] is not None
    assert 0.0 <= sig["positive_ratio"] <= 1.0

    # 2. 分年份 Rank IC 透传（跨 2024 和 2025 两年）
    years = {row["year"] for row in payload["annual"]}
    assert years == {2024, 2025}
    for row in payload["annual"]:
        assert row["observations"] > 0
        assert row["rank_ic"] is not None

    # 3. 常见风格相关性速查：准确识别强小盘/低波/低估值重合
    styles = {row["style"]: row for row in payload["style_correlations"]}
    assert "ln_market_cap" in styles
    assert styles["ln_market_cap"]["correlation"] < -0.9
    assert styles["ln_market_cap"]["tilt"] == "偏小盘"
    assert styles["ln_market_cap"]["high_overlap"] is True
    assert "ep_ttm" in styles
    assert styles["ep_ttm"]["correlation"] > 0.9
    assert styles["ep_ttm"]["tilt"] == "偏低估值"
    assert "volatility_20" in styles


def test_research_combination_honors_custom_directions_for_training_and_testing():
    bars, fundamentals, days = _make_multi_year_panel()
    repo = _SyntheticFactorRepo(bars, fundamentals)
    f_good = _SmallCapProxyFactor(name="small_cap_proxy", display_name="小盘测试因子", direction=1)
    f_inv = _InverseSignalFactor(name="inverse_alpha", display_name="需反转测试因子", direction=1)

    # 默认正向时：_InverseSignalFactor 的单因子 Rank IC 应为负
    plain = research_combination(
        repo,
        (f_good, f_inv),
        train_start=days[0],
        train_end=days[45],
        test_start=days[46],
        test_end=days[-1],
        mode="equal",
        horizon=3,
        n_groups=5,
    )
    inv_label = f"单因子 · {f_inv.display_name} ({f_inv.name})"
    plain_ic = plain.reports[inv_label].rank_ic_mean

    # 手动将 _InverseSignalFactor 切换为反向 (-1)：单因子 IC 精确取反，且 spec 记录 direction=-1
    flipped = research_combination(
        repo,
        (f_good, f_inv),
        train_start=days[0],
        train_end=days[45],
        test_start=days[46],
        test_end=days[-1],
        mode="equal",
        custom_directions={f_good.name: 1, f_inv.name: -1},
        horizon=3,
        n_groups=5,
    )
    flipped_ic = flipped.reports[inv_label].rank_ic_mean
    assert flipped_ic == pytest.approx(-plain_ic, abs=1e-9)
    spec_by_name = {item["name"]: item for item in flipped.spec}
    assert spec_by_name[f_good.name]["direction"] == 1
    assert spec_by_name[f_inv.name]["direction"] == -1

    # 非法方向必须被明确拒绝
    for bad_dir in ({f_inv.name: 0}, {f_inv.name: 2}, {f_inv.name: True}, {"unknown_factor": -1}):
        with pytest.raises(ValueError):
            research_combination(
                repo,
                (f_good, f_inv),
                train_start=days[0],
                train_end=days[45],
                test_start=days[46],
                test_end=days[-1],
                mode="equal",
                custom_directions=bad_dir,
                horizon=3,
                n_groups=5,
            )


def test_factor_research_and_composite_api_propagate_directions(api, monkeypatch):
    client, _, root = api
    bars, fundamentals, days = _make_multi_year_panel()
    repo = _SyntheticFactorRepo(bars, fundamentals)
    repo.root = root  # type: ignore[attr-defined]
    monkeypatch.setattr(workspace, "market_repository", lambda: repo)
    monkeypatch.setattr(workspace, "local_data_bounds", lambda: (days[0], days[-1]))
    monkeypatch.setattr(
        workspace,
        "_factor_scope",
        lambda user, universe, start, end, submitted_symbols=None: (repo, sorted(bars["symbol"].unique())),
    )

    resp_comp = client.post(
        "/api/v1/factors/composite",
        json={
            "factor_names": ["momentum_20", "volatility_20"],
            "weight_mode": "equal",
            "directions": {"momentum_20": -1, "volatility_20": 1},
            "corr_threshold": 0.99,
            "start_date": days[25].isoformat(),
            "end_date": days[-1].isoformat(),
            "train_end": days[55].isoformat(),
            "test_start": days[56].isoformat(),
            "horizon": 3,
            "n_groups": 5,
        },
    )
    assert resp_comp.status_code == 200, resp_comp.text
    comp_data = resp_comp.json()
    spec = {item["name"]: item for item in comp_data["composite_spec"]}
    assert spec["momentum_20"]["direction"] == -1
    assert spec["volatility_20"]["direction"] == 1
    assert "significance" in comp_data["report"]
    assert "annual" in comp_data["report"]

    resp_res = client.post(
        "/api/v1/factors/research",
        json={
            "factor_names": ["momentum_20", "volatility_20"],
            "weight_mode": "equal",
            "directions": {"momentum_20": -1, "volatility_20": -1},
            "train_start": days[25].isoformat(),
            "train_end": days[55].isoformat(),
            "test_start": days[56].isoformat(),
            "test_end": days[-1].isoformat(),
            "horizon": 3,
            "n_groups": 5,
        },
    )
    assert resp_res.status_code == 200, resp_res.text
    res_spec = {item["name"]: item for item in resp_res.json()["composite_spec"]}
    assert res_spec["momentum_20"]["direction"] == -1
    assert res_spec["volatility_20"]["direction"] == -1


class _ValuationLikeFactor(FactorDefinition):
    """Factor requiring pe_ttm/pb_mrq (like roe_ttm) so initial bars lack only turnover_rate."""

    required_fields: tuple[str, ...] = ("pe_ttm", "pb_mrq")

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        val = pd.to_numeric(bars["pb_mrq"], errors="coerce") / pd.to_numeric(bars["pe_ttm"], errors="coerce")
        return pd.DataFrame(
            {
                "date": pd.to_datetime(bars["trade_date"]).dt.normalize(),
                "symbol": bars["symbol"],
                "value": val,
            }
        )


def test_style_correlations_preserve_valuation_styles_for_fundamental_factors():
    bars, fundamentals, days = _make_multi_year_panel()
    repo = _SyntheticFactorRepo(bars, fundamentals)
    factor = _ValuationLikeFactor(
        name="roe_like_test",
        display_name="ROE 代理",
        direction=1,
        required_fields=("pe_ttm", "pb_mrq"),
    )
    report = FactorEvaluator(repo).evaluate(
        factor, days[25], days[-1], horizon=3, n_groups=5, diagnostics=True
    )
    styles = {row["style"] for row in report.style_correlations}
    # 关键回归：加载 turnover_rate 补全时绝不能把原有的 pe_ttm / pb_mrq 覆盖丢掉
    assert {"ln_market_cap", "volatility_20", "momentum_20", "turnover_20", "ep_ttm", "bp_mrq"}.issubset(styles)


def test_factor_evaluation_cost_bps_and_limit_move_filter():
    bars, fundamentals, days = _make_multi_year_panel()
    bars["up_limit"] = bars["raw_close"] * 1.10
    bars["down_limit"] = bars["raw_close"] * 0.90
    # 制造部分涨停日：前两只股票在部分交易日封死涨停
    limit_dates = {pd.Timestamp(d) for d in days[30:40]}
    hit_mask = bars["symbol"].isin(["000001.SZ", "000002.SZ"]) & bars["trade_date"].isin(limit_dates)
    bars.loc[hit_mask, "up_limit"] = bars.loc[hit_mask, "raw_close"]
    repo = _SyntheticFactorRepo(bars, fundamentals)

    factor = _SmallCapProxyFactor(name="small_cap_proxy", display_name="小盘测试因子", direction=1)
    report = FactorEvaluator(repo).evaluate(
        factor,
        days[25],
        days[-1],
        horizon=3,
        n_groups=5,
        diagnostics=True,
        filters=FactorSampleFilters(exclude_limit_moves=True),
        cost_bps=15.0,
    )
    assert any("排除涨跌停" in note for note in report.notes)
    assert report.cost_summary is not None
    assert report.cost_summary["cost_bps"] == 15.0
    assert report.cost_summary["net_top_return"] < report.cost_summary["gross_top_return"]
    assert report.cost_summary["net_long_short_total"] < report.cost_summary["gross_long_short_total"]
    assert "net_G5" in report.group_nav.columns
    assert "net_long_short" in report.group_nav.columns

    payload = factor_report_to_dict(report)
    assert payload["cost_summary"]["cost_bps"] == 15.0
    assert payload["cost_summary"]["net_long_short_total"] < payload["cost_summary"]["gross_long_short_total"]


def test_closed_loop_status_caches_by_parquet_mtime(api, monkeypatch, tmp_path):
    client, _, _ = api
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    pq = market_dir / "sample.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(pq)
    calls = {"count": 0}

    class _FakeService:
        def __init__(self) -> None:
            self.repository = type("Repo", (), {"root": market_dir})()
            self.app = {}

        def closed_loop_status(self):
            calls["count"] += 1
            return {"bars_symbols": 100, "call": calls["count"]}

    workspace._closed_loop_cache = None
    monkeypatch.setattr(workspace, "build_data_center_service", lambda user: _FakeService())

    first = client.get("/api/v1/data-center/closed-loop")
    second = client.get("/api/v1/data-center/closed-loop")
    assert first.status_code == 200 and second.status_code == 200
    assert calls["count"] == 1
    assert second.json()["call"] == 1

    # 更新 parquet 文件后缓存必须自动失效
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(pq)
    third = client.get("/api/v1/data-center/closed-loop")
    assert third.status_code == 200
    assert calls["count"] == 2
    assert third.json()["call"] == 2


