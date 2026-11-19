"""Neutralization coverage diagnostics and index-scoped fundamentals backfill."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from app.quant.result_adapter import factor_report_to_dict
from app.routes import workspace
from quant_platform.application import data_jobs
from quant_platform.data.fundamentals import FUNDAMENTALS_TABLE, STORED_COLUMNS
from quant_platform.data.fundamentals_backfill import BaoStockFundamentalsBackfill
from quant_platform.data.index_constituents import (
    CONSTITUENTS_TABLE,
    CSI_800,
    index_member_windows,
)
from quant_platform.data.industry import EXPOSURES_TABLE
from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository
from quant_platform.factors.evaluation import FactorEvaluator
from quant_platform.factors.registry import default_registry

INDUSTRIES = ["J66货币金融服务", "C15酒、饮料和精制茶制造业", "C38电气机械和器材制造业"]
SYMBOLS = [f"{number:06d}.SZ" for number in range(1, 16)]


def _two_year_market(tmp_path, *, pub_date: str):
    days = pd.bdate_range("2024-10-01", "2025-03-31")
    rng = np.random.default_rng(11)
    repo = ParquetMarketDataRepository(tmp_path / "market")
    frames = []
    for index, symbol in enumerate(SYMBOLS):
        drift = 0.002 * (index % 3 - 1)
        close = 10 * np.cumprod(1 + drift + rng.normal(0, 0.01, len(days)))
        frames.append(
            pd.DataFrame({
                "symbol": symbol,
                "trade_date": days,
                "raw_open": close,
                "raw_high": close * 1.01,
                "raw_low": close * 0.99,
                "raw_close": close,
                "pre_close": close,
                "volume": 1e5,
                "amount": 1e6,
                "adjusted_close": close,
                "adj_factor": 1.0,
                "quality_status": "OK",
                "source": "baostock",
            })
        )
    repo.save_table("daily_bars", pd.concat(frames, ignore_index=True))
    repo.save_table(
        EXPOSURES_TABLE,
        pd.DataFrame([
            {
                "symbol": symbol,
                "date": pd.Timestamp("2024-09-30"),
                "industry": INDUSTRIES[i % 3],
                "sector": INDUSTRIES[i % 3][0],
                "source": "baostock",
            }
            for i, symbol in enumerate(SYMBOLS)
        ]),
    )
    reports = []
    for index, symbol in enumerate(SYMBOLS):
        row = {col: np.nan for col in STORED_COLUMNS}
        row.update(
            symbol=symbol,
            stat_date=pd.Timestamp("2024-12-31"),
            pub_date=pd.Timestamp(pub_date),
            total_shares=1e8 * (index + 1),
            source="baostock",
        )
        reports.append(row)
    repo.save_table(FUNDAMENTALS_TABLE, pd.DataFrame(reports, columns=STORED_COLUMNS))
    return repo, days


def test_neutralization_coverage_reports_yearly_breakdown_and_warns_when_late_size_only(tmp_path):
    repo, _ = _two_year_market(tmp_path, pub_date="2025-01-15")
    factor = default_registry().get("momentum_20")
    report = FactorEvaluator(repo).evaluate(
        factor, date(2024, 11, 1), date(2025, 3, 28), horizon=1, n_groups=5, neutralization="both"
    )
    cov = report.neutralization_coverage
    assert cov is not None
    assert cov["mode"] == "both"
    assert cov["requested_start"] == "2024-11-01"
    assert cov["requested_end"] == "2025-03-28"
    assert cov["effective_start"] == "2025-01-15"
    assert cov["effective_end"] == "2025-03-28"
    assert cov["industry_coverage"] == pytest.approx(1.0)
    assert cov["size_coverage"] < 0.65
    assert cov["joint_coverage"] == pytest.approx(cov["size_coverage"])
    assert cov["insufficient"] is True
    assert "2025-01-15 至 2025-03-28" in cov["warning"]
    assert "总股本" in cov["warning"]

    by_year = {row["year"]: row for row in cov["yearly"]}
    assert set(by_year) == {2024, 2025}
    assert by_year[2024]["industry_coverage"] == pytest.approx(1.0)
    assert by_year[2024]["size_coverage"] == pytest.approx(0.0)
    assert by_year[2024]["joint_coverage"] == pytest.approx(0.0)
    assert by_year[2024]["effective_days"] == 0
    assert by_year[2025]["effective_days"] > 40

    payload = factor_report_to_dict(report)
    assert payload["neutralization_coverage"]["insufficient"] is True
    assert len(payload["neutralization_coverage"]["yearly"]) == 2


def test_neutralization_coverage_is_clean_when_full_and_absent_when_none(tmp_path):
    repo, _ = _two_year_market(tmp_path, pub_date="2024-10-15")
    factor = default_registry().get("momentum_20")
    evaluator = FactorEvaluator(repo)

    full = evaluator.evaluate(
        factor, date(2024, 11, 1), date(2025, 3, 28), horizon=1, n_groups=5, neutralization="both"
    )
    cov = full.neutralization_coverage
    assert cov is not None and cov["insufficient"] is False and cov["warning"] == ""
    assert cov["industry_coverage"] == pytest.approx(1.0)
    assert cov["size_coverage"] == pytest.approx(1.0)
    assert cov["joint_coverage"] == pytest.approx(1.0)
    assert cov["skipped_days"] == 0

    ind_only = evaluator.evaluate(
        factor, date(2024, 11, 1), date(2025, 3, 28), horizon=1, n_groups=5, neutralization="industry"
    )
    assert ind_only.neutralization_coverage["size_coverage"] is None
    assert ind_only.neutralization_coverage["industry_coverage"] == pytest.approx(1.0)

    size_only = evaluator.evaluate(
        factor, date(2024, 11, 1), date(2025, 3, 28), horizon=1, n_groups=5, neutralization="size"
    )
    assert size_only.neutralization_coverage["industry_coverage"] is None
    assert size_only.neutralization_coverage["size_coverage"] == pytest.approx(1.0)

    none_report = evaluator.evaluate(
        factor, date(2024, 11, 1), date(2025, 3, 28), horizon=1, n_groups=5, neutralization="none"
    )
    assert none_report.neutralization_coverage is None
    assert factor_report_to_dict(none_report)["neutralization_coverage"] is None


def _sample_constituents():
    return pd.DataFrame([
        # HS300: 600519 stayed throughout; 000001 joined in 2020-06-15
        {"index_symbol": "000300.SH", "effective_date": pd.Timestamp("2016-01-04"), "symbol": "600519.SH", "source": "baostock"},
        {"index_symbol": "000300.SH", "effective_date": pd.Timestamp("2020-06-15"), "symbol": "600519.SH", "source": "baostock"},
        {"index_symbol": "000300.SH", "effective_date": pd.Timestamp("2020-06-15"), "symbol": "000001.SZ", "source": "baostock"},
        # ZZ500: 000002 was only a member from 2016-01-04 to 2018-06-11
        {"index_symbol": "000905.SH", "effective_date": pd.Timestamp("2016-01-04"), "symbol": "000002.SZ", "source": "baostock"},
        {"index_symbol": "000905.SH", "effective_date": pd.Timestamp("2018-06-11"), "symbol": "000003.SZ", "source": "baostock"},
    ])


def test_index_member_windows_prioritizes_hs300_and_trims_backfill_quarters(tmp_path):
    constituents = _sample_constituents()
    windows = index_member_windows(constituents, CSI_800, date(2016, 1, 1), date(2022, 12, 31))
    # HS300 members come first (000001.SZ, 600519.SH), then ZZ500-only members (000002.SZ, 000003.SZ).
    assert list(windows) == ["000001.SZ", "600519.SH", "000002.SZ", "000003.SZ"]
    # 000001.SZ entered 2020-06-15 -> lead-in (370d) starts 2019-06-11, skipping 2015..2018.
    assert windows["000001.SZ"] == [(date(2019, 6, 11), date(2022, 12, 31))]
    # 000002.SZ exited 2018-06-11 -> ends at 2018-06-11, skipping 2019..2022.
    assert windows["000002.SZ"] == [(date(2014, 12, 30), date(2018, 6, 11))]

    repo = ParquetMarketDataRepository(tmp_path / "market")
    days = pd.bdate_range("2015-01-05", "2022-12-30")
    repo.save_table(
        "daily_bars",
        pd.concat(
            [pd.DataFrame({"symbol": sym, "trade_date": days, "raw_close": 10.0}) for sym in windows],
            ignore_index=True,
        ),
    )
    planned = dict(
        BaoStockFundamentalsBackfill(repo, today=date(2023, 1, 1)).plan(
            date(2016, 1, 1), date(2022, 12, 31), symbols=list(windows), symbol_windows=windows
        )
    )
    # 600519.SH includes 2014 Q4 (lead-in before 2016-01-01) so day-1 market cap is populated.
    assert (2014, 4) in planned["600519.SH"]
    assert (2015, 3) in planned["600519.SH"]
    # 000001.SZ skips 2015..2018 entirely and starts at 2019 Q2.
    assert all(year >= 2019 for year, _ in planned["000001.SZ"])
    assert (2019, 2) in planned["000001.SZ"]
    # 000002.SZ stops in 2018 and does not request 2019+.
    assert all(year <= 2018 for year, _ in planned["000002.SZ"])


def test_index_scope_route_and_job_attempt(tmp_path, monkeypatch):
    repo = ParquetMarketDataRepository(tmp_path / "market")
    started = []
    jobs = SimpleNamespace(
        start=lambda start, end, datasets, symbols=None, trigger="admin", fundamentals_index=None: (
            started.append((start, end, datasets, symbols, fundamentals_index))
            or {"id": "j1", "status": "STARTING"}
        )
    )
    monkeypatch.setattr(workspace, "_data_jobs", lambda: jobs)
    monkeypatch.setattr(workspace, "market_repository", lambda: repo)
    monkeypatch.setattr(workspace.audit, "record", lambda *args, **kwargs: None)
    admin = {"id": 1, "is_admin": True}

    body = {"start_date": "2016-01-01", "end_date": "2022-12-31", "datasets": ["fundamentals"], "scope": "hs300"}
    # Missing index constituents -> 409
    with pytest.raises(HTTPException) as exc:
        workspace.data_jobs_start(body, admin)
    assert exc.value.status_code == 409
    # Unknown scope -> 422
    with pytest.raises(HTTPException) as exc:
        workspace.data_jobs_start({**body, "scope": "bogus"}, admin)
    assert exc.value.status_code == 422

    repo.save_table(CONSTITUENTS_TABLE, _sample_constituents())
    assert workspace.data_jobs_start(body, admin)["status"] == "STARTING"
    assert started[-1] == (date(2016, 1, 1), date(2022, 12, 31), ["fundamentals"], None, "000300.SH")
    assert workspace.data_jobs_start({**body, "scope": "csi800"}, admin)["status"] == "STARTING"
    assert started[-1] == (date(2016, 1, 1), date(2022, 12, 31), ["fundamentals"], None, CSI_800)

    captured = []
    service = SimpleNamespace(
        app={"app": {"runtime_dir": str(tmp_path)}},
        repository=repo,
        backfill_fundamentals=lambda start, end, symbols=None, symbol_windows=None, progress=None: (
            captured.append((symbols, symbol_windows)) or {"failed": {}, "reports": 12}
        ),
    )
    monkeypatch.setattr("quant_platform.application.data_service.DataCenterService", lambda config: service)
    folder = tmp_path / "job"
    folder.mkdir()
    job = {
        "config": "configs/app.yaml",
        "start_date": "2016-01-01",
        "end_date": "2022-12-31",
        "datasets": ["fundamentals"],
        "fundamentals_index": CSI_800,
    }
    assert data_jobs.attempt(folder, job) == 0
    assert captured and captured[0][0] == ["000001.SZ", "600519.SH", "000002.SZ", "000003.SZ"]
    assert captured[0][1]["000001.SZ"] == [(date(2019, 6, 11), date(2022, 12, 31))]
