"""One job, one process. Run with python -m app.quant.backtest_worker JOB_ID."""
import json
import logging
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path
from datetime import date, datetime, timezone

from fastapi import HTTPException

from ..database import get_conn
from . import backtest_jobs as jobs, compute, runtime
from quant_platform.core import deadline
from quant_platform.core.progress import report, reporting


def watch_owner(jid, stopped):
    # A killed API process must not leave an orphan calculation using CPU.
    # The parent renews this lease; child progress never renews it.
    while not stopped.wait(2):
        try:
            with get_conn() as conn:
                row = conn.execute("SELECT state,lease_at,started_at FROM backtest_jobs WHERE id=?", (jid,)).fetchone()
            if row is None or row["state"] in {"CANCELLING", "CANCELLED", "FAILED", "TIMED_OUT"}:
                os._exit(1)
            stamp = row["lease_at"] or row["started_at"]
            if row["state"] == "RUNNING" and stamp and (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() > 15:
                os._exit(1)
        except Exception:
            logging.exception("Job owner lease check failed")


def execute(jid):
    paths = json.loads(os.environ.get("FELLOWQUANT_JOB_PATHS", "{}"))
    for key, attr in (("config", "CONFIG_PATH"), ("market", "MARKET_ROOT"), ("runtime", "RUNTIME_ROOT")):
        if key in paths:
            setattr(runtime, attr, Path(paths[key]))
    from ..routes import backtests, workspace
    from quant_platform.application.strategy_studio_service import StrategyPackage

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM backtest_jobs WHERE id=? AND state='RUNNING'", (jid,)).fetchone()
        if row is None:
            return
        user = conn.execute("SELECT id,is_admin,is_active FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if user is None or not user["is_active"]:
        jobs.finish(jid, "FAILED", "账户已停用，任务未执行")
        return
    user = dict(user)
    payload = json.loads(row["payload"])
    if payload["kind"] not in {"factor", "factor_research"}:
        runtime.TASK_SETTINGS = {**payload["snapshot"], "paths": paths}
    token = jobs.JOB_ID.set(jid)
    try:
        with deadline.limit(compute.job_timeout_seconds(payload["kind"])), reporting(jobs.reporter(jid)):
            body = payload["request"]
            if payload["kind"] == "factor":
                request = workspace.FactorEvalIn.model_validate(body)
                result = workspace.run_factor_job(request, user, payload["snapshot"])
                report("保存因子评估报告")
                jobs.save_factor_report(jid, result)
            elif payload["kind"] == "factor_research":
                request = workspace.FactorResearchIn.model_validate(body)
                result = workspace.run_factor_research_job(request, user, payload["snapshot"])
                report("保存组合研究报告")
                jobs.save_factor_report(jid, result)
            elif payload["kind"] == "backtest":
                backtests.submit_backtest(backtests.BacktestIn.model_validate(body), user)
            else:
                if payload["kind"] == "package":
                    request = workspace.PackageBacktestIn.model_validate(body)
                    package = workspace._stored_package(payload["package"], request.style)
                    package = replace(package, name=payload["label"], top_n=request.top_n or package.top_n,
                                      rebalance=request.rebalance or package.rebalance)
                    initial_cash = request.initial_cash
                    reference = "package:" + payload["package_id"]
                    exclude_st = None
                    hold_buffer = request.hold_buffer
                    execution_overrides = request.execution_overrides
                    filter_overrides = request.filter_overrides
                else:
                    request = workspace.ScreenHistoryIn.model_validate({k: v for k, v in body.items() if k not in {"from_date", "to_date"}})
                    package = StrategyPackage(package_id="screen", name=payload["label"],
                        definition=workspace._screen_rule(request.definition, user=user), top_n=request.top_n,
                        rebalance=request.rebalance, source="stock_screen", created_at=datetime.now(timezone.utc))
                    initial_cash, reference = 1_000_000, ""
                    exclude_st = request.exclude_st
                    hold_buffer = None
                    execution_overrides = None
                    filter_overrides = None
                workspace._run_backtest(user, package, market=request.market,
                    start=date.fromisoformat(body["from_date"]), end=date.fromisoformat(body["to_date"]),
                    initial_cash=initial_cash, reference=reference, package_id=payload["package_id"],
                    exclude_st=exclude_st,
                    hold_buffer=hold_buffer,
                    execution_overrides=execution_overrides,
                    filter_overrides=filter_overrides)
    except deadline.ComputationTimeout:
        jobs.finish(jid, "TIMED_OUT", jobs.TIMEOUT_MESSAGE)
    except HTTPException as exc:
        jobs.finish(jid, "FAILED", str(exc.detail))
    except BaseException:
        logging.exception("Backtest worker failed: %s", jid)
        jobs.finish(jid, "FAILED", "计算失败，请检查数据范围或联系管理员")
    finally:
        jobs.JOB_ID.reset(token)
        runtime.TASK_SETTINGS = None


if __name__ == "__main__":
    stopped = threading.Event()
    watcher = threading.Thread(target=watch_owner, args=(sys.argv[1], stopped), daemon=True)
    watcher.start()
    try:
        execute(sys.argv[1])
    finally:
        stopped.set()
        watcher.join(timeout=3)
