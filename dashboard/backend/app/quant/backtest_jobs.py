"""Durable backtest queue for the supported single API-process deployment.

Each calculation runs in a disposable subprocess. The API owns compute slots;
it releases them only after the child has exited, including cancel/timeout.
The result record and SUCCEEDED state are committed in one SQLite transaction.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .. import database
from ..database import _now, get_conn
from . import compute, runtime

log = logging.getLogger(__name__)
ACTIVE = ("QUEUED", "RUNNING", "CANCELLING")
JOB_ID = ContextVar("backtest_job_id", default=None)
TIMEOUT_MESSAGE = "计算超时，已停止。请缩小股票范围或日期区间后重试。"

SCHEMA = database.BACKTEST_JOBS_TABLE


def backtest_slot(user: dict):
    """Use the synchronous limit only when there is no scheduler owning the job."""
    return nullcontext() if JOB_ID.get() is not None else compute.computing(user)


def initialize() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(backtests)")}
        if "archived_at" not in columns:
            conn.execute("ALTER TABLE backtests ADD COLUMN archived_at TEXT")


def enqueue(user_id: int, payload: dict) -> dict:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT COUNT(*) FROM backtest_jobs WHERE user_id=? AND state IN ('QUEUED','RUNNING','CANCELLING')", (user_id,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM backtest_jobs WHERE state IN ('QUEUED','RUNNING','CANCELLING')").fetchone()[0]
        if count >= 5 or total >= 100:
            raise HTTPException(429, "等待中的任务过多，请取消不需要的任务或稍后重试。")
        jid = uuid4().hex
        conn.execute("INSERT INTO backtest_jobs(id,user_id,payload,created_at) VALUES(?,?,?,?)",
                     (jid, user_id, json.dumps(payload, ensure_ascii=False), _now()))
    return get_job(jid, user_id)


def public_job(row, conn) -> dict:
    result = {key: row[key] for key in ("id", "state", "stage", "completed", "total", "created_at", "started_at", "finished_at", "result_id", "error")}
    result["queue_position"] = None
    if row["state"] == "QUEUED":
        result["queue_position"] = conn.execute(
            "SELECT COUNT(*) FROM backtest_jobs WHERE state='QUEUED' AND (created_at < ? OR (created_at = ? AND id <= ?))",
            (row["created_at"], row["created_at"], row["id"])).fetchone()[0]
    payload = json.loads(row["payload"])
    result["kind"] = payload.get("kind", "backtest")
    result["timeout_seconds"] = compute.job_timeout_seconds(result["kind"])
    result["label"] = payload.get("label", "策略回测")
    return result


def get_job(jid: str, user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM backtest_jobs WHERE id=? AND user_id=?", (jid, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "任务不存在")
        return public_job(row, conn)


def list_jobs(user_id: int, *, category: str = "backtest") -> dict:
    factor_jobs = int(category == "factor")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM backtest_jobs WHERE user_id=?
               AND (COALESCE(json_extract(payload, '$.kind'), 'backtest') = 'factor') = ?
               ORDER BY CASE WHEN state IN ('QUEUED','RUNNING','CANCELLING') THEN 0 ELSE 1 END,
                        created_at DESC, id DESC LIMIT 30""", (user_id, factor_jobs),
        ).fetchall()
        return {"items": [public_job(row, conn) for row in rows]}


