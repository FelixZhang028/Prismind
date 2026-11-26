"""模拟账户：锁住创建时的设置，从创建当天开始，按本地最新行情推进。"""
import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app import database
from app.routes import paper, workspace
from app.quant import runtime
from quant_platform.application.backtest_service import BacktestRequest
from quant_platform.backtest.validity import CURRENT_AUDIT_VERSION
from quant_platform.risk.config import RiskLimits
from quant_platform.strategies.templates import beginner_templates
from test_research_integrity import api  # noqa: F401 - fixture

TODAY = date(2026, 10, 28)


class Calendar:
    def __init__(self, days):
        self.days = days

    def read_table(self, name):
        assert name == "trade_calendar"
        return pd.DataFrame({"cal_date": pd.to_datetime(self.days), "is_open": 1})


@pytest.fixture
def env(api, monkeypatch):  # noqa: F811
    client, connect, root = api
    client.app.include_router(paper.router)

    state = SimpleNamespace(requests=[], universes=[], pool=["600000.SH", "000001.SZ"], fail=None,
                            bounds=(date(2020, 1, 2), TODAY), calendar=[TODAY], jobs=[],
                            risk=RiskLimits(max_drawdown=0.2))
    defaults = BacktestRequest("rule_builder", "x", {}, date(2025, 1, 1), date(2025, 12, 31), 1e6, 10, "weekly")

    def build(user):
        configs = {"universe": {"universe": {"symbols": list(state.pool), "filters": {"exclude_st": True}}}}

        def run(request):
            if state.fail:
                raise ValueError(state.fail)
            state.requests.append(request)
            state.universes.append(json.loads(json.dumps(configs["universe"]["universe"])))
            run_id = f"r{len(state.requests)}"
            directory = root / "runs" / run_id
            directory.mkdir(parents=True)
            days = pd.bdate_range(request.start_date, request.end_date)
            fills = pd.DataFrame({"trade_date": [days[-1]], "symbol": ["600000.SH"], "side": ["BUY"],
                                  "quantity": [100], "price": [10.0], "commission": [5.0], "stamp_tax": [0.0], "slippage": [0.0]})
            fills.to_parquet(directory / "fills.parquet")
            (directory / "validity_report.json").write_text(json.dumps({
                "audit_version": CURRENT_AUDIT_VERSION, "status": "VALID", "metrics_reliable": True, "issues": []}))
            return SimpleNamespace(output_dir=directory, config_snapshot={}, result=SimpleNamespace(
                summary={"cumulative_return": 0.01, "max_drawdown": -0.25, "final_equity": request.initial_cash * 1.01,
                         "metrics_reliable": True},
                nav=pd.DataFrame({"trade_date": days, "equity": [request.initial_cash] * len(days)}),
                fills=fills, positions=pd.DataFrame(), run_id=run_id))

        return SimpleNamespace(configs=configs, default_request=lambda: defaults, run=run, runs_root=root / "runs")

    monkeypatch.setattr(paper, "get_conn", connect)
    monkeypatch.setattr(runtime, "get_conn", connect)
    monkeypatch.setattr(paper, "build_backtest_service", build)
    monkeypatch.setattr(paper, "local_data_bounds", lambda: state.bounds)
    monkeypatch.setattr(paper, "market_repository", lambda: Calendar(state.calendar))
    monkeypatch.setattr(paper, "user_risk_limits", lambda _: state.risk)
    monkeypatch.setattr(paper, "security_names", lambda: {})
    monkeypatch.setattr(paper, "china_today", lambda: TODAY)
    monkeypatch.setattr(paper, "_data_jobs", lambda: SimpleNamespace(records=lambda: state.jobs))
    return client, connect, root, state


def save_package(client, top_n=5):
    template = beginner_templates()[0]
    response = client.post("/api/v1/packages", json={
        "definition": {"name": "placeholder", "entry_rules": []},
        "top_n": top_n, "rebalance": "weekly", "source": f"template:{template.template_id}", "style": "balanced"})
    assert response.status_code == 201, response.text
    return response.json()


