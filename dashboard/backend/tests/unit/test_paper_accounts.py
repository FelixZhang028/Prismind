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
    with connect() as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, is_active INTEGER, is_admin INTEGER)")
        conn.executemany("INSERT INTO users VALUES (?,1,0)", [(1,), (2,)])
        conn.execute("CREATE TABLE strategy_packages (id INTEGER PRIMARY KEY, user_id INTEGER, package_id TEXT, name TEXT, definition TEXT, top_n INTEGER, rebalance TEXT, source TEXT, created_at TEXT)")
        conn.execute(database.PAPER_ACCOUNTS_TABLE)
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