def factor_report(jid: str, user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT r.report FROM factor_job_reports r JOIN backtest_jobs j ON j.id=r.job_id
               WHERE j.id=? AND j.user_id=? AND j.state='SUCCEEDED'""", (jid, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "因子评估报告不存在或尚未完成")
    return json.loads(row["report"])


def save_factor_report(jid: str, report: dict) -> None:
    result = json.dumps(report, ensure_ascii=False, allow_nan=False)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            """UPDATE backtest_jobs SET state='SUCCEEDED',stage='已完成',finished_at=?
               WHERE id=? AND state='RUNNING'""", (_now(), jid),
        ).rowcount
        if not changed:
            raise InterruptedError("任务已停止，报告未发布")
        conn.execute("INSERT INTO factor_job_reports(job_id,report) VALUES (?,?)", (jid, result))


def cancel(jid: str, user_id: int) -> dict:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT state FROM backtest_jobs WHERE id=? AND user_id=?", (jid, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "任务不存在")
        if row["state"] == "QUEUED":
            conn.execute("UPDATE backtest_jobs SET state='CANCELLED',stage='已取消',finished_at=? WHERE id=?", (_now(), jid))
        elif row["state"] == "RUNNING":
            conn.execute("UPDATE backtest_jobs SET state='CANCELLING',stage='正在停止计算' WHERE id=?", (jid,))
    return get_job(jid, user_id)


def save_result(conn, values: tuple) -> int:
    """Called by both existing backtest paths; publication is cancel-safe."""
    jid = JOB_ID.get()
    if jid:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT state FROM backtest_jobs WHERE id=?", (jid,)).fetchone()
        if row is None or row["state"] != "RUNNING":
            raise InterruptedError("任务已停止，结果未发布")
    cur = conn.execute(
        "INSERT INTO backtests (user_id,strategy,market,from_date,to_date,status,result,created_at) VALUES(?,?,?,?,?,?,?,?)", values)
    bid = cur.lastrowid
    if jid:
        conn.execute("UPDATE backtest_jobs SET state='SUCCEEDED',stage='已完成',result_id=?,finished_at=? WHERE id=?", (bid, _now(), jid))
    return bid


def finish(jid: str, state: str, error: str) -> None:
    with get_conn() as conn:
        # A cancellation that won the transaction race stays a cancellation,
        # even if the worker reports an error while trying to publish its result.
        conn.execute("""UPDATE backtest_jobs SET
                     state=CASE WHEN state='CANCELLING' THEN 'CANCELLED' ELSE ? END,
                     stage=CASE WHEN state='CANCELLING' THEN '已取消' ELSE ? END,
                     error=CASE WHEN state='CANCELLING' THEN '已取消' ELSE ? END,
                     finished_at=? WHERE id=? AND state IN ('RUNNING','CANCELLING')""",
                     (state, error, error, _now(), jid))


def reporter(jid: str):
    last = [0.0, ""]
    def update(stage, completed=0, total=0):
        now = time.monotonic()
        if stage == last[1] and now - last[0] < 0.5 and completed != total:
            return
        last[:] = [now, stage]
        with get_conn() as conn:
            conn.execute("UPDATE backtest_jobs SET stage=?,completed=?,total=?,heartbeat_at=? WHERE id=? AND state='RUNNING'",
                         (stage, completed, total, _now(), jid))
    return update


class BacktestScheduler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.workers = {}

    def start(self):
        initialize()
        # A previous API lifetime cannot own an active job anymore. Never replay
        # interrupted calculations silently; queued requests keep their snapshots.
        with get_conn() as conn:
            conn.execute("UPDATE backtest_jobs SET state='FAILED',stage='服务重启，计算已中断',error='服务重启，计算已中断，请重新提交',finished_at=? WHERE state IN ('RUNNING','CANCELLING')", (_now(),))
        self.thread = threading.Thread(target=self._loop, daemon=True, name="backtest-queue")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        for worker in list(self.workers.values()):
            worker.join(timeout=10)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.workers = {k: v for k, v in self.workers.items() if v.is_alive()}
                with get_conn() as conn:
                    rows = conn.execute("SELECT id,user_id FROM backtest_jobs WHERE state='QUEUED' ORDER BY created_at,id").fetchall()
                queued_users = set()
                for row in rows:
                    if row["user_id"] in queued_users:
                        continue
                    queued_users.add(row["user_id"])
                    if self.stop_event.is_set():
                        break
                    if row["id"] in self.workers:
                        continue
                    if compute.running()["total"] >= compute.slots():
                        break
                    thread = threading.Thread(target=self._execute, args=(dict(row),), daemon=True)
                    self.workers[row["id"]] = thread
                    thread.start()
            except Exception:
                log.exception("Backtest queue tick failed")
            self.stop_event.wait(0.5)

    def _execute(self, job):
        jid = job["id"]
        child = None
        try:
            with compute.computing({"id": job["user_id"]}):
                try:
                    with get_conn() as conn:
                        changed = conn.execute("UPDATE backtest_jobs SET state='RUNNING',stage='加载数据',started_at=? WHERE id=? AND state='QUEUED'", (_now(), jid)).rowcount
                        if not changed:
                            return
                        row = conn.execute("SELECT payload FROM backtest_jobs WHERE id=?", (jid,)).fetchone()
                    kind = json.loads(row["payload"]).get("kind", "backtest")
                    timeout = compute.job_timeout_seconds(kind)
                    env = os.environ.copy()
                    env["FELLOWQUANT_DATA_DIR"] = os.path.dirname(database.DB_PATH)
                    env["FELLOWQUANT_JOB_PATHS"] = json.dumps({"config": str(runtime.CONFIG_PATH), "market": str(runtime.MARKET_ROOT), "runtime": str(runtime.RUNTIME_ROOT)})
                    child = subprocess.Popen(
                        [sys.executable, "-m", "app.quant.backtest_worker", jid],
                        cwd=str(Path(__file__).resolve().parents[2]), env=env,
                        stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    started = time.monotonic()
                    outcome = None
                    while child.poll() is None:
                        with get_conn() as conn:
                            conn.execute("UPDATE backtest_jobs SET lease_at=? WHERE id=? AND state='RUNNING'", (_now(), jid))
                            row = conn.execute("SELECT state FROM backtest_jobs WHERE id=?", (jid,)).fetchone()
                        if row is None or row["state"] == "CANCELLING":
                            outcome = ("CANCELLED", "已取消")
                        elif self.stop_event.is_set():
                            outcome = ("FAILED", "服务停止，计算已中断，请重新提交")
                        elif time.monotonic() - started >= timeout:
                            outcome = ("TIMED_OUT", TIMEOUT_MESSAGE)
                        if outcome:
                            # Mark before termination so the worker cannot publish late.
                            finish(jid, *outcome)
                            child.terminate()
                            break
                        self.stop_event.wait(0.2)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    with get_conn() as conn:
                        row = conn.execute("SELECT state FROM backtest_jobs WHERE id=?", (jid,)).fetchone()
                    if row and row["state"] == "CANCELLING":
                        finish(jid, "CANCELLED", "已取消")
                    elif row and row["state"] == "RUNNING":
                        finish(jid, "FAILED", "计算进程异常退出，请重试或联系管理员")
                finally:
                    if child is not None and child.poll() is None:
                        child.kill()
                        child.wait()
        except HTTPException as exc:
            if exc.status_code != 429:
                finish(jid, "FAILED", "计算未能启动，请重试")
        except Exception:
            log.exception("Backtest job failed: %s", jid)
            if child is not None and child.poll() is None:
                child.kill()
                child.wait()
            finish(jid, "FAILED", "计算未能完成，请重试或联系管理员")