def create(client, package_id, **extra):
    response = client.post("/api/v1/paper-accounts", json={"package_id": package_id, "initial_cash": 500000, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_latest_backtest_reference_uses_the_completed_run_owned_by_the_user(api):
    _, connect, _ = api
    config = {"strategy_reference": "package:p1", "market": "000906.SH", "max_positions": 30,
              "rebalance": "monthly", "initial_capital": 500_000, "strategy_parameters": {"unused": True}}
    with connect() as conn:
        conn.executemany(
            """INSERT INTO backtests (user_id, strategy, market, from_date, to_date, status, result, created_at)
               VALUES (?, '相同策略名', '000906.SH', '2025-01-01', '2025-06-01', ?, ?, '2025-06-02')""",
            [
                (1, "完成", json.dumps({"effective_config": config | {"max_positions": 10}})),
                (1, "完成", json.dumps({"effective_config": config})),
                (1, "失败", json.dumps({"effective_config": config})),
                (1, "完成", json.dumps({"effective_config": config | {"strategy_reference": "package:p2"}})),
                (2, "完成", json.dumps({"effective_config": config | {"max_positions": 45}})),
                (1, "完成", "invalid JSON"),
            ],
        )
    backtest = paper.latest_backtest_reference("p1", {"id": 1})["backtest"]
    assert backtest["id"] == 2
    assert backtest["created_at"] == "2025-06-02"
    assert backtest["config"] == {key: value for key, value in config.items() if key != "strategy_parameters"}
    assert paper.latest_backtest_reference("p2", {"id": 2}) == {"backtest": None}


def test_a_new_account_starts_today_and_waits_for_two_trading_days(env):
    client, _, _, state = env
    package = save_package(client)
    account = create(client, package["package_id"], top_n=3)
    assert (account["status"], account["start_date"], account["top_n"]) == ("WAITING", "2026-10-28", 3)
    assert account["result"] == {} and account["trades"] == []

    # 只有开始那一天的数据：开始日收盘调仓，下一个交易日才成交，还没有结果。
    waiting = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert waiting["status"] == "WAITING" and not state.requests

    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]
    active = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    request = state.requests[-1]
    assert (request.start_date, request.end_date, request.initial_cash, request.top_n) == (TODAY, date(2026, 10, 29), 500000, 3)
    assert request.risk_limits.max_positions == 3
    assert active["status"] == "ACTIVE" and active["last_date"] == "2026-10-29"
    assert active["result"]["effective_config"]["strategy_reference"] == f"paper:{account['account_id']}"
    assert [trade["symbol"] for trade in active["trades"]] == ["600000"]


def test_settings_are_locked_when_the_account_is_created(env):
    client, connect, _, state = env
    package = save_package(client)
    account = create(client, package["package_id"])

    # 之后改股票池、改风控、改策略规则，都不影响模拟账户。
    state.pool = ["300750.SZ"]
    state.risk = RiskLimits(max_drawdown=0.5)
    edited = beginner_templates()[1].presets["balanced"].definition.to_dict()
    with connect() as conn:
        conn.execute("UPDATE strategy_packages SET definition = ?, source = 'visual_builder'", (json.dumps(edited),))
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 30)), [TODAY, date(2026, 10, 29), date(2026, 10, 30)]
    detail = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()

    assert state.universes[-1]["symbols"] == ["600000.SH", "000001.SZ"]
    assert state.requests[-1].risk_limits.max_drawdown == 0.2
    locked = json.loads(state.requests[-1].strategy_parameters["definition_json"])
    assert locked == beginner_templates()[0].presets["balanced"].definition.to_dict()
    checks = {item["title"]: item for item in detail["checks"]}
    assert "修改过规则" in checks["策略规则"]["detail"]
    assert checks["风控"]["severity"] == "warning"  # 结果回撤 25% 超过了锁住的 20% 停止线
    assert "只运行了 3 个交易日" in checks["结果可信度"]["detail"]
    assert detail["market_label"] == "创建时的股票池（2 只）"


