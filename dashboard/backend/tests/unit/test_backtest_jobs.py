"""Queue lifecycle and isolation using disposable SQLite and real child processes."""
import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import database
from app.quant import backtest_jobs as jobs, compute
from app.routes import workspace


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))
    database.init_db()
    with database.get_conn() as conn:
        for uid in (1, 2):
            conn.execute("INSERT INTO users(id,name,email,password_hash,salt,created_at) VALUES(?,?,?,?,?,?)", (uid, "test", f"{uid}@example.test", "x", "x", database._now()))
    return tmp_path


def queued(uid=1):
    return jobs.enqueue(uid, {"label": "test", "snapshot": {}, "request": {}})


def wait_for(check, seconds=8):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if check():
            return
        time.sleep(0.03)
    raise AssertionError("condition not reached")


def test_queue_ownership_limits_and_cancel_before_start(db):
    job = queued()
    assert job["state"] == "QUEUED" and job["queue_position"] == 1
    with pytest.raises(HTTPException) as exc:
        jobs.cancel(job["id"], 2)
    assert exc.value.status_code == 404
    assert jobs.list_jobs(2)["items"] == []
    for _ in range(4):
        queued()
    with pytest.raises(HTTPException) as exc:
        queued()
    assert exc.value.status_code == 429
    assert jobs.cancel(job["id"], 1)["state"] == "CANCELLED"
    assert queued()["state"] == "QUEUED"


def test_cancelled_job_cannot_publish_and_success_is_atomic(db):
    job = queued()
    with database.get_conn() as conn:
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (job["id"],))
    token = jobs.JOB_ID.set(job["id"])
    values = (1, "s", "pool", "2025-01-01", "2025-12-31", "完成", "{}", database._now())
    try:
        jobs.cancel(job["id"], 1)
        with pytest.raises(InterruptedError), database.get_conn() as conn:
            jobs.save_result(conn, values)
        with database.get_conn() as conn:
            assert conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0] == 0
            conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (job["id"],))
        with database.get_conn() as conn:
            bid = jobs.save_result(conn, values)
        assert jobs.cancel(job["id"], 1)["state"] == "SUCCEEDED"
        assert jobs.get_job(job["id"], 1)["result_id"] == bid
    finally:
        jobs.JOB_ID.reset(token)


@pytest.mark.parametrize("action", ["cancel", "timeout", "factor_timeout", "stop", "crash"])
def test_real_child_exits_before_compute_slot_is_released(db, monkeypatch, action):
    real_popen = subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = real_popen([sys.executable, "-c", "import time; time.sleep(30)" if action != "crash" else "raise SystemExit(2)"], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(jobs.subprocess, "Popen", spawn)
    monkeypatch.setenv("FELLOWQUANT_BACKTEST_JOB_TIMEOUT", "1" if action == "timeout" else "20")
    if action == "factor_timeout":
        monkeypatch.setenv("FELLOWQUANT_FACTOR_JOB_TIMEOUT", "1")
        job = jobs.enqueue(1, {"kind": "factor"})
    else:
        job = queued()
    scheduler = jobs.BacktestScheduler()
    thread = threading.Thread(target=scheduler._execute, args=({"id": job["id"], "user_id": 1},))
    thread.start()
    try:
        wait_for(lambda: bool(children))
        if action == "cancel":
            jobs.cancel(job["id"], 1)
        elif action == "stop":
            scheduler.stop_event.set()
        thread.join(timeout=8)
        assert not thread.is_alive()
        assert children[0].poll() is not None
        assert compute.running()["total"] == 0
        expected = {
            "cancel": "CANCELLED", "timeout": "TIMED_OUT", "factor_timeout": "TIMED_OUT",
            "stop": "FAILED", "crash": "FAILED",
        }[action]
        assert jobs.get_job(job["id"], 1)["state"] == expected
        with compute.computing({"id": 1}):
            pass
    finally:
        scheduler.stop_event.set()
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
        thread.join(timeout=8)


def test_queued_backtest_uses_the_job_limit_instead_of_the_synchronous_limit(db, monkeypatch):
    from app.quant.backtest_worker import execute
    from app.routes import backtests
    from quant_platform.core import deadline

    monkeypatch.setenv("FELLOWQUANT_COMPUTE_TIMEOUT", "600")
    monkeypatch.delenv("FELLOWQUANT_BACKTEST_JOB_TIMEOUT", raising=False)
    now = [0]
    monkeypatch.setattr(deadline, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def run_backtest(request, user):
        with jobs.backtest_slot(user):
            now[0] = 601
            deadline.check()
            now[0] = 1801
            deadline.check()

    monkeypatch.setattr(backtests, "submit_backtest", run_backtest)
    task = jobs.enqueue(1, {
        "kind": "backtest",
        "snapshot": {},
        "request": {
            "strategy": "a_share_momentum", "market": "当前股票池",
            "from_date": "2024-01-02", "to_date": "2024-06-28",
        },
    })
    assert task["timeout_seconds"] == 1800
    assert compute.job_timeout_seconds("package") == 1800
    assert compute.job_timeout_seconds("screen") == 1800
    assert compute.timeout_seconds() == 600
    with database.get_conn() as conn:
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (task["id"],))
    execute(task["id"])
    assert now[0] == 1801
    assert jobs.get_job(task["id"], 1)["state"] == "TIMED_OUT"


def test_restart_marks_interrupted_jobs_and_keeps_queue(db, monkeypatch):
    running, waiting = queued(), queued()
    with database.get_conn() as conn:
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (running["id"],))
    scheduler = jobs.BacktestScheduler()
    monkeypatch.setattr(scheduler, "_loop", lambda: None)
    scheduler.start()
    scheduler.stop()
    assert jobs.get_job(running["id"], 1)["state"] == "FAILED"
    assert jobs.get_job(waiting["id"], 1)["state"] == "QUEUED"


