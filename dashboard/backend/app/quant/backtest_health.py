"""回测白话体检卡：基于已落盘回测明细做 4 项确定性体检（零模型依赖、无前视偏差）。

1. 单股运气依赖：剥离头号盈利股后的组合收益变化；
2. 交易成本翻倍抗压：若实盘佣金、印花税与滑点翻倍，收益是否仍站得住；
3. 行业集中与大小盘偏向：全区间持仓平均行业权重与点时市值风格；
4. 最难熬回撤与空仓时长：最长未创新高交易日数、最大回撤区间与空仓占比。
"""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_platform.data.fundamentals import market_capitalization, point_in_time
from quant_platform.data.industry import industry_on

from .symbols import to_bare, to_canonical


def _read_parquet(directory: Path | None, name: str) -> pd.DataFrame:
    if directory is None:
        return pd.DataFrame()
    path = directory / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        return pd.DataFrame()


def _read_summary(directory: Path | None) -> dict[str, Any]:
    if directory is None:
        return {}
    path = directory / "summary.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if isfinite(num) else None


def _fmt_pct(value: float, signed: bool = True) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _symbol_label(symbol: str, names: dict[str, str]) -> str:
    canonical = to_canonical(symbol)
    bare = to_bare(canonical)
    name = names.get(canonical) or names.get(bare)
    return f"{name}（{bare}）" if name else bare


def _resolve_capital(
    result: dict[str, Any], summary: dict[str, Any], nav: pd.DataFrame
) -> tuple[float | None, float | None]:
    cfg = result.get("effective_config") or {}
    initial = (
        _safe_float(summary.get("initial_cash"))
        or _safe_float(cfg.get("initial_capital"))
    )
    final = _safe_float(summary.get("final_equity")) or _safe_float(result.get("final_equity"))
    if not nav.empty and "equity" in nav.columns:
        eq = pd.to_numeric(nav["equity"], errors="coerce").dropna()
        if not eq.empty:
            if final is None:
                final = float(eq.iloc[-1])
            if initial is None:
                initial = float(eq.iloc[0])
    elif isinstance(result.get("equity"), list) and result["equity"]:
        eq_vals = [_safe_float(v) for v in result["equity"]]
        eq_vals = [v for v in eq_vals if v is not None]
        if eq_vals:
            if final is None:
                final = eq_vals[-1]
            if initial is None:
                initial = eq_vals[0]
    if initial is not None and initial <= 0:
        initial = None
    return initial, final


# --------------------------------------------------------------------------- #
# 1. 单股运气依赖
# --------------------------------------------------------------------------- #


