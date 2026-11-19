"""P0 可靠性与量化严谨性修复回归测试。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import database
from app.quant import backup, run_evidence
from quant_platform.accounts.account import Account
from quant_platform.application.daily_update import DailyUpdate
from quant_platform.backtest.engine import BacktestEngine
from quant_platform.backtest.validity import CURRENT_AUDIT_VERSION
from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository
from quant_platform.execution.next_open import ExecutionConfig, NextOpenExecutionModel
from quant_platform.execution.order_generator import OrderGenerator
from quant_platform.portfolio.equal_weight import EqualWeightPortfolio
from quant_platform.portfolio.risk_weighted import RiskWeightedPortfolio
from quant_platform.research import event_study as es
from quant_platform.risk.basic_rules import (
    PortfolioRiskAction,
    RiskDecision,
    evaluate_daily_portfolio_risk,
)
from quant_platform.risk.config import RiskLimits
from quant_platform.signals.models import Signal
from quant_platform.universe.a_share import AShareUniverse, AShareUniverseConfig

DAY = date(2025, 3, 10)


# --------------------------------------------------------------------------- #
# 1. 风控优先级：清仓 > 减仓 > 停止新委托
# --------------------------------------------------------------------------- #


def test_daily_loss_or_missing_industry_never_blocks_drawdown_liquidate_or_reduce():
    weights = {"000001.SZ": 0.4, "600519.SH": 0.4}
    limits_liq = RiskLimits(
        max_daily_loss=0.05,
        max_drawdown=0.20,
        drawdown_action="liquidate",
        max_industry_weight=0.5,
    )
    liq = evaluate_daily_portfolio_risk(
        weights,
        limits_liq,
        strategy_id="s",
        trade_date=DAY,
        current_drawdown=-0.21,
        daily_return=-0.06,
        industry_map={},
    )
    assert liq.decision == RiskDecision.ADJUST
    assert liq.action == PortfolioRiskAction.LIQUIDATE
    assert liq.targets == ()
    assert any("单日亏损" in r for r in liq.reasons)
    assert any("缺少当时可得行业" in r for r in liq.reasons)
    assert any("执行清仓" in r for r in liq.reasons)

    limits_red = RiskLimits(
        max_daily_loss=0.05,
        max_drawdown=0.20,
        drawdown_action="reduce",
        drawdown_target_weight=0.40,
    )
    red = evaluate_daily_portfolio_risk(
        weights,
        limits_red,
        strategy_id="s",
        trade_date=DAY,
        current_drawdown=-0.22,
        daily_return=-0.06,
    )
    assert red.decision == RiskDecision.ADJUST
    assert red.action == PortfolioRiskAction.REDUCE
    assert sum(t.target_weight for t in red.targets) == pytest.approx(0.40)
    assert any("单日亏损" in r for r in red.reasons)
    assert any("仓位降至不高于 40%" in r for r in red.reasons)

    only_loss = evaluate_daily_portfolio_risk(
        weights,
        limits_liq,
        strategy_id="s",
        trade_date=DAY,
        current_drawdown=-0.10,
        daily_return=-0.06,
        industry_map={"000001.SZ": "银行", "600519.SH": "食品"},
    )
    assert only_loss.decision == RiskDecision.REJECT
    assert only_loss.action == PortfolioRiskAction.STOP_NEW


# --------------------------------------------------------------------------- #
# 2. 上市天数使用 list_date，预热窗口覆盖 minimum_history_days
# --------------------------------------------------------------------------- #


def test_minimum_listing_days_uses_list_date_instead_of_loaded_bar_count():
    days = pd.bdate_range("2025-01-02", periods=10)
    bars = pd.DataFrame(
        [
            {
                "symbol": "OLD.SH",
                "trade_date": d,
                "list_date": "2020-01-02",
                "amount": 1e8,
                "quality_status": "OK",
                "is_listed": True,
                "is_st": False,
                "is_suspended": False,
            }
            for d in days
        ]
        + [
            {
                "symbol": "YOUNG.SZ",
                "trade_date": d,
                "list_date": "2024-10-15",
                "amount": 1e8,
                "quality_status": "OK",
                "is_listed": True,
                "is_st": False,
                "is_suspended": False,
            }
            for d in days
        ]
    )
    universe = AShareUniverse(
        AShareUniverseConfig(
            symbols=("OLD.SH", "YOUNG.SZ"),
            minimum_listing_days=250,
            minimum_history_days=1,
            minimum_average_amount=0.0,
        )
    )
    universe.prepare(bars)
    assert universe.select(days[0].date(), bars) == ["OLD.SH"]

    # 未调用 prepare 时，select 路径也使用同一口径。
    direct = AShareUniverse(universe.config)
    assert direct.select(days[0].date(), bars) == ["OLD.SH"]

    # 引擎预热窗口自动覆盖 minimum_history_days + 20。
    long_hist = AShareUniverse(
        AShareUniverseConfig(symbols=("OLD.SH",), minimum_history_days=200)
    )
    engine = BacktestEngine(
        repository=SimpleNamespace(),
        universe=long_hist,
        strategy=SimpleNamespace(min_history=5),
        portfolio=EqualWeightPortfolio(top_n=1),
        order_generator=OrderGenerator(),
        execution_model=NextOpenExecutionModel(ExecutionConfig()),
        warmup_days=120,
    )
    assert engine.warmup_days >= 220


# --------------------------------------------------------------------------- #
# 3. 每日更新失败传播 & 覆盖率分母
# --------------------------------------------------------------------------- #


def test_daily_update_propagates_step_failures_and_counts_all_listed_stocks(tmp_path):
    today = date(2026, 10, 16)
    listed = [f"{i:06d}.SZ" for i in range(1, 101)]
    master = pd.DataFrame(
        {"symbol": listed, "list_date": ["2020-01-02"] * 100, "delist_date": [None] * 100}
    )
    # 100 只已上市，只有 50 只有行情（且都是最新）-> 必须判为落后。
    summary = pd.DataFrame(
        {"end": [pd.Timestamp("2026-10-15")] * 50},
        index=pd.Index(listed[:50], name="symbol"),
    )
    provider = SimpleNamespace(
        get_trade_calendar=lambda s, e: pd.DataFrame({"calendar_date": [today.isoformat()], "is_trading_day": ["1"]}),
        get_history_range=lambda sym, s, e, adjustflag: pd.DataFrame({"date": [today.isoformat()], "code": [sym]}),
        close=lambda: None,
    )
    backfill = SimpleNamespace(
        refresh_security_master=lambda: master,
        build_universe_membership=lambda: pd.DataFrame(),
        build_delisting_settlements=lambda: pd.DataFrame(),
    )
    service = SimpleNamespace(
        repository=SimpleNamespace(
            read_table=lambda name: master if name == "security_master" else pd.DataFrame(),
            daily_bar_summary=lambda: summary,
            daily_bar_bounds=lambda: (date(2020, 1, 2), today),
        ),
        sources=SimpleNamespace(baostock_provider=lambda: provider),
        full_market_backfill=lambda: backfill,
        update_market_data=lambda *a, **kw: SimpleNamespace(message="ok"),
        repair_benchmarks=lambda: {"removed": 0, "detail": "", "errors": []},
        update_benchmark=lambda *a, **kw: None,
        backfill_corporate_action_gaps=lambda progress=None: {"added": 0, "failed": {"000001.SZ": "超时"}},
        backfill_index_constituents=lambda s, e, progress=None: {"requests": 2, "failed": {"000300.SH": "限流"}},
        backfill_industry=lambda s, e, progress=None: {"snapshots": 1, "failed": {"2026-09-30": "网络断开"}},
    )
    state_path = tmp_path / "state.json"
    updater = DailyUpdate(service, state_path)
    assert updater._behind(date(2026, 10, 15)) is True

    result = updater.run(today)
    for step in ("corporate_actions", "index_constituents", "industry"):
        assert step in result["errors"]
        assert result["steps"][step]["failed_count"] == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for step in ("corporate_actions", "index_constituents", "industry"):
        assert step not in state["done"]


# --------------------------------------------------------------------------- #
# 4. 备份恢复（含 runs / agent_lab）与回测证据路径迁移
# --------------------------------------------------------------------------- #


def test_backup_and_restore_preserve_run_evidence_and_agent_lab(tmp_path, monkeypatch):
    db_file = tmp_path / "app.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, '研究员')")
    conn.commit()
    conn.close()

    runtime = tmp_path / "runtime"
    run_dir = runtime / "runs" / "run-alpha-1"
    run_dir.mkdir(parents=True)
    (run_dir / "validity_report.json").write_text(
        json.dumps({"audit_version": CURRENT_AUDIT_VERSION, "status": "VALID", "metrics_reliable": True, "issues": []}),
        encoding="utf-8",
    )
    (runtime / "app-secret.key").write_text("top-secret", encoding="utf-8")
    agent_dir = runtime / "agent_lab" / "user_1"
    agent_dir.mkdir(parents=True)
    (agent_dir / "prior_knowledge.json").write_text('{"notes":["不要追高"]}', encoding="utf-8")

    backup_dir = tmp_path / "backups"
    linked_pairs: list[tuple[Path, Path]] = []
    real_link = backup.os.link

    def tracked_link(src, dst):
        linked_pairs.append((Path(src), Path(dst)))
        return real_link(src, dst)

    monkeypatch.setattr(backup.os, "link", tracked_link)
    first = backup.backup(date(2026, 11, 18), root=backup_dir, database=db_file, runtime=runtime)
    second = backup.backup(date(2026, 11, 19), root=backup_dir, database=db_file, runtime=runtime)
    assert first is not None and second is not None
    assert (first / "runs" / "run-alpha-1" / "validity_report.json").is_file()
    assert (second / "runs" / "run-alpha-1" / "validity_report.json").is_file()
    assert (first / "agent_lab" / "user_1" / "prior_knowledge.json").is_file()
    # 未变更的 run 文件在次日备份中尝试复用硬链接（受限环境自动降级复制）。
    assert any(dst.name == "validity_report.json" for _, dst in linked_pairs)

    # 删掉原数据后从备份恢复。
    db_file.unlink()
    import shutil

    shutil.rmtree(runtime)
    summary = backup.restore(first, database=db_file, runtime=runtime)
    assert set(summary["restored"]) >= {"app.db", "app-secret.key", "runs", "agent_lab"}
    assert (runtime / "agent_lab" / "user_1" / "prior_knowledge.json").read_text(encoding="utf-8") == '{"notes":["不要追高"]}'

    monkeypatch.setattr(run_evidence, "RUNTIME_ROOT", runtime)
    evidence = run_evidence.run_evidence({"output_dir": "runs/run-alpha-1"})
    assert evidence["validity_status"] == "VALID"
    assert evidence["metrics_reliable"] is True


def test_run_directory_relocates_legacy_release_paths_and_blocks_traversal(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "runtime"
    actual = runtime / "runs" / "run-001"
    actual.mkdir(parents=True)
    monkeypatch.setattr(run_evidence, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(run_evidence, "BACKEND_ROOT", tmp_path)

    assert run_evidence.relative_run_dir(actual) == "runs/run-001"
    assert run_evidence.run_directory({"output_dir": "runs/run-001"}) == actual.resolve()
    # 旧版本目录已被删除，仍能按 runs/<id> 重定位到当前 RUNTIME_ROOT。
    old_release = "/opt/prismind/releases/20261001/dashboard/backend/data/runtime/runs/run-001"
    assert run_evidence.run_directory({"output_dir": old_release}) == actual.resolve()
    # 路径穿越与非法目录一律拒绝。
    assert run_evidence.run_directory({"output_dir": "runs/../app-secret.key"}) is None
    assert run_evidence.run_directory({"output_dir": "/etc/passwd"}) is None

    # init_db 自动把可对上的历史绝对路径迁移成相对路径 runs/<id>。
    db_path = tmp_path / "data" / "app.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, name, email, password_hash, salt, created_at) VALUES (1, 'u', 'u@e.test', 'h', 's', 'now')"
        )
        conn.execute(
            "INSERT INTO backtests (id, user_id, strategy, market, from_date, to_date, status, result, created_at) "
            "VALUES (1, 1, 's', 'm', '2025-01-02', '2025-06-30', '完成', ?, 'now')",
            (json.dumps({"output_dir": old_release}),),
        )
    database.init_db()
    with database.get_conn() as conn:
        migrated = json.loads(conn.execute("SELECT result FROM backtests WHERE id = 1").fetchone()["result"])
    assert migrated["output_dir"] == "runs/run-001"


# --------------------------------------------------------------------------- #
# 5. 事件研究：行业不向后偷看、次日开盘入场、日期聚类显著性检验
# --------------------------------------------------------------------------- #


def test_event_study_no_industry_bfill_next_open_entry_and_significance(tmp_path):
    days = pd.bdate_range("2024-01-01", periods=320)
    rows = []
    # 构造 10 只股票，其中 2 只在不同日期多次触发大跌后显著反弹，另 8 只横盘。
    event_indices = [120, 145, 170, 195, 220, 245]
    for idx in range(10):
        symbol = f"6002{idx:02d}.SH"
        close = np.full(len(days), 10.0)
        raw_open = np.full(len(days), 10.0)
        up_limit = np.full(len(days), 11.0)
        if idx < 2:
            for pos in event_indices:
                close[pos - 5 : pos + 1] = np.linspace(10.0, 7.5, 6)
                raw_open[pos - 5 : pos + 1] = close[pos - 5 : pos + 1]
                # 股票 0 次日正常开盘在 8.0 并涨回 10.0；股票 1 在第一个事件日次日一字涨停买不到。
                raw_open[pos + 1] = 8.0
                up_limit[pos + 1] = 8.25
                if idx == 1 and pos == event_indices[0]:
                    raw_open[pos + 1] = 8.25  # 次日一字涨停
                close[pos + 1 : pos + 21] = np.linspace(8.2, 10.0, 20)
        rows.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "trade_date": days,
                    "adjusted_close": close,
                    "raw_close": close,
                    "raw_open": raw_open,
                    "amount": 1e8,
                    "is_st": False,
                    "is_suspended": False,
                    "up_limit": up_limit,
                    "down_limit": close * 0.9,
                }
            )
        )
    repo = ParquetMarketDataRepository(tmp_path / "market")
    repo.save_table("daily_bars", pd.concat(rows, ignore_index=True))
    # 行业首次记录晚于前几个事件日：不应向后偷看填回早期。
    repo.save_table(
        "security_exposures",
        pd.DataFrame(
            {
                "symbol": ["600200.SH"],
                "date": [days[210]],
                "industry": ["J66货币金融服务"],
                "sector": ["J"],
            }
        ),
    )

    cond = [{"type": "ret", "days": 5, "op": "<=", "value": -20}]
    res_open = es.run(
        repo,
        {"conditions": cond, "entry": "next_open", "start": days[100].date().isoformat()},
        pool=[],
        names={},
    )
    h20 = res_open["horizons"]["20"]
    assert res_open["entry"] == "next_open"
    assert h20["untradable_entry"] >= 1
    assert h20["significance"]["event_days"] >= 5
    assert h20["significance"]["significant"] is True
    assert h20["significance"]["p_value"] < 0.05

    # 行业筛选在首次记录日（days[210]）之前的事件不应被计入。
    early_only = es.run(
        repo,
        {
            "conditions": cond,
            "industries": ["货币金融服务"],
            "start": days[100].date().isoformat(),
            "end": days[205].date().isoformat(),
        },
        pool=[],
        names={},
    )
    assert early_only["events"] == 0

    # 当天涨停用收盘价口径时提示无法按涨停收盘买入。
    limit_res = es.run(
        repo,
        {"conditions": [{"type": "limit", "direction": "up"}], "start": days[100].date().isoformat()},
        pool=[],
        names={},
    )
    assert any("次日开盘" in note for note in limit_res["notes"])


# --------------------------------------------------------------------------- #
# 6. 买单按信号得分优先级撮合（不再按股票代码字典序挤掉高分股票）
# --------------------------------------------------------------------------- #


def test_buy_orders_execute_by_signal_priority_not_symbol_alphabetical_order():
    signals = [
        Signal("s", DAY, "688001.SH", "SCORE", score=0.95),
        Signal("s", DAY, "000001.SZ", "SCORE", score=0.20),
    ]
    targets = EqualWeightPortfolio(top_n=2).construct(signals)
    # 账号现金刚好只够买一只股票（每只目标约 50,000，但次日高开后总共只够买一只）。
    account = Account("s", initial_cash=60_000.0)
    orders = OrderGenerator(lot_size=100).generate(
        targets=targets,
        account=account,
        signal_date=DAY,
        execution_date=date(2025, 3, 11),
        closing_prices={"688001.SH": 10.0, "000001.SZ": 10.0},
    )
    # 高分股 688001.SH 的 priority 更靠前。
    buy_symbols = [o.symbol for o in orders]
    assert buy_symbols == ["688001.SH", "000001.SZ"]

    bars = pd.DataFrame(
        [
            {
                "symbol": sym,
                "trade_date": pd.Timestamp("2025-03-11"),
                "raw_open": 10.5,
                "volume": 1_000_000.0,
                "liquidity_volume": 1_000_000.0,
                "is_suspended": False,
                "quality_status": "OK",
                "up_limit": 12.0,
                "down_limit": 8.0,
                "adj_factor": 1.0,
            }
            for sym in ("000001.SZ", "688001.SH")
        ]
    )
    # 打乱传入顺序，验证执行模型按 priority 优先买入 688001.SH。
    _, fills = NextOpenExecutionModel(ExecutionConfig(slippage_rate=0.0, impact_coefficient=0.0)).execute(
        list(reversed(orders)), bars, account
    )
    assert fills[0].symbol == "688001.SH"
    assert "688001.SH" in account.positions


# --------------------------------------------------------------------------- #
# 7. MVO 尊重策略信号得分 & 收缩协方差在大股票数下稳定收敛
# --------------------------------------------------------------------------- #


def test_mean_variance_uses_strategy_signal_scores_and_handles_high_dimension():
    rng = np.random.default_rng(42)
    days = pd.bdate_range("2025-01-02", periods=65)
    # 资产 A 过去 60 天下跌但策略给高分；资产 B 过去 60 天上涨但策略给低分。
    # 两者波动率相近，MVO 必须把更高权重分配给策略看好的资产 A，而非追涨历史均值 B。
    noise_a = rng.normal(-0.002, 0.015, size=len(days))
    noise_b = rng.normal(0.003, 0.015, size=len(days))
    price_a = 10.0 * np.cumprod(1.0 + noise_a)
    price_b = 10.0 * np.cumprod(1.0 + noise_b)
    history = pd.concat(
        [
            pd.DataFrame({"symbol": "A.SH", "trade_date": days, "adjusted_close": price_a}),
            pd.DataFrame({"symbol": "B.SH", "trade_date": days, "adjusted_close": price_b}),
        ],
        ignore_index=True,
    )
    signals = [
        Signal("s", days[-1].date(), "A.SH", "SCORE", score=2.0),
        Signal("s", days[-1].date(), "B.SH", "SCORE", score=-1.0),
    ]
    targets = RiskWeightedPortfolio(top_n=2, method="mean_variance", lookback=60).construct_with_history(
        signals, history
    )
    weights = {t.symbol: t.target_weight for t in targets}
    assert weights["A.SH"] > weights["B.SH"]

    # 高维小样本场景（45 只股票、30 天收益，样本协方差奇异）下，收缩协方差仍能稳定收敛。
    short_days = pd.bdate_range("2025-01-02", periods=31)
    many_frames = []
    many_signals = []
    for i in range(45):
        ret = rng.normal(0.0, 0.02, size=len(short_days))
        many_frames.append(
            pd.DataFrame(
                {
                    "symbol": f"60{i:04d}.SH",
                    "trade_date": short_days,
                    "adjusted_close": 10.0 * np.cumprod(1.0 + ret),
                }
            )
        )
        many_signals.append(Signal("s", short_days[-1].date(), f"60{i:04d}.SH", "SCORE", score=float(45 - i)))
    many_targets = RiskWeightedPortfolio(top_n=45, method="mean_variance", lookback=30).construct_with_history(
        many_signals, pd.concat(many_frames, ignore_index=True)
    )
    assert sum(t.target_weight for t in many_targets) == pytest.approx(1.0, abs=1e-6)