def test_busy_user_remains_queued_until_slot_is_available(db):
    task = queued()
    scheduler = jobs.BacktestScheduler()
    with compute.computing({"id": 1}):
        scheduler._execute({"id": task["id"], "user_id": 1})
        assert jobs.get_job(task["id"], 1)["state"] == "QUEUED"
    assert compute.running()["total"] == 0


def test_cancellation_wins_over_a_late_worker_error(db):
    task = queued()
    with database.get_conn() as conn:
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (task["id"],))
    jobs.cancel(task["id"], 1)
    jobs.finish(task["id"], "FAILED", "late worker error")
    result = jobs.get_job(task["id"], 1)
    assert result["state"] == "CANCELLED" and result["error"] == "已取消"


def test_active_jobs_are_not_hidden_by_newer_finished_jobs(db):
    active = queued()
    for _ in range(35):
        newer = queued()
        jobs.cancel(newer["id"], 1)
    listed = jobs.list_jobs(1)["items"]
    assert len(listed) == 30 and listed[0]["id"] == active["id"]


def test_task_routes_do_not_expose_another_users_payload(db):
    from app.routes.backtest_jobs import get_task, list_tasks, cancel_task
    task = queued()
    assert "payload" not in get_task(task["id"], {"id": 1})
    assert list_tasks({"id": 2}) == {"items": []}
    for route in (get_task, cancel_task):
        with pytest.raises(HTTPException) as exc:
            route(task["id"], {"id": 2})
        assert exc.value.status_code == 404