def _check_single_stock(
    trades: pd.DataFrame,
    positions: pd.DataFrame,
    initial_cash: float | None,
    final_equity: float | None,
    names: dict[str, str],
) -> dict[str, Any]:
    pnl_by_symbol: dict[str, float] = {}
    if not trades.empty and {"symbol", "net_pnl"}.issubset(trades.columns):
        grouped = (
            trades.assign(
                symbol=trades["symbol"].astype(str).map(to_canonical),
                net_pnl=pd.to_numeric(trades["net_pnl"], errors="coerce"),
            )
            .dropna(subset=["net_pnl"])
            .groupby("symbol", observed=True)["net_pnl"]
            .sum()
        )
        for sym, val in grouped.items():
            pnl_by_symbol[str(sym)] = pnl_by_symbol.get(str(sym), 0.0) + float(val)

    # 加上回测期末仍持有的未平仓浮动盈亏，避免长持牛股因未卖出而被低估
    if not positions.empty and {"trade_date", "symbol", "quantity", "average_cost", "close"}.issubset(positions.columns):
        pos = positions.copy()
        pos["trade_date"] = pd.to_datetime(pos["trade_date"], errors="coerce")
        last_day = pos["trade_date"].max()
        if pd.notna(last_day):
            tail = pos[pos["trade_date"].eq(last_day)]
            for row in tail.to_dict(orient="records"):
                qty = _safe_float(row.get("quantity")) or 0.0
                avg = _safe_float(row.get("average_cost"))
                close = _safe_float(row.get("close"))
                if qty > 0 and avg is not None and close is not None:
                    sym = to_canonical(str(row["symbol"]))
                    pnl_by_symbol[sym] = pnl_by_symbol.get(sym, 0.0) + qty * (close - avg)

    if not pnl_by_symbol or initial_cash is None or final_equity is None:
        return {
            "key": "single_stock",
            "title": "单股运气依赖",
            "status": "neutral",
            "tag": "暂无明细",
            "headline": "没有足够的个股盈亏明细，无法检测单股依赖。",
            "detail": "本次回测可能全程空仓或缺少历史成交归档。",
            "metrics": {},
        }

    ranked = sorted(pnl_by_symbol.items(), key=lambda item: -item[1])
    top1_sym, top1_pnl = ranked[0]
    worst_sym, worst_pnl = ranked[-1]
    total_pnl = final_equity - initial_cash
    total_return = total_pnl / initial_cash
    top1_label = _symbol_label(top1_sym, names)
    worst_label = _symbol_label(worst_sym, names)
    symbol_count = len(pnl_by_symbol)

    if total_pnl <= 0:
        detail = f"共交易 {symbol_count} 只股票；最大拖累为 {worst_label}（¥{worst_pnl:,.0f}）"
        if top1_pnl > 0:
            detail += f"，最大正贡献为 {top1_label}（+¥{top1_pnl:,.0f}）。"
        else:
            detail += "。"
        return {
            "key": "single_stock",
            "title": "单股运气依赖",
            "status": "neutral",
            "tag": "整体未盈利",
            "headline": f"本次回测累计收益 {_fmt_pct(total_return)}，暂不适用盈利集中度判断。",
            "detail": detail,
            "metrics": {
                "traded_symbols": symbol_count,
                "worst_symbol": to_bare(worst_sym),
                "worst_pnl": round(worst_pnl, 2),
            },
        }

    top1_share = top1_pnl / total_pnl if top1_pnl > 0 else 0.0
    top3_pnl = sum(val for _, val in ranked[:3] if val > 0)
    top3_share = top3_pnl / total_pnl
    return_without_top1 = ((final_equity - max(top1_pnl, 0.0)) - initial_cash) / initial_cash

    if return_without_top1 <= 0 or top1_share >= 0.50:
        status, tag = "warn", "高度依赖单股"
        headline = f"去掉最赚钱的 {top1_label} 后，收益从 {_fmt_pct(total_return)} 变为 {_fmt_pct(return_without_top1)}。"
        detail = (
            f"单只股票贡献了 {top1_share * 100:.0f}% 的利润（前 3 只合计占 {top3_share * 100:.0f}%），"
            "存在明显的“撞牛股”风险，建议扩大持股数量或拉长回测区间复核。"
        )
    elif top1_share >= 0.30:
        status, tag = "caution", "盈利有一定集中"
        headline = f"头号盈利股 {top1_label} 贡献了 {top1_share * 100:.0f}% 的收益。"
        detail = (
            f"去掉该股后累计收益仍为 {_fmt_pct(return_without_top1)}（原 {_fmt_pct(total_return)}），"
            f"前 3 只合计占 {top3_share * 100:.0f}%，共参与 {symbol_count} 只股票。"
        )
    else:
        status, tag = "ok", "盈利来源分散"
        headline = f"去掉头号盈利股 {top1_label} 后，收益仍有 {_fmt_pct(return_without_top1)}（原 {_fmt_pct(total_return)}）。"
        detail = (
            f"头号盈利股仅占总盈利的 {top1_share * 100:.0f}%（前 3 只占 {top3_share * 100:.0f}%），"
            f"共参与 {symbol_count} 只股票，不依赖单一牛股。"
        )

    return {
        "key": "single_stock",
        "title": "单股运气依赖",
        "status": status,
        "tag": tag,
        "headline": headline,
        "detail": detail,
        "metrics": {
            "traded_symbols": symbol_count,
            "top1_symbol": to_bare(top1_sym),
            "top1_label": top1_label,
            "top1_pnl": round(top1_pnl, 2),
            "top1_share": round(top1_share, 4),
            "top3_share": round(top3_share, 4),
            "return_without_top1": round(return_without_top1, 4),
        },
    }