def test_failures_are_recorded_and_the_next_success_replaces_the_old_run(env):
    client, connect, root, state = env
    account = create(client, save_package(client)["package_id"])
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]
    first = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert (root / "runs" / "r1").exists()

    state.fail = "MISSING_CORPORATE_ACTION: 600000.SH 缺少分红送转记录"
    failed = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert failed["status"] == "FAILED" and "缺少分红明细" in failed["error"]
    assert failed["last_date"] == first["last_date"] and failed["result"]["run_id"] == "r1"

    state.fail = None
    again = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert again["status"] == "ACTIVE" and again["error"] is None and again["result"]["run_id"] == "r2"
    assert not (root / "runs" / "r1").exists() and (root / "runs" / "r2").exists()

    # K 线页用 paper-<编号> 读成交；删除账户时运行目录一起删掉。
    traded = client.get(f"/api/v1/runs/paper-{account['account_id']}/trades")
    assert traded.status_code == 200 and traded.json()["symbols"][0]["symbol"] == "600000"
    assert client.delete(f"/api/v1/paper-accounts/{account['account_id']}").status_code == 200
    assert not (root / "runs" / "r2").exists()
    assert client.get(f"/api/v1/paper-accounts/{account['account_id']}").status_code == 404


def test_accounts_are_private_and_limited(env, monkeypatch):
    client, connect, _, state = env
    package = save_package(client)
    for _ in range(3):
        create(client, package["package_id"])
    response = client.post("/api/v1/paper-accounts", json={"package_id": package["package_id"]})
    assert response.status_code == 409 and "最多 3 个" in response.json()["detail"]
    assert client.get("/api/v1/paper-accounts").json()["limit"] == 3

    with connect() as conn:
        conn.execute("UPDATE paper_accounts SET user_id = 2")
    assert client.get("/api/v1/paper-accounts").json()["items"] == []
    other = conn_account(connect)
    assert client.get(f"/api/v1/paper-accounts/{other}").status_code == 404
    assert client.post(f"/api/v1/paper-accounts/{other}/advance").status_code == 404
    assert client.delete(f"/api/v1/paper-accounts/{other}").status_code == 404
    assert client.get(f"/api/v1/runs/paper-{other}/trades").status_code == 404
    assert client.post("/api/v1/paper-accounts", json={"package_id": "missing"}).status_code == 404
    assert client.post("/api/v1/paper-accounts", json={"package_id": package["package_id"], "market": "火星"}).status_code == 422


def conn_account(connect):
    with connect() as conn:
        return conn.execute("SELECT account_id FROM paper_accounts LIMIT 1").fetchone()[0]


def test_manual_advance_waits_for_data_updates(env):
    client, _, _, state = env
    account = create(client, save_package(client)["package_id"])
    state.jobs = [{"status": "RUNNING"}]
    response = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance")
    assert response.status_code == 409 and "数据正在更新" in response.json()["detail"]


def test_background_advances_each_account_once_per_new_data_day(env):
    client, _, _, state = env
    package = save_package(client)
    first, second = (create(client, package["package_id"]) for _ in range(2))
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]
    jobs = SimpleNamespace(records=lambda: state.jobs)

    state.jobs = [{"status": "RUNNING"}]
    assert paper.advance_all(jobs) == 0 and not state.requests
    state.jobs = [{"status": "SUCCESS"}]
    assert paper.advance_all(jobs) == 2 and len(state.requests) == 2
    assert paper.advance_all(jobs) == 0 and len(state.requests) == 2  # 同一天的数据不再重算

    # 失败的账户等到有新的一天数据时再试，不会每次检查都重算。
    state.fail = "boom"
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 30)), [TODAY, date(2026, 10, 29), date(2026, 10, 30)]
    assert paper.advance_all(jobs) == 2
    assert {item["status"] for item in client.get("/api/v1/paper-accounts").json()["items"]} == {"FAILED"}
    assert paper.advance_all(jobs) == 0