def test_factor_task_uses_submitted_custom_factor_and_symbols(db, monkeypatch):
    from datetime import date
    from app.quant.backtest_worker import execute
    from app.routes.backtest_jobs import JobIn, get_factor_report, submit

    dates = date(2025, 1, 1), date(2025, 3, 31)
    monkeypatch.setattr(workspace, "_clamped_range", lambda start, end: dates)
    monkeypatch.setattr(workspace, "_factor_symbols", lambda user: ["600000.SH"])
    monkeypatch.setattr(workspace, "_evaluate_factor", lambda request, factor, start, end, repo, symbols: {
        "factor_name": factor.name, "window": factor.window, "symbols": symbols, "start": start.isoformat(),
    })
    with database.get_conn() as conn:
        conn.execute(
            """INSERT INTO custom_factors (user_id,name,display_name,field,operator,window,created_at)
               VALUES (1,'test_momentum','测试动量','adjusted_close','momentum',20,?)""", (database._now(),),
        )
    task = submit(JobIn(kind="factor", request={"factor_name": "test_momentum"}), {"id": 1})
    monkeypatch.setenv("FELLOWQUANT_FACTOR_JOB_TIMEOUT", "2400")
    assert jobs.list_jobs(1)["items"] == []
    assert jobs.list_jobs(1, category="factor")["items"][0]["timeout_seconds"] == 2400
    with database.get_conn() as conn:
        conn.execute("DELETE FROM custom_factors WHERE user_id=1")
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (task["id"],))
    monkeypatch.setattr(workspace, "_factor_symbols", lambda user: ["600001.SH"])
    execute(task["id"])

    assert jobs.get_job(task["id"], 1)["state"] == "SUCCEEDED"
    assert get_factor_report(task["id"], {"id": 1}) == {
        "factor_name": "test_momentum", "window": 20, "symbols": ["600000.SH"], "start": "2025-01-01",
    }
    with pytest.raises(HTTPException) as exc:
        get_factor_report(task["id"], {"id": 2})
    assert exc.value.status_code == 404


def test_cancelled_factor_task_cannot_publish_a_report(db):
    task = jobs.enqueue(1, {"kind": "factor"})
    with database.get_conn() as conn:
        conn.execute("UPDATE backtest_jobs SET state='RUNNING' WHERE id=?", (task["id"],))
    jobs.cancel(task["id"], 1)
    with pytest.raises(InterruptedError):
        jobs.save_factor_report(task["id"], {"factor_name": "momentum_20"})
    jobs.finish(task["id"], "CANCELLED", "已取消")
    assert jobs.get_job(task["id"], 1)["state"] == "CANCELLED"
    with pytest.raises(HTTPException) as exc:
        jobs.factor_report(task["id"], 1)
    assert exc.value.status_code == 404


def test_concurrent_imports_do_not_overwrite_each_other(db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(workspace, "default_universe_settings", lambda: ([], {}))
    def add(values):
        return workspace.universe_add(workspace.UniverseAddIn(symbols=values), {"id": 1})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(add, [["000001", "000002"], ["000002", "000003"]]))
    assert set(workspace._load_universe_symbols(1)) == {"000001", "000002", "000003"}
    assert sum(r["added_count"] for r in results) == 3


def test_import_800_codes_counts_invalid_duplicate_and_preserves_filters(db, monkeypatch):
    monkeypatch.setattr(workspace, "default_universe_settings", lambda: ([], {"exclude_st": True}))
    body = workspace.UniverseAddIn(symbols=[f"{i:06d}" for i in range(800)] + ["SH000001", "000002.SZ", "bad", "sz.000003"])
    result = workspace.universe_add(body, {"id": 1})
    assert (result["count"], result["added_count"], result["duplicate_count"], result["invalid_count"]) == (800, 800, 3, 1)
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM universe WHERE user_id=1").fetchone()
        assert len(json.loads(row["symbols"])) == 800 and row["exclude_st"] == 1
    monkeypatch.setattr(workspace, "MAX_POOL_SIZE", 800)
    with pytest.raises(HTTPException):
        workspace.universe_add(workspace.UniverseAddIn(symbols=["999999"]), {"id": 1})
    assert len(workspace._load_universe_symbols(1)) == 800


def test_archive_is_reversible_atomic_and_user_scoped(db):
    ids = []
    with database.get_conn() as conn:
        for uid in (1, 1, 2):
            ids.append(jobs.save_result(conn, (uid, "s", "pool", "2025-01-01", "2025-12-31", "完成", "{}", database._now())))
    refs = [f"run-{bid}" for bid in ids]
    with pytest.raises(HTTPException):
        workspace.archive_runs(workspace.ArchiveRunsIn(run_ids=[refs[0], refs[2]]), {"id": 1})
    with database.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM backtests WHERE archived_at IS NOT NULL").fetchone()[0] == 0

    workspace.archive_runs(workspace.ArchiveRunsIn(run_ids=refs[:2]), {"id": 1})
    with database.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM backtests WHERE archived_at IS NOT NULL").fetchone()[0] == 2
    assert workspace.run_library(user={"id": 1})["total"] == 0
    assert workspace.run_library(user={"id": 1}, archived=True)["total"] == 2
    workspace.archive_runs(workspace.ArchiveRunsIn(run_ids=refs[:2], archived=False), {"id": 1})
    with database.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM backtests WHERE archived_at IS NOT NULL").fetchone()[0] == 0
    assert workspace.run_library(user={"id": 1})["total"] == 2


