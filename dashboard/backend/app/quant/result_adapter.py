"""结果转换器：把 quant_platform 的回测/因子报告转换成前端 VIEW_SPEC 契约 JSON。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from quant_platform.application.backtest_service import BacktestRun
from quant_platform.execution.models import TRADE_REASON_LABELS
from quant_platform.factors.evaluation import FactorReport

from .run_evidence import relative_run_dir
from .symbols import to_bare

# 回测成交明细最多内嵌的条数（完整明细见 data/runtime/runs/<run_id>/）。
MAX_TRADE_ROWS = 500


def _finite(value: Any) -> Any:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _round(value: Any, digits: int = 2) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _percent(value: Any, absolute: bool = False) -> float | None:
    number = _finite(value)
    return None if number is None else _round((abs(number) if absolute else number) * 100)


def backtest_run_to_result(run: BacktestRun, names: dict[str, str] | None = None) -> dict[str, Any]:
    """BacktestRun -> 前端 backtests.result JSON（含 trades / positions）。"""

    summary = run.result.summary
    nav = run.result.nav
    equity: list[float] = []
    nav_dates: list[str] = []
    if not nav.empty and "equity" in nav.columns:
        equity = [round(float(v), 2) for v in pd.to_numeric(nav["equity"], errors="coerce")]
        nav_dates = [
            ts.date().isoformat() for ts in pd.to_datetime(nav["trade_date"], errors="coerce")
        ]

    return {
        "equity": equity,
        "nav_dates": nav_dates,
        "total_return": _percent(summary.get("cumulative_return")),
        "annual_return": _percent(summary.get("annual_return")),
        "max_drawdown": _percent(summary.get("max_drawdown"), True),
        "sharpe": _round(summary.get("sharpe")),
        "sortino": _round(summary.get("sortino")),
        "calmar": _round(summary.get("calmar")),
        "win_rate": _percent(summary.get("positive_day_ratio")),
        "final_equity": _round(summary.get("final_equity")),
        "total_cost": _round(summary.get("total_transaction_cost")),
        "commission": _round(summary.get("commission")),
        "stamp_tax": _round(summary.get("stamp_tax")),
        "slippage_cost": _round(summary.get("slippage_cost")),
        "portfolio_turnover": _percent(summary.get("portfolio_turnover")),
        "annualized_turnover": _percent(summary.get("annualized_turnover")),
        "fills": int(summary.get("fills") or 0),
        "orders": int(summary.get("orders") or 0),
        "closed_trades": int(summary.get("closed_trades") or 0),
        "trade_win_rate": _percent(summary.get("trade_win_rate")),
        "average_holding_days": _round(summary.get("average_holding_days")),
        "validity_status": summary.get("validity_status"),
        "metrics_reliable": bool(summary.get("metrics_reliable", False)),
        "run_id": run.result.run_id,
        "run_kind": getattr(run, "config_snapshot", {}).get("app", {}).get("backtest", {}).get("run_kind", "single"),
        "output_dir": relative_run_dir(run.output_dir),
        "trades": fills_to_trades(run.result.fills),
        "positions": final_positions(run.result.positions, names=names, as_of=nav_dates[-1] if nav_dates else None),
        **({"hold_buffer": int(summary["hold_buffer"])} if summary.get("hold_buffer") else {}),
        **(
            {
                "market_timing": summary["market_timing"],
                "market_timing_triggers": int(summary.get("market_timing_triggers") or 0),
            }
            if summary.get("market_timing")
            else {}
        ),
        **(
            {
                "exit_rules": summary["exit_rules"],
                "stop_loss_triggers": int(summary.get("stop_loss_triggers") or 0),
                "trailing_stop_triggers": int(summary.get("trailing_stop_triggers") or 0),
            }
            if summary.get("exit_rules")
            else {}
        ),
    }


def fills_to_trades(fills: pd.DataFrame) -> list[dict[str, Any]]:
    """成交明细 -> 前端交易明细表（最多 MAX_TRADE_ROWS 条）。"""

    if fills.empty:
        return []
    frame = fills.tail(MAX_TRADE_ROWS).copy()
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        quantity = int(record.get("quantity") or 0)
        price = float(record.get("price") or 0.0)
        raw_reason = record.get("reason")
        reason = str(raw_reason).strip() if raw_reason is not None and pd.notna(raw_reason) else ""
        rows.append(
            {
                "date": str(record.get("trade_date")),
                "symbol": to_bare(str(record.get("symbol"))),
                "side": "买入" if str(record.get("side")).upper() == "BUY" else "卖出",
                "quantity": quantity,
                "price": round(price, 2),
                "amount": round(quantity * price, 2),
                "fee": round(
                    float(record.get("commission") or 0.0)
                    + float(record.get("stamp_tax") or 0.0),
                    2,
                ),
                "reason": reason,
                "reason_label": TRADE_REASON_LABELS.get(reason, "—"),
            }
        )
    return rows


def final_positions(
    positions: pd.DataFrame, names: dict[str, str] | None = None, as_of: str | None = None
) -> list[dict[str, Any]]:
    """持仓帧最后一日的持仓快照 -> 前端持仓分析表。

    持仓帧只记有持仓的日子：``as_of``（回测的最后一个交易日）那天没有记录，说明收盘时全是现金，返回空表，
    不能把更早那天的持仓当成最后的持仓。"""

    names = names or {}
    if positions.empty or "trade_date" not in positions.columns:
        return []
    frame = positions.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    last_day = frame["trade_date"].max()
    if as_of is not None and last_day != pd.Timestamp(as_of):
        return []
    snapshot = frame[frame["trade_date"].eq(last_day)]
    rows: list[dict[str, Any]] = []
    for record in snapshot.to_dict(orient="records"):
        quantity = int(record.get("quantity") or 0)
        average_cost = float(record.get("average_cost") or 0.0)
        market_value = float(record.get("market_value") or 0.0)
        close = record.get("close")
        symbol = str(record.get("symbol"))
        rows.append(
            {
                "symbol": to_bare(symbol),
                "name": names.get(symbol, ""),
                "quantity": quantity,
                "avg_price": round(average_cost, 2),
                "price": round(float(close), 2) if close is not None else None,
                "market_value": round(market_value, 2),
                "pnl": round(market_value - quantity * average_cost, 2),
            }
        )
    return rows


def _neutralization_coverage_to_dict(coverage: dict[str, Any] | None) -> dict[str, Any] | None:
    if not coverage:
        return None
    yearly = [
        {
            "year": int(row["year"]),
            "samples": int(row["samples"]),
            "industry_coverage": _round(row.get("industry_coverage"), 4),
            "size_coverage": _round(row.get("size_coverage"), 4),
            "joint_coverage": _round(row.get("joint_coverage"), 4),
            "total_days": int(row["total_days"]),
            "effective_days": int(row["effective_days"]),
            "skipped_days": int(row["skipped_days"]),
        }
        for row in coverage.get("yearly") or []
    ]
    return {
        "mode": coverage.get("mode"),
        "requested_start": coverage.get("requested_start"),
        "requested_end": coverage.get("requested_end"),
        "effective_start": coverage.get("effective_start"),
        "effective_end": coverage.get("effective_end"),
        "total_samples": int(coverage.get("total_samples") or 0),
        "usable_samples": int(coverage.get("usable_samples") or 0),
        "effective_samples": int(coverage.get("effective_samples") or 0),
        "total_days": int(coverage.get("total_days") or 0),
        "effective_days": int(coverage.get("effective_days") or 0),
        "skipped_days": int(coverage.get("skipped_days") or 0),
        "leading_missing_days": int(coverage.get("leading_missing_days") or 0),
        "trailing_missing_days": int(coverage.get("trailing_missing_days") or 0),
        "industry_coverage": _round(coverage.get("industry_coverage"), 4),
        "size_coverage": _round(coverage.get("size_coverage"), 4),
        "joint_coverage": _round(coverage.get("joint_coverage"), 4),
        "insufficient": bool(coverage.get("insufficient")),
        "warning": str(coverage.get("warning") or ""),
        "yearly": yearly,
    }


def factor_report_to_dict(report: FactorReport) -> dict[str, Any]:
    """FactorReport -> 前端因子评估 JSON 契约。"""

    daily_ic: list[dict[str, Any]] = []
    if not report.daily_ic.empty:
        frame = report.daily_ic.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for record in frame.to_dict(orient="records"):
            point = {
                "date": record["date"].date().isoformat(),
                "ic": _round(record.get("ic"), 4),
                "rank_ic": _round(record.get("rank_ic"), 4),
            }
            if "rank_ic_ir" in record:
                point.update(
                    ic_ir=_round(record["ic_ir"], 4),
                    rank_ic_ir=_round(record["rank_ic_ir"], 4),
                )
            daily_ic.append(point)

    group_mean_returns: dict[str, float] = {}
    if not report.group_mean_returns.empty:
        for group, value in report.group_mean_returns.items():
            number = _finite(group)
            key = f"G{int(number)}" if number is not None and number.is_integer() else str(group)
            rounded = _round(value, 6)
            if rounded is not None:
                group_mean_returns[key] = rounded

    return {
        "factor_name": report.factor_name,
        "display_name": report.display_name,
        "horizon": report.horizon,
        "n_groups": report.n_groups,
        "ic_mean": _round(report.ic_mean, 4),
        "ic_ir": _round(report.ic_ir, 3),
        "rank_ic_mean": _round(report.rank_ic_mean, 4),
        "rank_ic_ir": _round(report.rank_ic_ir, 3),
        "long_short_mean": _round(report.long_short_mean, 4),
        "first_half_ic": _round(report.first_half_ic, 4),
        "second_half_ic": _round(report.second_half_ic, 4),
        "turnover_mean": _round(report.turnover_mean, 4),
        "daily_ic": daily_ic,
        "group_mean_returns": group_mean_returns,
        "group_nav": [
            {"date": row["date"].date().isoformat(),
             **{key: _round(value, 6) for key, value in row.items() if key != "date"}}
            for row in report.group_nav.to_dict(orient="records")
        ],
        "nav_periods": report.nav_periods,
        "nav_skipped": report.nav_skipped,
        "industry_distribution": report.industry_distribution,
        "neutralization_coverage": _neutralization_coverage_to_dict(report.neutralization_coverage),
        "significance": {
            "observations": int((report.significance or {}).get("observations") or 0),
            "rank_ic_mean": _round((report.significance or {}).get("rank_ic_mean"), 4),
            "rank_ic_ir": _round((report.significance or {}).get("rank_ic_ir"), 3),
            "positive_ratio": _round((report.significance or {}).get("positive_ratio"), 4),
            "hac_t": _round((report.significance or {}).get("hac_t"), 3),
            "hac_p": _round((report.significance or {}).get("hac_p"), 4),
            "fdr_q": _round((report.significance or {}).get("fdr_q"), 4),
            "fdr_horizons": int((report.significance or {}).get("fdr_horizons") or 0),
        },
        "annual": [
            {
                "year": int(row["year"]),
                "observations": int(row["observations"]),
                "rank_ic": _round(row.get("rank_ic_mean"), 4),
                "rank_ic_ir": _round(row.get("rank_ic_ir"), 3),
                "positive_ratio": _round(row.get("positive_ratio"), 4),
                "hac_t": _round(row.get("hac_t"), 3),
                "hac_p": _round(row.get("hac_p"), 4),
            }
            for row in (report.annual.to_dict(orient="records") if not report.annual.empty else [])
        ],
        "style_correlations": list(report.style_correlations or []),
        **(
            {
                "cost_summary": {
                    "cost_bps": _round(report.cost_summary.get("cost_bps"), 1),
                    "gross_top_return": _round(report.cost_summary.get("gross_top_return"), 4),
                    "net_top_return": _round(report.cost_summary.get("net_top_return"), 4),
                    "gross_long_short_total": _round(report.cost_summary.get("gross_long_short_total"), 4),
                    "net_long_short_total": _round(report.cost_summary.get("net_long_short_total"), 4),
                    "net_long_short_mean": _round(report.cost_summary.get("net_long_short_mean"), 4),
                    "avg_top_turnover": _round(report.cost_summary.get("avg_top_turnover"), 4),
                }
            }
            if report.cost_summary
            else {}
        ),
        "rebalance_turnover": [
            {"date": day.date().isoformat(), "turnover": _round(value, 6)}
            for day, value in report.rebalance_turnover.itertuples(index=False, name=None)
        ],
        "decay": [
            {
                "horizon": int(row["horizon"]),
                "rank_ic": _round(row["rank_ic_mean"], 4),
                "rank_ic_ir": _round(row["rank_ic_ir"], 4),
                "observations": int(row["observations"]),
                "hac_t": _round(row.get("hac_t"), 3),
                "hac_p": _round(row.get("hac_p"), 4),
                "fdr_q": _round(row.get("fdr_q"), 4),
            }
            for row in report.decay.to_dict(orient="records")
        ],
        # 每条说明各自以句号结尾，接在一起时不再加分号，免得出现「。；」。
        "notes": "".join(note if note.endswith(("。", "！", "？")) else note + "。" for note in report.notes),
    }
