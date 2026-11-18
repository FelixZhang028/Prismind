"""Asynchronous entry points for backtests and single-factor evaluation."""
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from quant_platform.core.exceptions import ConfigurationError
from quant_platform.strategies.factor_composite import FactorCompositeParameters, FactorCompositeStrategy

from ..database import get_conn
from ..quant import backtest_jobs as jobs, runtime
from ..quant.markets import CURRENT_POOL
from .auth import get_current_user
from .backtests import BacktestIn, _resolve_plugin

router = APIRouter(prefix="/api/v1/backtest-jobs", tags=["backtests"])


class JobIn(BaseModel):
    kind: Literal["backtest", "package", "screen", "factor"] = "backtest"
    request: dict[str, Any]
    package_id: str | None = Field(None, max_length=160)


def prepare(body: JobIn, user: dict) -> dict:
    from . import workspace
    from quant_platform.data.index_constituents import INDEX_UNIVERSES

    package = None
    package_id = body.package_id
    kind = body.kind
    if kind == "factor":
        return workspace.prepare_factor_job(workspace.FactorEvalIn.model_validate(body.request), user)
    if kind == "backtest":
        request = BacktestIn.model_validate(body.request)
        if request.strategy.startswith("package:"):
            if request.strategy_parameters:
                raise HTTPException(422, "规则策略请在创建页修改指标参数")
            package_id = request.strategy.removeprefix("package:")
            kind = "package"
            values = dict(from_date=request.from_date, to_date=request.to_date,
                          initial_cash=request.initial_capital, top_n=request.max_positions,
                          rebalance=request.rebalance, market=request.market)
        else:
            values = request.model_dump()
    else:
        values = body.request
    bounds = runtime.local_data_bounds()
    if not bounds:
        raise HTTPException(409, "本地暂无行情数据，请先更新数据。")
    if kind == "package":
        package_request = workspace.PackageBacktestIn.model_validate(values)
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM strategy_packages WHERE package_id=? AND user_id=?", (package_id, user["id"])).fetchone()
        if row is None:
            raise HTTPException(404, "策略包不存在")
        package = dict(row)
        # Validate now; queue holds the entire saved definition, not a mutable reference.
        workspace._stored_package(package, package_request.style)
        values = package_request.model_dump()
        label = row["name"]
    elif kind == "screen":
        request = workspace.ScreenHistoryIn.model_validate(values)
        rule = workspace._screen_rule(request.definition)
        values = request.model_dump()
        values.update(from_date=max(bounds[0], bounds[1] - timedelta(days=365 * request.years)).isoformat(), to_date=bounds[1].isoformat())
        label = "条件选股：" + rule.name
    else:
        service = runtime.build_backtest_service(user)
        plugin = _resolve_plugin(service, request.strategy, user)
        metadata = next(m for m in service.available_strategies() if m.plugin_name == plugin)
        defaults = service.default_request()
        parameters = defaults.strategy_parameters if plugin == defaults.strategy_plugin else metadata.defaults()
        try:
            values["strategy_parameters"] = metadata.validate_parameters({**parameters, **request.strategy_parameters})
            if plugin == FactorCompositeStrategy.plugin_name:
                FactorCompositeParameters.from_json(values["strategy_parameters"]["factors_json"])
        except (ValueError, ConfigurationError) as exc:
            raise HTTPException(422, str(exc)) from None
        label = metadata.display_name
    market = values.get("market", CURRENT_POOL)
    if market != CURRENT_POOL and market not in INDEX_UNIVERSES:
        raise HTTPException(422, "不支持这个股票范围")
    try:
        start = date.fromisoformat(values.get("from_date") or bounds[0].isoformat())
        end = date.fromisoformat(values.get("to_date") or bounds[1].isoformat())
    except ValueError:
        raise HTTPException(422, "日期格式需为 YYYY-MM-DD") from None
    start, end = max(start, bounds[0]), min(end, bounds[1])
    if start >= end:
        raise HTTPException(422, "开始日期需早于结束日期，且区间须与本地行情有交集。")
    values.update(from_date=start.isoformat(), to_date=end.isoformat())
    saved_pool = runtime.saved_universe_snapshot(user["id"])
    symbols, filters, preset = saved_pool if saved_pool is not None else (*runtime.default_universe_settings(), None)
    if market == CURRENT_POOL and not symbols:
        raise HTTPException(422, "股票池为空，请先添加股票")
    return dict(kind=kind, request=values, package=package, package_id=package_id, label=label,
                snapshot=dict(symbols=symbols, filters=filters, preset=preset, risk=asdict(runtime.user_risk_limits(user["id"]))))


@router.post("", status_code=202)
def submit(body: JobIn, user: dict = Depends(get_current_user)):
    from pydantic import ValidationError
    try:
        payload = prepare(body, user)
    except (ValidationError, ConfigurationError) as exc:
        message = "因子评估参数无效，请检查后重试" if body.kind == "factor" else "回测参数或策略定义无效，请检查后重试"
        raise HTTPException(422, message) from exc
    return jobs.enqueue(user["id"], payload)


@router.get("")
def list_tasks(user: dict = Depends(get_current_user), category: Literal["backtest", "factor"] = "backtest"):
    return jobs.list_jobs(user["id"], category=category)


@router.get("/{job_id}")
def get_task(job_id: str, user: dict = Depends(get_current_user)):
    return jobs.get_job(job_id, user["id"])


@router.get("/{job_id}/factor-report")
def get_factor_report(job_id: str, user: dict = Depends(get_current_user)):
    return jobs.factor_report(job_id, user["id"])


@router.post("/{job_id}/cancel")
def cancel_task(job_id: str, user: dict = Depends(get_current_user)):
    return jobs.cancel(job_id, user["id"])