def test_busy_server_leaves_the_account_for_the_next_check(env, monkeypatch):
    client, connect, _, state = env
    account = create(client, save_package(client)["package_id"])
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]

    def busy(_):
        raise HTTPException(status_code=429, detail="服务器正忙")

    monkeypatch.setattr(paper, "computing", busy)
    assert paper.advance_all(SimpleNamespace(records=lambda: [])) == 0
    with connect() as conn:
        row = conn.execute("SELECT status, attempted_date FROM paper_accounts").fetchone()
    assert (row["status"], row["attempted_date"]) == ("WAITING", None)


def test_the_unused_old_table_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute("CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, user_id INTEGER, account_id TEXT, strategy TEXT)")
    database.init_db()
    database.init_db()
    with sqlite3.connect(tmp_path / "app.db") as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_accounts)")}
    assert {"package", "universe", "risk_limits", "attempted_date"} <= columns


def test_an_all_cash_finish_shows_no_positions_instead_of_older_holdings():
    from app.quant.result_adapter import final_positions

    frame = pd.DataFrame({"trade_date": pd.to_datetime(["2026-08-06", "2026-08-07"]), "symbol": ["600000.SH"] * 2,
                          "quantity": [100, 100], "average_cost": [10.0, 10.0], "market_value": [1000.0, 1100.0], "close": [10.0, 11.0]})
    assert final_positions(frame, as_of="2026-10-27") == []
    held = final_positions(frame, as_of="2026-08-07")
    assert [(row["symbol"], row["price"], row["pnl"]) for row in held] == [("600000", 11.0, 100.0)]
    assert len(final_positions(frame)) == 1  # 不知道最后一天时保持原来的做法


def test_a_drawdown_line_of_100_percent_is_described_as_no_line():
    account = {"last_date": "2026-10-27", "package_id": "p", "risk_limits": json.dumps(RiskLimits(max_drawdown=1.0).to_dict()),
               "package": json.dumps(_package_dict())}
    checks = paper.account_checks(account, {"max_drawdown": 40.0, "equity": [1] * 80, "metrics_reliable": True},
                                  today=TODAY, latest=date(2026, 10, 27), current_package=None)
    risk = next(item for item in checks if item["title"] == "风控")
    assert "没有设回撤停止线" in risk["detail"] and risk["severity"] == "info"


def _package_dict():
    from datetime import datetime
    from quant_platform.application.strategy_studio_service import StrategyPackage

    preset = beginner_templates()[0].presets["balanced"]
    return StrategyPackage("p", "x", preset.definition, preset.top_n, preset.rebalance, "test", datetime(2026, 10, 28)).to_dict()


def test_factor_composite_account_creates_locks_and_advances(env):
    client, _, _, state = env
    factors_json = json.dumps([
        {"name": "momentum_20", "weight": 0.6, "direction": 1, "clip": True, "missing": "drop", "standardization": "rank"},
        {"name": "volatility_20", "weight": 0.4, "direction": -1, "clip": True, "missing": "drop", "standardization": "rank"},
    ])
    resp = client.post("/api/v1/paper-accounts", json={
        "strategy_kind": "factor_composite",
        "factors_json": factors_json,
        "initial_cash": 800000,
        "top_n": 8,
        "rebalance": "monthly",
    })
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["strategy_kind"] == "factor_composite"
    assert account["package_id"] is None
    assert account["status"] == "WAITING"
    assert account["top_n"] == 8
    assert account["rebalance"] == "monthly"
    assert account["standardization"] == "rank"
    assert len(account["factors"]) == 2
    assert account["factors"][1]["direction"] == -1
    assert "百分位排名" in account["describe_text"]
    assert "反向" in account["describe_text"]
    checks = {item["title"]: item for item in account["checks"]}
    assert "已锁定 2 个因子" in checks["因子组合"]["detail"]

    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]
    active = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    request = state.requests[-1]
    assert request.strategy_plugin == "factor_composite"
    assert request.top_n == 8 and request.rebalance == "monthly"
    assert request.risk_limits.max_positions == 8
    locked_rows = json.loads(request.strategy_parameters["factors_json"])
    assert [(r["name"], r["weight"], r["direction"]) for r in locked_rows] == [
        ("momentum_20", 0.6, 1),
        ("volatility_20", 0.4, -1),
    ]
    assert active["status"] == "ACTIVE" and active["last_date"] == "2026-10-29"
    assert active["result"]["effective_config"]["strategy_plugin"] == "factor_composite"
    assert active["result"]["effective_config"]["strategy_reference"] == f"paper:{account['account_id']}"

    # 列表返回 strategy_kind，K 线成交接口也正常工作。
    listed = client.get("/api/v1/paper-accounts").json()["items"]
    assert listed[0]["strategy_kind"] == "factor_composite"
    traded = client.get(f"/api/v1/runs/paper-{account['account_id']}/trades")
    assert traded.status_code == 200 and traded.json()["symbols"][0]["symbol"] == "600000"


