"""Fit factor combinations on training data and compare frozen models on a holdout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite

import pandas as pd

from quant_platform.core import deadline, progress
from quant_platform.data.extras import extra_columns
from quant_platform.data.index_constituents import UNIVERSE_COLUMN
from quant_platform.data.industry import EXPOSURES_TABLE
from quant_platform.factors.base import FactorDefinition
from quant_platform.factors.combine import STANDARDIZATIONS, combine_factors, correlation_matrix, prepare_frames, drop_highly_correlated
from quant_platform.factors.custom import CustomFactor, custom_factor_to_dict
from quant_platform.factors.evaluation import FactorEvaluator, FactorReport
from quant_platform.factors.statistics import benjamini_hochberg, fdr_verdict


@dataclass(frozen=True)
class FrameFactor(FactorDefinition):
    values: pd.DataFrame = field(default_factory=pd.DataFrame)

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        cutoff = pd.to_datetime(bars["trade_date"]).max()
        return self.values[self.values.date <= cutoff].copy()


class BoundedRepository:
    """Cap factor history, exposures, fundamentals, and forward-return prices at the phase boundary."""

    def __init__(self, repository, end: date, symbols=None):
        self.repository, self.end, self.symbols = repository, end, symbols

    def get_daily_bars(self, symbols=None, end_date=None, **options):
        cutoff = min(pd.Timestamp(end_date or self.end), pd.Timestamp(self.end)).date()
        return self.repository.get_daily_bars(
            symbols=symbols if symbols is not None else self.symbols, end_date=cutoff, **options
        )

    def read_table(self, name: str) -> pd.DataFrame:
        reader = getattr(self.repository, "read_table", None)
        if reader is None:
            return pd.DataFrame()
        frame = reader(name)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return frame
        cutoff = pd.Timestamp(self.end)
        for col in ("effective_date", "date", "trade_date"):
            if col in frame.columns:
                return frame[pd.to_datetime(frame[col], errors="coerce") <= cutoff].copy()
        return frame

    def get_fundamentals(self) -> pd.DataFrame:
        getter = getattr(self.repository, "get_fundamentals", None)
        if getter is None:
            return pd.DataFrame()
        frame = getter()
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return frame
        if "pub_date" in frame.columns:
            cutoff = pd.Timestamp(self.end)
            return frame[pd.to_datetime(frame["pub_date"], errors="coerce") <= cutoff].copy()
        return frame


@dataclass
class CombinationResult:
    weights: dict[str, float]
    correlation: pd.DataFrame
    comparison: pd.DataFrame
    reports: dict[str, FactorReport]
    spec: list[dict]
    dropped: list[str] = field(default_factory=list)
    train_signal_end: date | None = None
    purged_sessions: int = 0
    multiple_testing: dict | None = None
    neutralization: str = "none"


def research_combination(
    repository,
    components: tuple[FactorDefinition, ...],
    *,
    train_start: date,
    train_end: date,
    test_start: date,
    test_end: date,
    mode: str = "equal",
    custom_weights: dict[str, float] | None = None,
    custom_directions: dict[str, int] | None = None,
    clip: bool = True,
    missing: str = "drop",
    standardization: str = "zscore",
    neutralization: str = "none",
    horizon: int = 5,
    n_groups: int = 5,
    symbols: list[str] | None = None,
    corr_threshold: float | None = None,
) -> CombinationResult:
    if not train_start <= train_end < test_start <= test_end:
        raise ValueError("日期需满足：训练开始 ≤ 训练结束 < 测试开始 ≤ 测试结束。")
    if len(components) < 2 or len({f.name for f in components}) != len(components):
        raise ValueError("请选择至少两个不同因子。")
    if mode not in {"equal", "manual", "ic"}:
        raise ValueError("未知权重方式")
    if mode == "manual" and set(custom_weights or {}).difference(f.name for f in components):
        raise ValueError("权重包含未选择的因子。")
    if custom_directions:
        unknown_dirs = set(custom_directions).difference(f.name for f in components)
        if unknown_dirs:
            raise ValueError("因子方向包含未选择的因子。")
        for dir_val in custom_directions.values():
            if type(dir_val) is not int or dir_val not in (1, -1):
                raise ValueError("因子方向只能是 1（正向）或 -1（反向）。")
    if missing not in {"drop", "median"}:
        raise ValueError("研究组合请选择剔除缺失或中位数填充。")
    if standardization not in STANDARDIZATIONS:
        raise ValueError("未知标准化方式")
    if neutralization not in {"none", "industry", "size", "both", "industry_rank"}:
        raise ValueError("不支持的中性化方式")

    extra = extra_columns(field for factor in components for field in factor.required_fields)
    n_factors = len(components)
    # 进度总步数：训练期(加载1 + 逐因子N) + 权重拟合(N若ic否则1) + 测试期(加载1 + 逐因子N + 评估N+2) + BH-FDR汇总(1)
    total_steps = (1 + n_factors) + (n_factors if mode == "ic" else 1) + (1 + n_factors) + (n_factors + 2) + 1
    completed_steps = 0

    def advance(stage: str) -> None:
        nonlocal completed_steps
        completed_steps = min(total_steps, completed_steps + 1)
        progress.report(stage, completed_steps, total_steps)

    def frames_until(start, end, period):
        progress.report(f"加载{period}行情", completed_steps, total_steps)
        bars = repository.get_daily_bars(symbols=symbols, end_date=end, **({"extras": extra} if extra else {}))
        if bars.empty:
            raise ValueError("所选区间没有本地行情，请先更新数据。")
        advance(f"已加载{period}行情")
        # 指数当时的成分股：只有那天在指数里的股票才是样本。
        members = bars[bars[UNIVERSE_COLUMN]] if UNIVERSE_COLUMN in bars.columns else bars
        universe = members[["trade_date", "symbol"]].rename(columns={"trade_date": "date"})
        universe["date"] = pd.to_datetime(universe["date"]).dt.normalize()
        phase_universe = universe[universe["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
        phase_evaluator = (
            FactorEvaluator(BoundedRepository(repository, end, symbols))
            if neutralization != "none"
            else None
        )
        phase_changes = (
            phase_evaluator.repository.read_table(EXPOSURES_TABLE)
            if phase_evaluator is not None and neutralization in {"industry", "both", "industry_rank"}
            else None
        )
        frames = {}
        for idx, factor in enumerate(components, 1):
            deadline.check()
            label = factor.display_name or factor.name
            progress.report(f"{period}计算因子：{label} ({idx}/{len(components)})", completed_steps, total_steps)
            try:
                values = factor.compute(bars)
            except ValueError as exc:
                raise ValueError(f"{period}（{start} 至 {end}）计算失败。{exc}") from exc
            values["date"] = pd.to_datetime(values["date"]).dt.normalize()
            merged = phase_universe.merge(values, on=["date", "symbol"], how="left")
            if phase_evaluator is not None:
                progress.report(f"{period}中性化处理：{label} ({idx}/{len(components)})", completed_steps, total_steps)
                try:
                    neutralized, _, _ = phase_evaluator._neutralize_with_coverage(
                        merged,
                        bars,
                        neutralization,
                        changes=phase_changes,
                        start_date=start,
                        end_date=end,
                    )
                except ValueError as exc:
                    raise ValueError(f"{period}（{start} 至 {end}）中性化失败。{exc}") from exc
                merged = phase_universe.merge(neutralized, on=["date", "symbol"], how="left")
            frames[factor.name] = merged
            advance(f"{period}完成因子：{label} ({idx}/{len(components)})")
        sessions = pd.DatetimeIndex(pd.to_datetime(bars.trade_date).unique()).sort_values()
        return frames, sessions

    train_frames, sessions = frames_until(train_start, train_end, "训练期")
    train_frames = prepare_frames(train_frames, clip=clip, missing=missing)
    sessions = sessions[sessions >= pd.Timestamp(train_start)]
    # Labels enter on t+1 and exit on t+horizon+1. Purge all signals whose
    # labels would cross train_end, including correlation-based selection.
    purge = horizon + 1
    if len(sessions) <= purge:
        raise ValueError("训练期交易日不足，无法隔离跨边界收益标签。")
    signal_end = sessions[-(purge + 1)].date()
    train_slice = {
        name: frame[frame.date.between(pd.Timestamp(train_start), pd.Timestamp(signal_end))]
        for name, frame in train_frames.items()
    }
    if any(frame.empty for frame in train_slice.values()):
        raise ValueError("训练期清洗后没有共同样本，请扩大日期范围或补齐行情。")
    correlation = correlation_matrix(train_slice)
    dropped = drop_highly_correlated(correlation, threshold=corr_threshold, priority=[f.name for f in components]) if corr_threshold is not None else []
    components = tuple(f for f in components if f.name not in dropped)
    if len(components) < 2:
        raise ValueError("训练期剔除高相关因子后不足两个，请更换组合或调高阈值。")
    directions = {
        factor.name: int((custom_directions or {}).get(factor.name, factor.direction))
        for factor in components
    }
    weights = {}
    for idx, factor in enumerate(components, 1):
        if mode == "equal":
            weight = 1.0
        elif mode == "manual":
            weight = float((custom_weights or {}).get(factor.name, 0))
        else:
            label = factor.display_name or factor.name
            progress.report(f"训练期 IC 加权评估：{label} ({idx}/{len(components)})", completed_steps, total_steps)
            proxy = FrameFactor(
                name=factor.name,
                display_name=factor.display_name,
                direction=directions[factor.name],
                values=train_slice[factor.name],
            )
            with progress.reporting(None):
                report = FactorEvaluator(BoundedRepository(repository, train_end, symbols)).evaluate(
                    proxy, train_start, train_end, horizon=horizon, n_groups=n_groups
                )
            weight = report.rank_ic_mean
            weight = max(weight, 0.0) if isfinite(weight) else 0.0
            advance(f"训练期完成权重评估：{label} ({idx}/{len(components)})")
        if not isfinite(weight) or weight < 0:
            raise ValueError("权重必须是非负有限数值；如需反转因子请切换因子方向。")
        weights[factor.name] = weight
    if mode != "ic":
        advance("训练期相关性与权重拟合完成")
    scale = max(weights.values())
    if scale <= 0:
        raise ValueError("没有正权重：请调整手动权重，或改用等权；训练期负 IC 不会自动取绝对值。")
    weights = {name: value / scale for name, value in weights.items()}
    total = sum(weights.values())
    weights = {name: value / total for name, value in weights.items()}

    # The test set is accessed only after all weights are fixed.
    frames, _ = frames_until(test_start, test_end, "测试期")
    frames = {f.name: frames[f.name] for f in components}
    cleaned = prepare_frames(frames, clip=clip, missing=missing)
    candidates = {
        f"单因子 · {factor.display_name} ({factor.name})": FrameFactor(
            name=factor.name,
            display_name=factor.display_name,
            direction=directions[factor.name],
            values=cleaned[factor.name],
        )
        for factor in components
    }
    for label, model_weights in [
        ("等权组合", {f.name: 1.0 for f in components}),
        ("我的组合", weights),
    ]:
        candidates[label] = FrameFactor(
            name=label,
            display_name=label,
            values=combine_factors(
                frames, model_weights, directions=directions, clip=clip, missing=missing,
                standardization=standardization,
            ),
        )
    reports = {}
    rows = []
    single_indices: list[int] = []
    single_p_values: list[float | None] = []
    evaluator = FactorEvaluator(BoundedRepository(repository, test_end, symbols))
    total_candidates = len(candidates)
    for idx, (label, factor) in enumerate(candidates.items(), 1):
        deadline.check()
        progress.report(f"测试期评估方案：{label} ({idx}/{total_candidates})", completed_steps, total_steps)
        with progress.reporting(None):
            report = evaluator.evaluate(
                factor, test_start, test_end, horizon=horizon, n_groups=n_groups
            )
        advance(f"测试期完成评估：{label} ({idx}/{total_candidates})")
        reports[label] = report
        sig = report.significance or {}
        hac_t = sig.get("hac_t")
        hac_p = sig.get("hac_p")
        is_single = label.startswith("单因子 · ")
        if is_single:
            single_indices.append(len(rows))
            single_p_values.append(hac_p if hac_p is not None and isfinite(float(hac_p)) else None)
        rows.append(
            {
                "方案": label,
                "Rank IC": report.rank_ic_mean,
                "Rank IC IR": report.rank_ic_ir,
                "IC": report.ic_mean,
                "同日多空收益差": report.long_short_mean,
                "成员更替率": report.turnover_mean,
                "有效 IC 天数": int(report.daily_ic.rank_ic.notna().sum()),
                "HAC t 值": hac_t,
                "HAC p 值": hac_p,
                "BH-FDR q 值": float("nan"),
                "多重检验结论": (
                    "组合方案"
                    if not is_single
                    else "样本不足"
                ),
            }
        )
    if not any(row["有效 IC 天数"] for row in rows):
        raise ValueError("测试期没有有效 IC 样本，请检查日期、股票数量和因子是否为常数。")

    q_values = benjamini_hochberg(single_p_values)
    for row_idx, q_val in zip(single_indices, q_values, strict=True):
        rows[row_idx]["BH-FDR q 值"] = float("nan") if q_val is None else q_val
        rows[row_idx]["多重检验结论"] = fdr_verdict(q_val)
    for row_idx, row in enumerate(rows):
        if row_idx in single_indices:
            continue
        p_val = row.get("HAC p 值")
        if p_val is None or not isfinite(float(p_val)):
            row["多重检验结论"] = "组合 · 样本不足"
        elif float(p_val) < 0.05:
            row["多重检验结论"] = "组合 · p<0.05"
        else:
            row["多重检验结论"] = "组合 · 未达5%"

    valid_ps = [p for p in single_p_values if p is not None]
    valid_qs = [q for q in q_values if q is not None]
    multiple_testing = {
        "method": "BH-FDR",
        "tested_factors": len(valid_ps),
        "total_factors": len(single_indices),
        "raw_passed_005": sum(1 for p in valid_ps if p < 0.05),
        "passed_005": sum(1 for q in valid_qs if q < 0.05),
        "passed_010": sum(1 for q in valid_qs if q < 0.10),
    }
    completed_steps = total_steps
    progress.report("完成 BH-FDR 多重检验校正与结果汇总", total_steps, total_steps)

    spec = [
        {
            "name": f.name, "display_name": f.display_name or f.name, "version": f.version,
            "weight": weights[f.name], "direction": directions[f.name],
            "clip": clip, "missing": missing, "standardization": standardization,
            **({"neutralization": neutralization} if neutralization != "none" else {}),
            **({"custom_factor": custom_factor_to_dict(f)} if isinstance(f, CustomFactor) else {}),
        }
        for f in components
    ]
    return CombinationResult(
        weights, correlation, pd.DataFrame(rows), reports, spec, dropped, signal_end, purge, multiple_testing, neutralization
    )