# --------------------------------------------------------------------------- #
# 2. 交易成本翻倍抗压
# --------------------------------------------------------------------------- #


def _check_cost_stress(
    result: dict[str, Any],
    summary: dict[str, Any],
    initial_cash: float | None,
    final_equity: float | None,
) -> dict[str, Any]:
    total_cost = _safe_float(summary.get("total_transaction_cost"))
    if total_cost is None:
        total_cost = _safe_float(result.get("total_cost"))
    if total_cost is None:
        parts = [
            _safe_float(result.get(key)) or 0.0
            for key in ("commission", "stamp_tax", "slippage_cost")
        ]
        total_cost = sum(parts) if any(parts) else 0.0

    if initial_cash is None or final_equity is None:
        return {
            "key": "cost_stress",
            "title": "交易成本翻倍抗压",
            "status": "neutral",
            "tag": "暂无数据",
            "headline": "缺少资金与费用记录，无法测算成本敏感度。",
            "detail": "",
            "metrics": {},
        }

    base_return = (final_equity - initial_cash) / initial_cash
    cost_ratio = total_cost / initial_cash
    doubled_return = ((final_equity - total_cost) - initial_cash) / initial_cash

    if total_cost <= 0:
        return {
            "key": "cost_stress",
            "title": "交易成本翻倍抗压",
            "status": "neutral",
            "tag": "无交易费用",
            "headline": "本次回测未产生交易成本。",
            "detail": "全程无成交或费用为零。",
            "metrics": {"total_cost": 0.0, "cost_ratio": 0.0},
        }

    net_profit = final_equity - initial_cash
    if base_return > 0 and doubled_return <= 0:
        status, tag = "warn", "对成本高度敏感"
        headline = f"若实盘费用与滑点翻倍，收益将从 {_fmt_pct(base_return)} 跌为 {_fmt_pct(doubled_return)}。"
        detail = (
            f"当前已产生总成本 ¥{total_cost:,.0f}（占初始资金 {cost_ratio * 100:.1f}%），"
            "稍高的实盘滑点就会吞掉全部收益；建议降低调仓频率或开启防频繁换手缓冲。"
        )
    elif base_return > 0 and (total_cost / max(net_profit, 1e-9)) >= 0.35:
        status, tag = "caution", "成本吞噬偏高"
        headline = f"费用与滑点翻倍后，收益从 {_fmt_pct(base_return)} 降至 {_fmt_pct(doubled_return)}。"
        detail = (
            f"当前总成本 ¥{total_cost:,.0f}（占初始资金 {cost_ratio * 100:.1f}%），"
            "换手摩擦较大，实盘需留意流动性与冲击成本。"
        )
    elif base_return <= 0:
        status, tag = ("warn" if cost_ratio >= 0.05 else "neutral"), ("高换手放大亏损" if cost_ratio >= 0.05 else "成本可控")
        headline = f"当前累计交易成本 ¥{total_cost:,.0f}（占初始资金 {cost_ratio * 100:.1f}%）。"
        detail = f"若费用翻倍，累计收益将从 {_fmt_pct(base_return)} 进一步变为 {_fmt_pct(doubled_return)}。"
    else:
        status, tag = "ok", "抗成本能力良好"
        headline = f"费用与滑点翻倍后，收益仍有 {_fmt_pct(doubled_return)}（原 {_fmt_pct(base_return)}）。"
        detail = f"当前总成本 ¥{total_cost:,.0f}（占初始资金 {cost_ratio * 100:.1f}%），受常规滑点波动影响较小。"

    return {
        "key": "cost_stress",
        "title": "交易成本翻倍抗压",
        "status": status,
        "tag": tag,
        "headline": headline,
        "detail": detail,
        "metrics": {
            "total_cost": round(total_cost, 2),
            "cost_ratio": round(cost_ratio, 4),
            "base_return": round(base_return, 4),
            "doubled_cost_return": round(doubled_return, 4),
        },
    }


# --------------------------------------------------------------------------- #
# 3. 行业集中与大小盘偏向
# --------------------------------------------------------------------------- #