def test_factor_composite_account_snapshots_custom_factor_definitions(env):
    from quant_platform.strategies.factor_composite import FactorCompositeParameters

    client, connect, _, state = env
    with connect() as conn:
        conn.execute(
            """INSERT INTO custom_factors (user_id, name, display_name, description, field, operator, window, window2, direction, expression, created_at)
               VALUES (1, 'my_alpha', '自建短期反转', '测试', 'close', 'expression', 20, NULL, -1, 'ret(close, 5) - ret(close, 20)', '2026-10-28')"""
        )
    factors_json = json.dumps([
        {"name": "my_alpha", "weight": 0.5, "direction": -1, "clip": False, "missing": "zero", "standardization": "zscore"},
        {"name": "momentum_20", "weight": 0.5, "direction": 1, "clip": False, "missing": "zero", "standardization": "zscore"},
    ])
    resp = client.post("/api/v1/paper-accounts", json={
        "strategy_kind": "factor_composite",
        "factors_json": factors_json,
    })
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["factors"][0]["has_custom_factor"] is True
    assert account["factors"][0]["display_name"] == "自建短期反转"
    checks = {item["title"]: item for item in account["checks"]}
    assert "自定义因子定义快照" in checks["因子组合"]["detail"]

    # 创建后删除自定义因子，模拟账户仍可按锁住的快照正常推进。
    with connect() as conn:
        conn.execute("DELETE FROM custom_factors WHERE user_id = 1 AND name = 'my_alpha'")
    state.bounds, state.calendar = (date(2020, 1, 2), date(2026, 10, 29)), [TODAY, date(2026, 10, 29)]
    active = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert active["status"] == "ACTIVE"
    parsed = FactorCompositeParameters.from_json(state.requests[-1].strategy_parameters["factors_json"])
    assert parsed.components[0].custom_factor is not None
    assert parsed.components[0].custom_factor.expression == "ret(close, 5) - ret(close, 20)"


def test_factor_composite_account_validation_and_backtest_reference(env):
    client, connect, _, _ = env
    assert client.post("/api/v1/paper-accounts", json={"strategy_kind": "factor_composite"}).status_code == 422
    assert client.post("/api/v1/paper-accounts", json={"strategy_kind": "factor_composite", "factors_json": "[]"}).status_code == 422
    assert client.post("/api/v1/paper-accounts", json={
        "strategy_kind": "factor_composite",
        "factors_json": json.dumps([{"name": "not_a_real_factor", "weight": 1}]),
    }).status_code == 422
    assert client.post("/api/v1/paper-accounts", json={"strategy_kind": "rule_builder"}).status_code == 422

    # 最近一次因子合成回测参照
    fc_config = {
        "strategy_reference": "factor_composite",
        "strategy_plugin": "factor_composite",
        "strategy_parameters": {"factors_json": json.dumps([{"name": "momentum_20", "weight": 1.0, "direction": 1}])},
        "market": "000300.SH",
        "initial_capital": 600_000,
        "max_positions": 12,
        "rebalance": "monthly",
    }
    with connect() as conn:
        conn.executemany(
            """INSERT INTO backtests (user_id, strategy, market, from_date, to_date, status, result, created_at)
               VALUES (?, '因子合成策略', '000300.SH', '2025-01-01', '2025-12-31', ?, ?, '2026-10-27')""",
            [
                (1, "完成", json.dumps({"effective_config": {"strategy_reference": "package:p1", "max_positions": 5}})),
                (1, "完成", json.dumps({"effective_config": fc_config})),
                (1, "失败", json.dumps({"effective_config": fc_config | {"max_positions": 20}})),
                (2, "完成", json.dumps({"effective_config": fc_config | {"max_positions": 30}})),
            ],
        )
    ref = client.get("/api/v1/paper-accounts/backtest-reference/factor_composite").json()["backtest"]
    assert ref["id"] == 2
    assert ref["config"]["strategy_plugin"] == "factor_composite"
    assert ref["config"]["max_positions"] == 12
    assert "momentum_20" in ref["config"]["strategy_parameters"]["factors_json"]


