"""
模拟账户：固定一套规则策略或多因子合成组合和设置，从创建那天开始，每个交易日收盘数据更新后推进到最新一天。

- 创建时把策略规则/因子组合快照、股票范围（股票池或指数）、风控设置复制一份锁住；之后改策略、改自定义因子、改股票池、改风控都不影响它。
- 开始日期就是创建当天（北京时间），不能选以前的日期，否则就是又做了一次回测。
- 每次推进都按锁住的设置从开始日期重新算到本地行情的最新一天（和回测是同一个引擎），所以结果可以重复得到；
  哪天的数据后来补全或修正了，下一次推进会自动用上。
- 只显示已经成交的记录和收盘持仓：引擎在最后一个交易日不生成订单，所以不会出现“下一个交易日要买什么”。
- 后台每隔几分钟检查一次：没有数据任务在运行、本地行情比账户新时，把所有账户依次推进一遍。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import replace as dc_replace
from datetime import date
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ..database import _now, get_conn
from ..quant import daily_schedule
from ..quant.benchmark_view import benchmark_comparison
from ..quant.compute import computing
from ..quant.markets import CURRENT_POOL, use_market
from ..quant.result_adapter import backtest_run_to_result
from ..quant.run_evidence import run_directory, with_run_evidence
from ..quant.runtime import (
    RUNTIME_ROOT,
    build_backtest_service,
    build_factor_registry,
    local_data_bounds,
    market_repository,
    security_names,
    user_risk_limits,
)
from ..routes.auth import get_current_user
from .workspace import _data_jobs, _friendly_engine_error, _stored_package
from quant_platform.application.data_jobs import exclusive
from quant_platform.application.strategy_studio_service import StrategyPackage, StrategyStudioService
from quant_platform.core.exceptions import ConfigurationError
from quant_platform.data.index_constituents import CHECKS_TABLE, CSI_800, INDEX_UNIVERSES, index_name, require_coverage
from quant_platform.factors.custom import CustomFactor, custom_factor_to_dict
from quant_platform.factors.registry import default_registry as default_factor_registry
from quant_platform.risk.config import RiskLimits
from quant_platform.strategies.factor_composite import FactorCompositeParameters, FactorCompositeStrategy

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/v1/paper-accounts", tags=["paper"])

DEFAULT_LIMIT = 3            # 每人最多几个模拟账户（管理员不限）；每个账户每天都要重新算一遍
CHECK_SECONDS = 300          # 后台多久检查一次
SHORT_RUN_DAYS = 60          # 运行不到这么多个交易日时，收益和风险指标只能参考
STALE_DATA_DAYS = 5          # 本地行情比今天落后这么多天时提醒
DATA_JOB_ACTIVE = ("STARTING", "RUNNING", "RETRYING")
STATUS_LABELS = {"WAITING": "等待第一个交易日", "ACTIVE": "运行中", "FAILED": "推进失败"}
STANDARDIZATION_LABELS = {"zscore": "Z-score", "rank": "百分位排名"}
REBALANCE_LABELS = {"daily": "每日", "weekly": "每周", "monthly": "每月", "quarterly": "每季"}
FACTOR_COMPOSITE_PLUGIN = FactorCompositeStrategy.plugin_name


def account_limit() -> int:
    try:
        return max(1, int(os.getenv("FELLOWQUANT_PAPER_ACCOUNTS", "") or DEFAULT_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT


def background_enabled() -> bool:
    return os.getenv("FELLOWQUANT_PAPER_ADVANCE", "on").strip().lower() not in ("0", "off", "false", "no")


def china_today() -> date:
    return daily_schedule.china_now().date()


class PaperAccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_kind: Literal["rule_builder", "factor_composite"] = "rule_builder"
    package_id: str | None = Field(None, min_length=1, max_length=64)
    factors_json: str | None = Field(None, max_length=32_000)
    name: str = Field("", max_length=40)
    market: str = Field(CURRENT_POOL, max_length=40)
    initial_cash: float = Field(1_000_000, ge=10_000, le=1e10, allow_inf_nan=False)
    top_n: int | None = Field(None, ge=1, le=50)
    rebalance: Literal["daily", "weekly", "monthly", "quarterly"] | None = None


def _is_factor_composite(stored: dict[str, Any]) -> bool:
    return stored.get("strategy_plugin") == FACTOR_COMPOSITE_PLUGIN


def _lock_factor_composite(
    factors_json: str, user: dict
) -> tuple[FactorCompositeParameters, dict[str, str], str]:
    """校验因子组合并为自定义因子写入不可变快照，避免日后删除或修改自定义因子影响推进。"""
    try:
        raw = json.loads(factors_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"因子组合JSON格式错误：{exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("请至少添加一个因子到组合中")

    builtin = default_factor_registry()
    user_registry = build_factor_registry(user)
    display_names: dict[str, str] = {}
    enriched: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or "name" not in item:
            raise ConfigurationError('因子组合元素必须形如 {"name": ..., "weight": ...}')
        copy_item = dict(item)
        name = str(copy_item["name"]).strip()
        copy_item["name"] = name
        label = str(copy_item.get("display_name") or "").strip()
        snapshot = copy_item.get("custom_factor")
        if snapshot is None and name not in builtin:
            if name in user_registry:
                factor = user_registry.get(name)
                if isinstance(factor, CustomFactor):
                    copy_item["custom_factor"] = custom_factor_to_dict(factor)
                if not label:
                    label = factor.display_name or factor.name
        elif snapshot is not None and isinstance(snapshot, dict) and not label:
            label = str(snapshot.get("display_name") or name)
        elif name in builtin and not label:
            factor = builtin.get(name)
            label = factor.display_name or factor.name
        display_names[name] = label or name
        enriched.append(copy_item)

    params = FactorCompositeParameters.from_json(json.dumps(enriched, ensure_ascii=False))
    return params, display_names, params.to_json()


def _factor_items(stored: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_factor_composite(stored):
        return []
    try:
        params = FactorCompositeParameters.from_json(str(stored.get("factors_json") or "[]"))
    except ConfigurationError:
        return []
    builtin = default_factor_registry()
    display_names = stored.get("display_names") or {}
    items: list[dict[str, Any]] = []
    for comp in params.components:
        default_dir = (
            comp.custom_factor.direction
            if comp.custom_factor is not None
            else (builtin.get(comp.name).direction if comp.name in builtin else 1)
        )
        items.append({
            "name": comp.name,
            "display_name": display_names.get(comp.name)
            or (comp.custom_factor.display_name if comp.custom_factor and comp.custom_factor.display_name else None)
            or (builtin.get(comp.name).display_name if comp.name in builtin else None)
            or comp.name,
            "weight": comp.weight,
            "direction": comp.direction if comp.direction is not None else default_dir,
            "has_custom_factor": comp.custom_factor is not None,
            "expression": comp.custom_factor.expression if comp.custom_factor else None,
        })
    return items


def _factor_describe_text(stored: dict[str, Any]) -> str:
    try:
        params = FactorCompositeParameters.from_json(str(stored.get("factors_json") or "[]"))
    except ConfigurationError:
        return ""
    items = _factor_items(stored)
    std = STANDARDIZATION_LABELS.get(params.standardization, params.standardization)
    parts = [
        f"{item['display_name']}（{'反向' if item['direction'] == -1 else '正向'} × {item['weight']:g}）"
        for item in items
    ]
    top_n = stored.get("top_n") or 10
    rebalance = REBALANCE_LABELS.get(str(stored.get("rebalance") or "weekly"), str(stored.get("rebalance") or ""))
    return f"按 {std} 标准化合成：{' + '.join(parts)}；最多持仓 {top_n} 只，{rebalance}调仓。"


def _default_factor_account_name(
    params: FactorCompositeParameters, display_names: dict[str, str], today: date
) -> str:
    suffix = f"·{today.isoformat()}"
    count = len(params.components)
    if count <= 2:
        joined = "+".join(display_names.get(c.name) or c.name for c in params.components)
        candidate = f"{joined}{suffix}"
        if len(candidate) <= 40:
            return candidate
    return f"多因子合成({count}因子){suffix}"[:40]


# --------------------------------------------------------------------------- #
# 读写
# --------------------------------------------------------------------------- #


def _owned(account_id: str, user: dict) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM paper_accounts WHERE account_id = ? AND user_id = ?",
                           (account_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="模拟账户不存在")
    return row


def _reload(account_id: str) -> Any:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)).fetchone()


def _update(account_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    columns = ", ".join(f"{name} = ?" for name in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE paper_accounts SET {columns} WHERE account_id = ?", (*fields.values(), account_id))


def _trading_days(start: date, end: date) -> int:
    """本地交易日历里 [start, end] 之间的交易日数。"""

    calendar = market_repository().read_table("trade_calendar")
    if calendar.empty:
        return 0
    if "is_open" in calendar.columns:
        calendar = calendar[calendar["is_open"].astype(int) == 1]
    days = pd.to_datetime(calendar["cal_date"]).dt.date
    return int(days.between(start, end).sum())


def _data_job_running(jobs: Any) -> bool:
    try:
        return any(record.get("status") in DATA_JOB_ACTIVE for record in jobs.records())
    except Exception:  # noqa: BLE001 - 读不到任务记录时当作有任务在运行，宁可晚一点推进
        return True


# --------------------------------------------------------------------------- #
# 推进
# --------------------------------------------------------------------------- #


def _remove_run(result: dict[str, Any] | None) -> None:
    """删掉旧的运行目录：模拟账户只保留最近一次结果，每天一份会越积越多。"""

    directory = run_directory(result or {})
    if directory is not None and directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


def _run(account: Any, end: date) -> dict[str, Any]:
    stored = json.loads(account["package"])
    service = build_backtest_service({"id": account["user_id"]})
    # 用创建时锁住的股票范围，不用账户主人现在的股票池。
    service.configs["universe"]["universe"] = json.loads(account["universe"])
    base = dc_replace(
        service.default_request(),
        start_date=date.fromisoformat(account["start_date"]),
        end_date=end,
        initial_cash=float(account["initial_cash"]),
        risk_limits=RiskLimits.from_mapping(json.loads(account["risk_limits"])),
    )
    if _is_factor_composite(stored):
        top_n = int(stored.get("top_n") or 10)
        rebalance = str(stored.get("rebalance") or "weekly")
        factors_json = str(stored["factors_json"])
        request = dc_replace(
            base,
            strategy_plugin=FACTOR_COMPOSITE_PLUGIN,
            strategy_id=f"paper_{account['account_id']}",
            strategy_parameters={"factors_json": factors_json},
            top_n=top_n,
            rebalance=rebalance,
        )
        run = service.run(request)
        result = backtest_run_to_result(run, names=security_names())
        result["effective_config"] = {
            "strategy_reference": f"paper:{account['account_id']}",
            "strategy_plugin": FACTOR_COMPOSITE_PLUGIN,
            "strategy_parameters": {"factors_json": factors_json},
            "market": account["market"],
            "initial_capital": float(account["initial_cash"]),
            "max_positions": top_n,
            "rebalance": rebalance,
            "from_date": account["start_date"],
            "to_date": end.isoformat(),
        }
        return with_run_evidence(result)

    package = StrategyPackage.from_mapping(stored)
    run = StrategyStudioService(service).run(package, base_request=base)
    result = backtest_run_to_result(run, names=security_names())
    result["effective_config"] = {
        "strategy_reference": f"paper:{account['account_id']}", "package_id": account["package_id"],
        "strategy_plugin": "rule_builder", "market": account["market"],
        "initial_capital": float(account["initial_cash"]), "max_positions": package.top_n,
        "rebalance": package.rebalance, "from_date": account["start_date"], "to_date": end.isoformat(),
    }
    return with_run_evidence(result)


def advance(account: Any, owner: dict) -> Any:
    """把账户推进到本地行情的最新一天，返回更新后的记录。

    同时进行的计算满了时抛出 429，账户保持原样（后台下次再试）；其他失败记在账户上。"""

    bounds = local_data_bounds()
    if bounds is None:
        raise HTTPException(status_code=409, detail="本地暂无行情数据。")
    latest = bounds[1]
    start = date.fromisoformat(account["start_date"])
    # 开始日收盘时第一次调仓，下一个交易日开盘成交：至少要有两个交易日才有结果。
    if _trading_days(start, latest) < 2:
        _update(account["account_id"], attempted_date=latest.isoformat())
        return _reload(account["account_id"])
    _update(account["account_id"], attempted_date=latest.isoformat())
    try:
        with computing(owner):
            result = _run(account, latest)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            _update(account["account_id"], attempted_date=account["attempted_date"])
            raise
        error = str(exc.detail)
    except (ConfigurationError, ValueError) as exc:
        error = _friendly_engine_error(exc)
    except Exception as exc:  # noqa: BLE001 - 引擎内部错误记在账户上，不影响别的账户
        logger.exception("模拟账户 %s 推进失败", account["account_id"])
        error = _friendly_engine_error(exc)
    else:
        previous = json.loads(account["result"]) if account["result"] else None
        _update(account["account_id"], status="ACTIVE", last_date=latest.isoformat(), error=None,
                result=json.dumps(result, ensure_ascii=False))
        if previous and previous.get("run_id") != result.get("run_id"):
            _remove_run(previous)
        return _reload(account["account_id"])
    _update(account["account_id"], status="FAILED", error=error[:500])
    return _reload(account["account_id"])


def advance_all(jobs: Any) -> int:
    """后台用：把本地行情比账户新的账户依次推进一遍，返回推进了几个。"""

    if _data_job_running(jobs):
        return 0
    bounds = local_data_bounds()
    if bounds is None:
        return 0
    latest = bounds[1].isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, u.is_admin FROM paper_accounts p JOIN users u ON u.id = p.user_id "
            "WHERE u.is_active = 1 AND (p.attempted_date IS NULL OR p.attempted_date < ?) ORDER BY p.id",
            (latest,),
        ).fetchall()
    done = 0
    for row in rows:
        if _data_job_running(jobs):  # 推进途中开始了新的数据更新：等它结束再继续
            break
        try:
            advance(row, {"id": row["user_id"], "is_admin": bool(row["is_admin"])})
            done += 1
        except HTTPException:
            continue  # 这个人有计算正在进行，或者服务器正忙：下次检查再推进它
    return done


class PaperAdvancer:
    """Daemon thread: advances every paper account after each data update."""

    def __init__(self, jobs: Any) -> None:
        self.jobs = jobs
        self._stop = threading.Event()

    def tick(self) -> int:
        if not background_enabled():
            return 0
        try:
            with exclusive(RUNTIME_ROOT / "paper_accounts.lock"):
                return advance_all(self.jobs)
        except RuntimeError:  # 另一个后端进程正在推进
            return 0

    def _loop(self) -> None:
        while not self._stop.wait(CHECK_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - 检查失败不能让线程退出
                logger.exception("推进模拟账户失败")

    def start(self) -> None:
        threading.Thread(target=self._loop, name="paper-accounts", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


# --------------------------------------------------------------------------- #
# 页面用的整理
# --------------------------------------------------------------------------- #


def _market_label(account: Any) -> str:
    if account["market"] in INDEX_UNIVERSES:
        return f"{index_name(account['market'])}历史成分股"
    count = len(json.loads(account["universe"]).get("symbols") or [])
    return f"创建时的股票池（{count} 只）" if count else "创建时的默认股票池"


def _package_text(package: StrategyPackage) -> str:
    try:
        return package.definition.describe(top_n=package.top_n, rebalance=package.rebalance)
    except ConfigurationError:
        return ""


def _summary(account: Any) -> dict[str, Any]:
    result = json.loads(account["result"]) if account["result"] else {}
    stored = json.loads(account["package"])
    is_factor = _is_factor_composite(stored)
    strategy_name = stored.get("name") or ("多因子合成策略" if is_factor else "")
    return {
        "account_id": account["account_id"],
        "display_name": account["display_name"],
        "status": account["status"],
        "status_label": STATUS_LABELS.get(account["status"], account["status"]),
        "strategy_kind": FACTOR_COMPOSITE_PLUGIN if is_factor else "rule_builder",
        "strategy_name": strategy_name,
        "package_id": None if is_factor else account["package_id"],
        "market": account["market"],
        "market_label": _market_label(account),
        "initial_cash": account["initial_cash"],
        "top_n": stored.get("top_n"),
        "rebalance": stored.get("rebalance"),
        "start_date": account["start_date"],
        "last_date": account["last_date"],
        "error": account["error"],
        "created_at": account["created_at"],
        "total_return": result.get("total_return"),
        "max_drawdown": result.get("max_drawdown"),
        "final_equity": result.get("final_equity"),
    }


def _check(title: str, passed: bool, detail: str, severity: str = "info") -> dict[str, Any]:
    return {"title": title, "passed": passed, "severity": "ok" if passed else severity, "detail": detail}


def account_checks(account: Any, result: dict[str, Any], *, today: date, latest: date | None,
                   current_package: Any) -> list[dict[str, Any]]:
    """账户现在的情况：数据新不新、规则有没有变、风控、结果能不能当真。只描述，不评价策略好坏。"""

    checks = []
    if latest is None:
        checks.append(_check("行情数据", False, "本地暂无行情数据。", "warning"))
    else:
        behind = (today - latest).days
        reached = f"账户推进到 {account['last_date']}" if account["last_date"] else "账户还没有推进"
        text = f"本地行情最新到 {latest.isoformat()}，{reached}。"
        if behind > STALE_DATA_DAYS:
            checks.append(_check("行情数据", False, text + f"本地行情已经 {behind} 天没有更新。", "warning"))
        else:
            checks.append(_check("行情数据", account["last_date"] == latest.isoformat(), text, "info"))

    stored = json.loads(account["package"])
    if _is_factor_composite(stored):
        items = _factor_items(stored)
        custom_count = sum(1 for item in items if item.get("has_custom_factor"))
        extra = f"（含 {custom_count} 个自定义因子定义快照）" if custom_count else ""
        checks.append(_check(
            "因子组合", True,
            f"已锁定 {len(items)} 个因子的权重、方向与标准化设置{extra}；后续修改因子库不影响本账户。",
        ))
    else:
        package = StrategyPackage.from_mapping(stored)
        if current_package is None:
            checks.append(_check("策略规则", True, "原策略已经删除；模拟账户仍按创建时锁住的规则运行。"))
        else:
            try:
                same = _stored_package(current_package).definition.to_dict() == package.definition.to_dict()
            except (ValueError, ConfigurationError):
                same = False
            checks.append(_check("策略规则", True, "规则和原策略一致。" if same else
                                 "原策略创建后修改过规则；模拟账户仍按创建时锁住的规则运行。"))

    risk = RiskLimits.from_mapping(json.loads(account["risk_limits"]))
    if not risk.enabled:
        checks.append(_check("风控", False, "创建时风控是关闭的：不限制仓位和回撤。", "info"))
    elif risk.max_drawdown >= 1:
        checks.append(_check("风控", False, "没有设回撤停止线（100%）：回撤再大也照常按规则调仓。", "info"))
    else:
        action = "不再买入新股票" if risk.drawdown_action == "stop_new" else \
            f"总仓位降到 {risk.drawdown_target_weight:.0%} 以内"
        stopped = (result.get("max_drawdown") or 0) >= risk.max_drawdown * 100
        detail = f"回撤达到 {risk.max_drawdown:.0%} 时{action}。"
        checks.append(_check("风控", not stopped,
                             detail + ("账户的最大回撤已经达到这条线。" if stopped else ""), "warning"))

    if result:
        days = len(result.get("equity") or [])
        reliable = bool(result.get("metrics_reliable"))
        if not reliable:
            checks.append(_check("结果可信度", False, "最近一次结果没有通过数据检查，下面的数字不能当作结论。", "warning"))
        elif days < SHORT_RUN_DAYS:
            checks.append(_check("结果可信度", False, f"只运行了 {days} 个交易日，收益和风险指标波动很大，只能参考。", "info"))
        else:
            checks.append(_check("结果可信度", True, f"已运行 {days} 个交易日，数据检查通过。"))
    return checks


def _detail(account: Any) -> dict[str, Any]:
    result = with_run_evidence(json.loads(account["result"])) if account["result"] else {}
    stored = json.loads(account["package"])
    is_factor = _is_factor_composite(stored)
    current = None
    if not is_factor:
        with get_conn() as conn:
            current = conn.execute("SELECT * FROM strategy_packages WHERE package_id = ? AND user_id = ?",
                                   (account["package_id"], account["user_id"])).fetchone()
    bounds = local_data_bounds()
    directory = run_directory(result) if result else None
    if is_factor:
        describe_text = _factor_describe_text(stored)
        factors = _factor_items(stored)
        try:
            standardization = FactorCompositeParameters.from_json(str(stored.get("factors_json") or "[]")).standardization
        except ConfigurationError:
            standardization = "zscore"
    else:
        package = StrategyPackage.from_mapping(stored)
        describe_text = _package_text(package)
        factors = []
        standardization = None
    return {
        **_summary(account),
        "describe_text": describe_text,
        "factors": factors,
        "standardization": standardization,
        "risk_limits": json.loads(account["risk_limits"]),
        "latest_data_date": bounds[1].isoformat() if bounds else None,
        "result": result,
        "trades": result.get("trades") or [],
        "positions": result.get("positions") or [],
        "benchmark": benchmark_comparison(directory) if directory else None,
        "checks": account_checks(account, result, today=china_today(), latest=bounds[1] if bounds else None,
                                 current_package=current),
    }


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #


@router.get("", summary="我的模拟账户")
def list_accounts(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM paper_accounts WHERE user_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
    limit = None if user.get("is_admin") else account_limit()
    return {"items": [_summary(row) for row in rows], "limit": limit, "today": china_today().isoformat()}


@router.get("/backtest-reference/{package_id}", summary="所选策略最近一次成功回测的设置")
def latest_backtest_reference(package_id: str, user: dict = Depends(get_current_user)):
    if package_id == FACTOR_COMPOSITE_PLUGIN:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT id, created_at, json_extract(result, '$.effective_config') AS config
                   FROM backtests
                   WHERE user_id = ? AND status = '完成'
                     AND CASE WHEN json_valid(result) THEN
                         json_extract(result, '$.effective_config.strategy_plugin') = ?
                         OR json_extract(result, '$.effective_config.strategy_reference') = ?
                     END
                   ORDER BY id DESC LIMIT 1""",
                (user["id"], FACTOR_COMPOSITE_PLUGIN, FACTOR_COMPOSITE_PLUGIN),
            ).fetchone()
        if row is None:
            return {"backtest": None}
        config = json.loads(row["config"])
        fields = ("strategy_reference", "strategy_plugin", "strategy_parameters",
                  "market", "initial_capital", "max_positions", "rebalance")
        return {"backtest": {"id": row["id"], "created_at": row["created_at"],
                             "config": {field: config.get(field) for field in fields}}}

    # The package reference is immutable in completed runs; strategy names can be reused.
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id, created_at, json_extract(result, '$.effective_config') AS config
               FROM backtests
               WHERE user_id = ? AND status = '完成'
                 AND CASE WHEN json_valid(result) THEN
                     json_extract(result, '$.effective_config.strategy_reference') = ?
                 END
               ORDER BY id DESC LIMIT 1""",
            (user["id"], f"package:{package_id}"),
        ).fetchone()
    if row is None:
        return {"backtest": None}
    config = json.loads(row["config"])
    fields = ("strategy_reference", "market", "initial_capital", "max_positions", "rebalance")
    return {"backtest": {"id": row["id"], "created_at": row["created_at"],
                         "config": {field: config.get(field) for field in fields}}}


@router.post("", status_code=status.HTTP_201_CREATED, summary="新建模拟账户（从今天开始）")
def create_account(body: PaperAccountIn, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_accounts WHERE user_id = ?", (user["id"],)).fetchone()[0]
    if not user.get("is_admin") and count >= account_limit():
        raise HTTPException(status_code=409, detail=f"每人最多 {account_limit()} 个模拟账户，请先删除一个不再需要的。")
    if body.market != CURRENT_POOL and body.market not in INDEX_UNIVERSES:
        raise HTTPException(status_code=422, detail="不支持这个股票范围，请选择当前股票池或列表里的指数。")

    today = china_today()
    if body.strategy_kind == FACTOR_COMPOSITE_PLUGIN:
        if not (body.factors_json or "").strip():
            raise HTTPException(status_code=422, detail="请至少添加一个因子来创建多因子合成模拟账户。")
        try:
            params, display_names, locked_factors_json = _lock_factor_composite(body.factors_json or "", user)
        except (ValueError, ConfigurationError) as exc:
            raise HTTPException(status_code=422, detail=f"因子组合无效：{exc}")
        top_n = int(body.top_n or 10)
        rebalance = body.rebalance or "weekly"
        stored_package_id = FACTOR_COMPOSITE_PLUGIN
        stored_payload: dict[str, Any] = {
            "strategy_plugin": FACTOR_COMPOSITE_PLUGIN,
            "name": f"多因子合成（{len(params.components)} 因子）",
            "factors_json": locked_factors_json,
            "display_names": display_names,
            "top_n": top_n,
            "rebalance": rebalance,
        }
        name = body.name.strip() or _default_factor_account_name(params, display_names, today)
    else:
        if not body.package_id:
            raise HTTPException(status_code=422, detail="请选择一个规则策略。")
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM strategy_packages WHERE package_id = ? AND user_id = ?",
                               (body.package_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="策略不存在")
        try:
            package = _stored_package(row)
            package = dc_replace(package, name=row["name"], top_n=body.top_n or package.top_n,
                                 rebalance=body.rebalance or package.rebalance)
            package.validate()
        except (ValueError, ConfigurationError) as exc:
            raise HTTPException(status_code=422, detail=f"策略定义无效：{exc}")
        top_n = package.top_n
        stored_package_id = body.package_id
        stored_payload = package.to_dict()
        name = body.name.strip() or f"{row['name']}·{today.isoformat()}"

    service = build_backtest_service(user)
    try:
        use_market(service, body.market)
        if body.market == CSI_800:
            require_coverage(market_repository().read_table(CHECKS_TABLE), body.market, today, today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    universe = service.configs["universe"].get("universe") or {}
    risk = dc_replace(user_risk_limits(user["id"]), max_positions=top_n)
    account_id = uuid4().hex[:12]
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO paper_accounts (user_id, account_id, display_name, status, package_id, package, market, "
            "universe, risk_limits, initial_cash, start_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"], account_id, name, "WAITING", stored_package_id, json.dumps(stored_payload, ensure_ascii=False),
             body.market, json.dumps(universe, ensure_ascii=False, default=str), json.dumps(risk.to_dict()),
             float(body.initial_cash), today.isoformat(), now, now),
        )
    return _detail(_reload(account_id))


@router.get("/{account_id}", summary="模拟账户详情")
def get_account(account_id: str, user: dict = Depends(get_current_user)):
    return _detail(_owned(account_id, user))


@router.post("/{account_id}/advance", summary="马上推进到本地行情的最新一天")
def advance_account(account_id: str, user: dict = Depends(get_current_user)):
    account = _owned(account_id, user)
    if _data_job_running(_data_jobs()):
        raise HTTPException(status_code=409, detail="数据正在更新，请等更新完成后再推进。")
    return _detail(advance(account, user))


@router.delete("/{account_id}", summary="删除模拟账户")
def delete_account(account_id: str, user: dict = Depends(get_current_user)):
    account = _owned(account_id, user)
    with get_conn() as conn:
        conn.execute("DELETE FROM paper_accounts WHERE account_id = ? AND user_id = ?", (account_id, user["id"]))
    _remove_run(json.loads(account["result"]) if account["result"] else None)
    return {"ok": True}