def test_screen_pagination_preserves_total_and_does_not_change_the_pool(db, monkeypatch):
    from datetime import date
    definition = workspace.DefinitionIn(name="test", entry_logic="all",
        entry_rules=[dict(left=dict(name="close"), operator="gt", value=0)],
        ranking=dict(indicator=dict(name="close"), direction="ascending"))
    rule = workspace._screen_rule(definition)
    items = [{"symbol": f"{i:06d}.SZ", "ranking": i} for i in range(205)]
    monkeypatch.setattr(workspace, "_run_screen", lambda body, user: (rule, date(2025, 1, 2), {"items": items, "checked": 800, "matched": 205}))
    monkeypatch.setattr(workspace, "security_names", lambda: {})
    monkeypatch.setattr(workspace, "market_options", lambda: [])
    monkeypatch.setattr(workspace.platform_ai, "platform_model", lambda: None)
    monkeypatch.setattr(workspace.platform_ai, "usage", lambda *args: {})
    workspace._save_universe(1, ["000001"])
    pages = [workspace.screen_package(workspace.ScreenIn(definition=definition, offset=offset), {"id": 1}) for offset in (0, 100, 200)]
    assert [p["shown"] for p in pages] == [100, 100, 5]
    assert all(p["matched"] == 205 and p["checked"] == 800 for p in pages)
    assert len({item["symbol"] for page in pages for item in page["items"]}) == 205
    assert workspace._load_universe_symbols(1) == ["000001"]