def test_paper_accounts_enable_initial_rebalance_and_report_next_schedule(env):
    client, _, _, state = env
    pkg = save_package(client, top_n=10)
    account = create(client, pkg["package_id"], rebalance="monthly")
    assert account["next_rebalance_date"] == TODAY.isoformat()
    assert account["next_rebalance_estimated"] is False
    checks = {item["title"]: item for item in account["checks"]}
    assert "开户首日（2026-10-28）收盘首次建仓" in checks["调仓计划"]["detail"]

    # 推进后：开启首日建仓，并结合交易日历给出当月末最后交易日
    state.bounds = (date(2020, 1, 2), date(2026, 10, 29))
    state.calendar = [
        date(2026, 10, 28),
        date(2026, 10, 29),
        date(2026, 10, 30),
        date(2026, 11, 2),
    ]
    active = client.post(f"/api/v1/paper-accounts/{account['account_id']}/advance").json()
    assert state.requests[-1].initial_rebalance is True
    assert active["result"]["effective_config"]["initial_rebalance"] is True
    assert active["next_rebalance_date"] == "2026-10-30"
    assert active["next_rebalance_estimated"] is False
    active_checks = {item["title"]: item for item in active["checks"]}
    assert "2026-10-30 收盘" in active_checks["调仓计划"]["detail"]

    # 日历未覆盖未来时回退估算当期最后工作日
    state.calendar = [date(2026, 10, 28), date(2026, 10, 29)]
    refreshed = client.get(f"/api/v1/paper-accounts/{account['account_id']}").json()
    assert refreshed["next_rebalance_date"] == "2026-10-30"
    assert refreshed["next_rebalance_estimated"] is True


def test_engine_initial_rebalance_builds_mid_month_position_while_default_stays_period_end():
    from quant_platform.backtest.engine import BacktestEngine

    dates = [
        date(2026, 11, 18),
        date(2026, 11, 19),
        date(2026, 11, 20),
        date(2026, 11, 23),
        date(2026, 11, 24),
        date(2026, 11, 25),
    ]
    stub = object.__new__(BacktestEngine)
    stub.rebalance = "monthly"

    # 默认回测口径：仅月末最后一天（区间内只有 11-25）
    stub.initial_rebalance = False
    assert stub._rebalance_dates(dates) == {date(2026, 11, 25)}

    # 模拟账户口径：首日 11-18 加入调仓日历，11-18 收盘出信号、11-19 开盘成交
    stub.initial_rebalance = True
    assert stub._rebalance_dates(dates) == {date(2026, 11, 18), date(2026, 11, 25)}

    # 跨月后：首日建仓 + 11 月末调仓，不重不漏
    across_month = [*dates, date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 1)]
    assert stub._rebalance_dates(across_month) == {date(2026, 11, 18), date(2026, 11, 30), date(2026, 12, 1)}

    # 按季调仓同理：季中开户首日建仓，之后每季末调仓
    stub.rebalance = "quarterly"
    assert stub._rebalance_dates(across_month) == {date(2026, 11, 18), date(2026, 12, 1)}