def _check_exposure_bias(
    positions: pd.DataFrame,
    exposures: pd.DataFrame | None,
    fundamentals: pd.DataFrame | None,
) -> dict[str, Any]:
    if positions.empty or not {"trade_date", "symbol", "market_value"}.issubset(positions.columns):
        return {
            "key": "exposure_bias",
            "title": "行业集中与大小盘偏向",
            "status": "neutral",
            "tag": "暂无持仓",
            "headline": "缺少逐日持仓明细或全程空仓，无法评估行业与市值偏向。",
            "detail": "",
            "metrics": {},
        }

    pos = positions[["trade_date", "symbol", "market_value"]].copy()
    if "close" in positions.columns:
        pos["close"] = pd.to_numeric(positions["close"], errors="coerce")
    pos["date"] = pd.to_datetime(pos["trade_date"], errors="coerce").dt.normalize()
    pos["symbol"] = pos["symbol"].astype(str).map(to_canonical)
    pos["market_value"] = pd.to_numeric(pos["market_value"], errors="coerce").fillna(0.0)
    pos = pos[pos["date"].notna() & pos["market_value"].gt(0)]
    if pos.empty:
        return {
            "key": "exposure_bias",
            "title": "行业集中与大小盘偏向",
            "status": "neutral",
            "tag": "全程空仓",
            "headline": "回测期间没有有效股票持仓。",
            "detail": "",
            "metrics": {},
        }

    day_totals = pos.groupby("date", observed=True)["market_value"].transform("sum")
    pos["weight"] = pos["market_value"] / day_totals.where(day_totals > 0)
    holding_days = int(pos["date"].nunique())

    # 行业平均权重（点时匹配，不向后回填）
    top_industries: list[dict[str, Any]] = []
    top2_weight: float | None = None
    if exposures is not None and not exposures.empty and "industry" in exposures.columns:
        try:
            ind_series = industry_on(pos[["date", "symbol"]], exposures, infer_early=False)
            pos_ind = pos.assign(industry=ind_series.fillna("未分类"))
            daily_ind = (
                pos_ind.groupby(["date", "industry"], observed=True)["weight"].sum().reset_index()
            )
            avg_ind = (
                daily_ind.groupby("industry", observed=True)["weight"].sum() / max(holding_days, 1)
            ).sort_values(ascending=False)
            named_ind = avg_ind[avg_ind.index != "未分类"]
            if not named_ind.empty:
                top_industries = [
                    {"industry": str(name), "weight": round(float(val), 4)}
                    for name, val in named_ind.head(3).items()
                ]
                top2_weight = float(named_ind.head(2).sum())
        except Exception:  # noqa: BLE001 - optional exposure lookup
            pass

    # 大小盘偏向（点时总股本 × 当日收盘价 -> 持仓加权平均市值，单位：亿元）
    avg_cap_yi: float | None = None
    size_bucket: str | None = None
    size_label = ""
    if (
        fundamentals is not None
        and not fundamentals.empty
        and "total_shares" in fundamentals.columns
        and "close" in pos.columns
    ):
        try:
            days_df = pos[["date", "symbol", "close", "weight"]].rename(columns={"date": "trade_date"})
            days_df = days_df[days_df["close"].gt(0)]
            if not days_df.empty:
                shares = point_in_time(days_df, fundamentals, ["total_shares"])["total_shares"]
                cap = market_capitalization(days_df["close"], shares)
                valid_cap = cap.gt(0).fillna(False)
                coverage = float(valid_cap.mean())
                if coverage >= 0.30:
                    w = days_df.loc[valid_cap, "weight"].to_numpy(dtype=float)
                    c = cap.loc[valid_cap].to_numpy(dtype=float) / 1e8  # 换算为亿元
                    if w.sum() > 0:
                        avg_cap_yi = float(np.average(c, weights=w))
                        if avg_cap_yi >= 500.0:
                            size_bucket, size_label = "large", f"偏大盘（持仓加权平均市值 {avg_cap_yi:,.0f} 亿）"
                        elif avg_cap_yi >= 100.0:
                            size_bucket, size_label = "mid", f"偏中盘（持仓加权平均市值 {avg_cap_yi:,.0f} 亿）"
                        else:
                            size_bucket, size_label = "small", f"偏小盘（持仓加权平均市值 {avg_cap_yi:,.0f} 亿）"
        except Exception:  # noqa: BLE001 - optional fundamentals lookup
            pass

    if not top_industries and not size_label:
        return {
            "key": "exposure_bias",
            "title": "行业集中与大小盘偏向",
            "status": "neutral",
            "tag": "缺少暴露数据",
            "headline": "当前区间缺少对应的行业分类或历史总股本数据。",
            "detail": f"共持仓 {holding_days} 个交易日，补齐行业分类和季度股本数据后会自动展示偏向分析。",
            "metrics": {"holding_days": holding_days},
        }

    ind_summary = "、".join(f"{item['industry']} {item['weight'] * 100:.0f}%" for item in top_industries[:2])
    if top2_weight is not None and top2_weight >= 0.60:
        status, tag = "warn", "行业高度集中"
        headline = f"前两大行业平均占比达 {top2_weight * 100:.0f}%（{ind_summary}）。"
    elif (top2_weight is not None and top2_weight >= 0.40) or size_bucket == "small":
        status, tag = "caution", "存在风格偏向"
        parts = []
        if top2_weight is not None:
            parts.append(f"前两大行业平均占 {top2_weight * 100:.0f}%（{ind_summary}）")
        if size_label:
            parts.append(size_label)
        headline = "，".join(parts) + "。"
    else:
        status, tag = "ok", "暴露较均衡"
        parts = []
        if top2_weight is not None:
            parts.append(f"前两大行业占 {top2_weight * 100:.0f}%（{ind_summary}）")
        if size_label:
            parts.append(size_label)
        headline = "，".join(parts) + "。"

    detail_parts = []
    if top_industries:
        all_top = "、".join(f"{item['industry']}（{item['weight'] * 100:.1f}%）" for item in top_industries)
        detail_parts.append(f"全区间平均仓位前三行业：{all_top}")
    if size_label:
        detail_parts.append(f"市值风格：{size_label}")
    if size_bucket == "small":
        detail_parts.append("小盘策略实盘需重点关注成交容量与风格轮动回撤")

    return {
        "key": "exposure_bias",
        "title": "行业集中与大小盘偏向",
        "status": status,
        "tag": tag,
        "headline": headline,
        "detail": "；".join(detail_parts) + "。",
        "metrics": {
            "holding_days": holding_days,
            "top_industries": top_industries,
            "top2_industry_weight": round(top2_weight, 4) if top2_weight is not None else None,
            "avg_market_cap_yi": round(avg_cap_yi, 1) if avg_cap_yi is not None else None,
            "size_bucket": size_bucket,
        },
    }