@pytest.mark.parametrize("kind,count", [("backtest", 3), ("package", 300), ("screen", 800)])
def test_real_worker_saves_a_backtest_and_uses_submitted_pool(db, monkeypatch, kind, count):
    from app.quant import runtime
    from app.routes.backtest_jobs import JobIn, submit
    from quant_platform.backtest.run_store import BacktestRunStore
    from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository
    import numpy as np
    import pandas as pd

    monkeypatch.setattr(runtime, "MARKET_ROOT", db / "market")
    monkeypatch.setattr(runtime, "RUNTIME_ROOT", db / "runtime")
    repo = ParquetMarketDataRepository(runtime.MARKET_ROOT)
    days = pd.bdate_range("2024-01-02", periods=180)
    frames = []
    symbols = [f"{i:06d}.SZ" for i in range(1, count + 1)]
    for i in range(1, count + 1):
        prices = 10 + np.arange(len(days)) * .01 + np.sin(np.arange(len(days)) / 3) * .1
        frames.append(pd.DataFrame(dict(symbol=f"{i:06d}.SZ", trade_date=days,
            raw_open=prices, raw_high=prices * 1.01, raw_low=prices * .99,
            raw_close=prices, pre_close=np.r_[prices[0], prices[:-1]],
            adjusted_close=prices, adj_factor=1., volume=1e7, amount=1e8,
            quality_status="OK", is_st=False, is_suspended=False, is_listed=True,
            source="test")))
    repo.save_table("daily_bars", pd.concat(frames, ignore_index=True))
    repo.save_table("trade_calendar", pd.DataFrame(dict(cal_date=days, is_open=1)))
    repo.save_table("security_master", pd.DataFrame(dict(symbol=symbols, name=["test"] * count, list_date=pd.Timestamp("2010-01-01"), delist_date=pd.NaT)))
    if kind == "screen":
        day = days[150]
        codes = ["000300.SH", "000905.SH"]
        repo.save_table("index_constituents", pd.DataFrame({
            "index_symbol": [codes[0]] * 300 + [codes[1]] * 500,
            "effective_date": day, "symbol": symbols, "source": "test",
        }))
        repo.save_table("index_constituent_checks", pd.DataFrame({
            "index_symbol": codes, "checked_from": day, "checked_through": day,
        }))
        monkeypatch.setattr(workspace, "market_repository", lambda: repo)
        preset = workspace.universe_use_preset(workspace.UniversePresetIn(index="000906.SH", snapshot_date=day.date()), {"id": 1})
        assert preset["count"] == 800
    else:
        workspace._save_universe(1, [s.split(".")[0] for s in symbols])
    definition = dict(name="趋势过滤短期反转", entry_logic="all",
        entry_rules=[dict(left=dict(name="close"), operator="gt", right=dict(name="sma", window=60)),
                     dict(left=dict(name="return_1d", window=5), operator="lt", value=.05)],
        ranking=dict(indicator=dict(name="return_1d", window=5), direction="ascending"))
    if kind == "backtest":
        request = JobIn(request=dict(strategy="a_share_momentum", market="当前股票池",
            from_date=str(days[150].date()), to_date=str(days[-1].date()), max_positions=2))
    elif kind == "package":
        package = workspace.create_package(workspace.PackageIn(definition=definition, top_n=2), {"id": 1})
        request = JobIn(kind="package", package_id=package["package_id"], request=dict(market="当前股票池",
            from_date=str(days[150].date()), to_date=str(days[-1].date())))
    else:
        with database.get_conn() as conn:
            conn.execute("UPDATE universe SET exclude_st=0 WHERE user_id=1")
        request = JobIn(kind="screen", request=dict(
            definition=definition, market="当前股票池", top_n=2, years=1, exclude_st=True,
        ))
    task = submit(request, {"id": 1})
    if kind == "package":
        with database.get_conn() as conn:
            conn.execute("DELETE FROM strategy_packages WHERE package_id=?", (package["package_id"],))
    # Editing the pool while queued must not alter the submitted request.
    workspace._save_universe(1, ["999999"])
    scheduler = jobs.BacktestScheduler()
    scheduler.start()
    try:
        wait_for(lambda: jobs.get_job(task["id"], 1)["state"] not in jobs.ACTIVE, seconds=90)
    finally:
        scheduler.stop()
    result = jobs.get_job(task["id"], 1)
    assert result["state"] == "SUCCEEDED", result
    assert result["total"] == (180 if kind == "screen" else 30) and result["completed"] == result["total"]
    with database.get_conn() as conn:
        row = conn.execute("SELECT result FROM backtests WHERE id=?", (result["result_id"],)).fetchone()
        assert row is not None
        recorded = json.loads(row["result"])
        assert recorded["run_id"] and recorded["pool"]["count"] == count
        if kind == "screen":
            assert recorded["pool"]["name"] == "中证 800"
            assert recorded["pool"]["snapshot_date"] == day.date().isoformat()
            snapshot = BacktestRunStore(runtime.RUNTIME_ROOT / "runs").load_config(recorded["run_id"])
            assert snapshot["universe"]["universe"]["filters"]["exclude_st"] is True


def test_enqueue_deduplicates_identical_active_jobs_and_allows_distinct_or_after_cancel(db):
    payload_a = {
        "kind": "backtest",
        "package_id": None,
        "label": "因子组合",
        "request": {"strategy": "factor_composite", "from_date": "2024-01-01", "to_date": "2025-12-31", "max_positions": 20},
        "snapshot": {"symbols": ["000001.SZ"], "risk": {"max_industry_weight": 0.25}},
    }
    first = jobs.enqueue(1, payload_a, deduplicate=True)
    assert first.get("deduplicated") is None

    # Identical active submission reuses existing job instead of queuing a duplicate.
    second = jobs.enqueue(1, payload_a, deduplicate=True)
    assert second["id"] == first["id"]
    assert second["deduplicated"] is True
    assert len(jobs.list_jobs(1)["items"]) == 1

    # Different risk/request parameters still enqueue a distinct job.
    payload_b = {**payload_a, "request": {**payload_a["request"], "max_positions": 10}}
    third = jobs.enqueue(1, payload_b, deduplicate=True)
    assert third["id"] != first["id"]
    assert third.get("deduplicated") is None
    assert len(jobs.list_jobs(1)["items"]) == 2

    # Once cancelled, submitting payload_a again creates a fresh job.
    jobs.cancel(first["id"], 1)
    fourth = jobs.enqueue(1, payload_a, deduplicate=True)
    assert fourth["id"] != first["id"]
    assert fourth.get("deduplicated") is None