# --------------------------------------------------------------------------- #
# 4. 最难熬回撤与空仓时长
# --------------------------------------------------------------------------- #


def _check_drawdown_endurance(nav: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    dates: list[str] = []
    equities: list[float] = []
    exposures_arr: list[float] = []

    if not nav.empty and "equity" in nav.columns:
        eq = pd.to_numeric(nav["equity"], errors="coerce")
        valid = eq.notna() & eq.gt(0)
        sub = nav.loc[valid].copy()
        if not sub.empty:
            equities = [float(v) for v in pd.to_numeric(sub["equity"], errors="coerce")]
            if "trade_date" in sub.columns:
                dates = [ts.date().isoformat() for ts in pd.to_datetime(sub["trade_date"], errors="coerce")]
            if "market_value" in sub.columns:
                mv = pd.to_numeric(sub["market_value"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                eq_np = np.asarray(equities, dtype=float)
                exposures_arr = [float(m / e) if e > 0 else 0.0 for m, e in zip(mv, eq_np, strict=True)]
    elif isinstance(result.get("equity"), list) and result["equity"]:
        raw_eq = result["equity"]
        raw_dates = result.get("nav_dates") or []
        for idx, val in enumerate(raw_eq):
            num = _safe_float(val)
            if num is not None and num > 0:
                equities.append(num)
                if idx < len(raw_dates):
                    dates.append(str(raw_dates[idx]))

    if len(equities) < 2:
        return {
            "key": "drawdown_endurance",
            "title": "最难熬回撤与空仓时长",
            "status": "neutral",
            "tag": "区间过短",
            "headline": "净值点数不足，无法评估回撤修复周期。",
            "detail": "",
            "metrics": {},
        }

    peak = equities[0]
    peak_idx = 0
    current_underwater = 0
    max_underwater = 0
    underwater_unrecovered = False
    max_dd = 0.0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0

    for idx, value in enumerate(equities):
        if value >= peak - 1e-9:
            peak = value
            peak_idx = idx
            current_underwater = 0
        else:
            current_underwater += 1
            if current_underwater > max_underwater:
                max_underwater = current_underwater
                underwater_unrecovered = idx == len(equities) - 1
            elif current_underwater == max_underwater and idx == len(equities) - 1:
                underwater_unrecovered = True
            dd = value / peak - 1.0
            if dd < max_dd:
                max_dd = dd
                max_dd_peak_idx = peak_idx
                max_dd_trough_idx = idx

    total_days = len(equities)
    avg_exposure = float(np.mean(exposures_arr)) if exposures_arr else None
    empty_days = sum(1 for x in exposures_arr if x < 0.05) if exposures_arr else None
    empty_ratio = (empty_days / total_days) if empty_days is not None else None

    if max_underwater >= 120:
        status, tag = "warn", "套牢期较长"
    elif max_underwater >= 60:
        status, tag = "caution", "季度级波动"
    else:
        status, tag = "ok", "修复较快"

    suffix = "（截至回测结束尚未创新高）" if underwater_unrecovered and max_underwater > 0 else ""
    headline = f"最长连续 {max_underwater} 个交易日未创新高{suffix}。"

    detail_parts: list[str] = []
    if max_dd < 0 and dates and max_dd_trough_idx < len(dates):
        detail_parts.append(
            f"最大回撤 {abs(max_dd) * 100:.1f}%（发生在 {dates[max_dd_peak_idx]} 至 {dates[max_dd_trough_idx]}）"
        )
    if avg_exposure is not None and empty_days is not None and empty_ratio is not None:
        detail_parts.append(
            f"平均股票仓位 {avg_exposure * 100:.0f}%，空仓或极轻仓 {empty_days} 天（占 {empty_ratio * 100:.0f}%）"
        )

    return {
        "key": "drawdown_endurance",
        "title": "最难熬回撤与空仓时长",
        "status": status,
        "tag": tag,
        "headline": headline,
        "detail": "；".join(detail_parts) + ("。" if detail_parts else ""),
        "metrics": {
            "total_days": total_days,
            "max_underwater_days": max_underwater,
            "underwater_unrecovered": underwater_unrecovered,
            "max_drawdown": round(abs(max_dd), 4),
            "avg_exposure": round(avg_exposure, 4) if avg_exposure is not None else None,
            "empty_days": empty_days,
            "empty_ratio": round(empty_ratio, 4) if empty_ratio is not None else None,
        },
    }


def backtest_health_check(
    directory: Path | None,
    result: dict[str, Any],
    *,
    names: dict[str, str] | None = None,
    exposures: pd.DataFrame | None = None,
    fundamentals: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute the 4 plain-Chinese diagnostic health checks for a persisted backtest run."""

    nav = _read_parquet(directory, "nav")
    trades = _read_parquet(directory, "trades")
    positions = _read_parquet(directory, "positions")
    summary = _read_summary(directory)
    initial_cash, final_equity = _resolve_capital(result, summary, nav)

    items = [
        _check_single_stock(trades, positions, initial_cash, final_equity, names or {}),
        _check_cost_stress(result, summary, initial_cash, final_equity),
        _check_exposure_bias(positions, exposures, fundamentals),
        _check_drawdown_endurance(nav, result),
    ]
    statuses = [item["status"] for item in items]
    warn_count = statuses.count("warn")
    caution_count = statuses.count("caution")
    if warn_count:
        summary_status = "warn"
        summary_badge = f"{warn_count} 项高风险提醒"
    elif caution_count:
        summary_status = "caution"
        summary_badge = f"{caution_count} 项需留意"
    elif "ok" in statuses:
        summary_status = "ok"
        summary_badge = "四项体检整体稳健"
    else:
        summary_status = "neutral"
        summary_badge = "样本不足，仅供参考"

    return {
        "summary_status": summary_status,
        "summary_badge": summary_badge,
        "items": items,
    }
