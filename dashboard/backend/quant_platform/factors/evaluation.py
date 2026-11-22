"""因子评估：IC / 分层收益 / 换手率 / 样本外稳定性。

因果性约定（防未来函数）：

- 因子值只用 ``<= end_date`` 的行情计算（评估区间内 t 日因子天然只依赖
  t 日及之前的数据，见 ``base.FactorDefinition`` 约定）；
- 未来收益严格定义为 t+1 日收盘买入、t+N+1 日收盘卖出：
  ``fwd_ret(t) = close(t+N+1) / close(t+1) - 1``（持有 N 个交易日）；
- IC 与分层统计均使用「因子值 × direction」后的调整值，
  因此正的 IC / 正的多空收益代表因子按预期方向有效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from quant_platform.core import deadline, progress
from quant_platform.data.extras import extra_columns
from quant_platform.data.fundamentals import MISSING_FUNDAMENTALS_MESSAGE, market_capitalization, point_in_time
from quant_platform.data.index_constituents import UNIVERSE_COLUMN, only_members
from quant_platform.data.industry import EXPOSURES_TABLE, MISSING_INDUSTRY_MESSAGE, industry_on
from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository
from quant_platform.factors.base import FactorDefinition, pivot_field
from quant_platform.factors.sample import FactorSampleFilters
from quant_platform.factors.statistics import annual_ic, ic_statistics, neutralize_exposures


ROLLING_IC_WINDOW = 60
ROLLING_IC_MIN_OBSERVATIONS = 20
LOW_COVERAGE_THRESHOLD = 0.8
LOW_YEAR_COVERAGE_THRESHOLD = 0.5
MISSING_EDGE_DAYS_THRESHOLD = 20


@dataclass(frozen=True)
class FactorReport:
    """单因子评估报告，全部为 DataFrame / 标量，便于网页直接展示。"""

    factor_name: str
    display_name: str
    horizon: int
    n_groups: int
    daily_ic: pd.DataFrame  # date / ic / rank_ic
    ic_mean: float
    ic_ir: float
    rank_ic_mean: float
    rank_ic_ir: float
    group_returns: pd.DataFrame  # date / group / ret
    group_mean_returns: pd.Series  # group -> 平均未来收益
    long_short_mean: float  # 顶组 - 底组 平均收益
    turnover: pd.DataFrame  # date / turnover（相邻期 top 组换手）
    turnover_mean: float
    first_half_ic: float  # 样本前半段 Rank IC 均值
    second_half_ic: float  # 样本后半段 Rank IC 均值
    notes: list[str] = field(default_factory=list)
    significance: dict = field(default_factory=dict)
    annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    decay: pd.DataFrame = field(default_factory=pd.DataFrame)
    group_nav: pd.DataFrame = field(default_factory=pd.DataFrame)
    rebalance_turnover: pd.DataFrame = field(default_factory=pd.DataFrame)
    nav_periods: int = 0
    nav_skipped: int = 0
    industry_distribution: dict | None = None
    neutralization_coverage: dict | None = None
    style_correlations: list[dict] = field(default_factory=list)
    cost_summary: dict | None = None


class FactorEvaluator:
    """基于本地行情仓库的因子评估器。"""

    def __init__(self, repository: ParquetMarketDataRepository) -> None:
        self.repository = repository

    def _neutralized(
        self, values: pd.DataFrame, bars: pd.DataFrame, neutralization: str, *, changes: pd.DataFrame | None = None,
    ) -> tuple[pd.DataFrame, list[str]]:
        """去掉因子值里能被行业和（或）市值解释的部分，只用每个交易日当时已知的行业和市值。

        没有行业分类或市值的样本不参与，并在说明里写明数量；不会拿空值硬算。
        """

        result, notes, _ = self._neutralize_with_coverage(values, bars, neutralization, changes=changes)
        return result, notes

    def _neutralize_with_coverage(
        self,
        values: pd.DataFrame,
        bars: pd.DataFrame,
        neutralization: str,
        *,
        changes: pd.DataFrame | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[pd.DataFrame, list[str], dict]:
        sample = values[["date", "symbol", "value"]].copy().reset_index(drop=True)
        sample["value"] = pd.to_numeric(sample["value"], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
        sample["date"] = pd.to_datetime(sample["date"]).astype("datetime64[ns]")
        exposures = sample[["date", "symbol"]].copy()
        needs_industry = neutralization in {"industry", "both", "industry_rank"}
        needs_size = neutralization in {"size", "both"}
        has_industry: pd.Series | None = None
        has_size: pd.Series | None = None
        usable = pd.Series(True, index=sample.index)
        if needs_industry:
            if changes is None:
                changes = self.repository.read_table(EXPOSURES_TABLE)
            if changes.empty or "industry" not in changes.columns:
                raise ValueError(MISSING_INDUSTRY_MESSAGE)
            exposures["industry"] = industry_on(exposures, changes, infer_early=False).to_numpy()
            has_industry = exposures["industry"].notna()
            usable &= has_industry
        if needs_size:
            days = bars[["symbol", "trade_date", "raw_close"]].copy()
            days["trade_date"] = pd.to_datetime(days["trade_date"]).astype("datetime64[ns]")
            days = days[days["trade_date"].isin(sample["date"].unique())]
            shares = point_in_time(days, self.repository.get_fundamentals(), ["total_shares"])["total_shares"]
            days["market_cap"] = market_capitalization(days["raw_close"], shares)
            if not days["market_cap"].notna().any():
                raise ValueError(MISSING_FUNDAMENTALS_MESSAGE)
            exposures = exposures.merge(
                days.rename(columns={"trade_date": "date"})[["date", "symbol", "market_cap"]], on=["date", "symbol"], how="left"
            )
            has_size = exposures["market_cap"].gt(0).fillna(False)
            usable &= has_size.to_numpy()
        notes: list[str] = []
        dropped = int((~usable).sum())
        if dropped:
            notes.append(f"{dropped} 个样本缺少当时的行业分类或市值，没有参与中性化（共 {len(sample)} 个样本）")
        if not usable.any():
            raise ValueError("所选区间没有同时满足要求的历史行业或市值数据。")
        available = sample[usable]
        if neutralization == "industry_rank":
            available = available.assign(industry=exposures.loc[usable, "industry"]).dropna(subset=["value"])
            peers = available.groupby(["date", "industry"], observed=True)["value"]
            sizes = peers.transform("size")
            ranks = (peers.rank(method="average") - 0.5) / sizes
            result = available.loc[sizes.ge(2), ["date", "symbol"]].assign(value=ranks)
            small_groups = int(sizes.lt(2).sum())
            if small_groups:
                notes.append(f"{small_groups} 个样本的当日行业内有效股票不足两只，没有参与行业内排序")
            if result.empty:
                raise ValueError("各行业的有效股票太少，无法进行行业内排序。")
        else:
            try:
                result = neutralize_exposures(available, exposures[usable], neutralization)
            except ValueError as exc:
                if "样本不足" not in str(exc):
                    raise
                raise ValueError(
                    "股票数量太少，做不了中性化：每个交易日的股票数要明显多于行业数。可以扩大股票池，或者不做中性化。"
                ) from exc
            skipped = available["date"].nunique() - result["date"].nunique()
            if skipped:
                notes.append(f"{skipped} 个交易日的有效股票不足以估计中性化模型，已跳过")
        coverage = self._build_neutralization_coverage(
            sample,
            available,
            result,
            neutralization=neutralization,
            has_industry=has_industry,
            has_size=has_size,
            usable=usable,
            start_date=start_date,
            end_date=end_date,
        )
        return result, notes, coverage

    @staticmethod
    def _build_neutralization_coverage(
        sample: pd.DataFrame,
        available: pd.DataFrame,
        result: pd.DataFrame,
        *,
        neutralization: str,
        has_industry: pd.Series | None,
        has_size: pd.Series | None,
        usable: pd.Series,
        start_date: date | None,
        end_date: date | None,
    ) -> dict:
        sample_dates = pd.DatetimeIndex(sample["date"].dropna().unique()).sort_values()
        effective_dates = pd.DatetimeIndex(result["date"].dropna().unique()).sort_values()
        available_dates = pd.DatetimeIndex(available["date"].dropna().unique()).sort_values()

        total_samples = int(len(sample))
        usable_samples = int(usable.sum())
        effective_samples = int(len(result))
        total_days = int(len(sample_dates))
        effective_days = int(len(effective_dates))
        skipped_days = max(0, int(len(available_dates)) - effective_days)

        industry_cov = float(has_industry.mean()) if has_industry is not None and total_samples else None
        size_cov = float(has_size.mean()) if has_size is not None and total_samples else None
        joint_cov = float(usable.mean()) if total_samples else 0.0

        eff_start_ts = effective_dates[0] if len(effective_dates) else None
        eff_end_ts = effective_dates[-1] if len(effective_dates) else None
        leading_missing_days = int((sample_dates < eff_start_ts).sum()) if eff_start_ts is not None else total_days
        trailing_missing_days = int((sample_dates > eff_end_ts).sum()) if eff_end_ts is not None else total_days

        eff_days_by_year = (
            pd.Series(effective_dates).dt.year.value_counts().to_dict() if len(effective_dates) else {}
        )
        avail_days_by_year = (
            pd.Series(available_dates).dt.year.value_counts().to_dict() if len(available_dates) else {}
        )

        frame = pd.DataFrame({
            "date": sample["date"],
            "year": sample["date"].dt.year,
            "usable": usable.to_numpy(dtype=bool),
        })
        if has_industry is not None:
            frame["has_industry"] = has_industry.to_numpy(dtype=bool)
        if has_size is not None:
            frame["has_size"] = has_size.to_numpy(dtype=bool)

        yearly: list[dict] = []
        for year, group in frame.groupby("year", sort=True):
            yr = int(year)
            yr_total_days = int(group["date"].nunique())
            yr_eff_days = int(eff_days_by_year.get(yr, 0))
            yr_avail_days = int(avail_days_by_year.get(yr, 0))
            yearly.append({
                "year": yr,
                "samples": int(len(group)),
                "industry_coverage": float(group["has_industry"].mean()) if has_industry is not None else None,
                "size_coverage": float(group["has_size"].mean()) if has_size is not None else None,
                "joint_coverage": float(group["usable"].mean()),
                "total_days": yr_total_days,
                "effective_days": yr_eff_days,
                "skipped_days": max(0, yr_avail_days - yr_eff_days),
            })

        low_years = [
            row["year"] for row in yearly
            if row["effective_days"] == 0 or row["joint_coverage"] < LOW_YEAR_COVERAGE_THRESHOLD
        ]
        insufficient = bool(
            joint_cov < LOW_COVERAGE_THRESHOLD
            or leading_missing_days >= MISSING_EDGE_DAYS_THRESHOLD
            or trailing_missing_days >= MISSING_EDGE_DAYS_THRESHOLD
            or low_years
        )
        eff_start = eff_start_ts.date().isoformat() if eff_start_ts is not None else None
        eff_end = eff_end_ts.date().isoformat() if eff_end_ts is not None else None
        req_start = start_date.isoformat() if start_date is not None else (
            sample_dates[0].date().isoformat() if len(sample_dates) else None
        )
        req_end = end_date.isoformat() if end_date is not None else (
            sample_dates[-1].date().isoformat() if len(sample_dates) else None
        )

        warning = ""
        if insufficient:
            parts = [
                f"中性化覆盖不足：实际有效日期为 {eff_start} 至 {eff_end}"
                f"（有效 {effective_days} / {total_days} 个交易日，联合覆盖率 {joint_cov * 100:.1f}%）"
            ]
            if size_cov is not None and size_cov < LOW_COVERAGE_THRESHOLD and (
                industry_cov is None or size_cov + 0.1 < industry_cov
            ):
                parts.append("主要缺少历史市值（总股本）数据")
            elif industry_cov is not None and industry_cov < LOW_COVERAGE_THRESHOLD and (
                size_cov is None or industry_cov + 0.1 < size_cov
            ):
                parts.append("主要缺少历史行业分类数据")
            parts.append("当前统计仅反映有数据阶段，请勿当作所选全区间结论。")
            warning = "；".join(parts[:-1]) + "。" + parts[-1]

        return {
            "mode": neutralization,
            "requested_start": req_start,
            "requested_end": req_end,
            "effective_start": eff_start,
            "effective_end": eff_end,
            "total_samples": total_samples,
            "usable_samples": usable_samples,
            "effective_samples": effective_samples,
            "total_days": total_days,
            "effective_days": effective_days,
            "skipped_days": skipped_days,
            "leading_missing_days": leading_missing_days,
            "trailing_missing_days": trailing_missing_days,
            "industry_coverage": industry_cov,
            "size_coverage": size_cov,
            "joint_coverage": joint_cov,
            "insufficient": insufficient,
            "warning": warning,
            "yearly": yearly,
        }

    def evaluate(
        self,
        factor: FactorDefinition,
        start_date: date,
        end_date: date,
        *,
        symbols: list[str] | None = None,
        horizon: int = 5,
        n_groups: int = 5,
        neutralization: str = "none",
        decay_horizons: tuple[int, ...] = (1, 5, 10, 20),
        diagnostics: bool = False,
        filters: FactorSampleFilters = FactorSampleFilters(),
        cost_bps: float = 0.0,
    ) -> FactorReport:
        """评估因子在 [start_date, end_date] 的横截面选股能力。"""

        if horizon < 1:
            raise ValueError("horizon 必须 >= 1")
        if n_groups < 2:
            raise ValueError("n_groups 必须 >= 2")
        if neutralization not in {"none", "industry", "size", "both", "industry_rank"}:
            raise ValueError("未知中性化方式")
        if not np.isfinite(cost_bps) or not 0.0 <= float(cost_bps) <= 100.0:
            raise ValueError("单边交易成本（bps）必须在 0 至 100 之间")
        cost_bps = float(cost_bps)

        # 因子值和未来收益均使用截止结束日期的行情。
        progress.report("加载行情")
        extra = extra_columns(factor.required_fields)
        factor_bars = self.repository.get_daily_bars(
            symbols=symbols, end_date=end_date, **({"extras": extra} if extra else {})
        )
        if factor_bars.empty:
            raise ValueError("评估区间内没有行情数据")
        notes: list[str] = []
        is_index = UNIVERSE_COLUMN in factor_bars.columns
        if filters.active():
            eligible, notes = filters.apply(factor_bars, start_date, end_date)
            factor_bars[UNIVERSE_COLUMN] = eligible
        progress.report("计算因子值")
        values = factor.compute(factor_bars)
        deadline.check()
        values["date"] = pd.to_datetime(values["date"]).dt.normalize()
        values = values[
            values["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
        ].copy()
        if UNIVERSE_COLUMN in factor_bars.columns:
            values, universe_note = only_members(values, factor_bars)
            if is_index:
                notes.append(universe_note)
        if filters.active() and values.empty:
            raise ValueError("所选日期和股票范围没有符合筛选条件的有效因子样本。")
        changes = (
            self.repository.read_table(EXPOSURES_TABLE)
            if diagnostics or neutralization in {"industry", "both", "industry_rank"} else None
        )
        neutralization_coverage = None
        if neutralization != "none":
            progress.report("按历史暴露处理因子")
            values, exposure_notes, neutralization_coverage = self._neutralize_with_coverage(
                values,
                factor_bars,
                neutralization,
                changes=changes,
                start_date=start_date,
                end_date=end_date,
            )
            notes.extend(exposure_notes)
        values["adjusted"] = pd.to_numeric(values["value"], errors="coerce") * factor.direction

        values["adjusted"] = values["adjusted"].replace([float("inf"), -float("inf")], float("nan"))
        # Assign membership before inspecting future returns, including unlabelled tail dates.
        progress.report("计算分组与 IC")
        values = self._assign_groups(values, n_groups)
        close = self._close_prices(factor_bars, filters.exclude_suspended).loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        dates = close.index
        entry = close.shift(-1)
        if filters.exclude_limit_moves:
            limit_tradable = self._limit_tradable_mask(factor_bars).reindex(
                index=dates, columns=close.columns, fill_value=False
            )
            entry_ok = limit_tradable.shift(-1, fill_value=False)
            blocked_entries = int((entry.notna() & ~entry_ok).sum().sum())
            entry = entry.where(entry_ok)
            if blocked_entries:
                notes.append(f"建仓日（t+1）触及涨跌停或缺少涨跌停价的 {blocked_entries} 个股票交易日未计入收益")
        returns = self._forward_returns(close, entry, horizon)
        merged = values.merge(returns, on=["date", "symbol"], how="left")

        daily_ic = self._daily_ic(merged.dropna(subset=["adjusted", "fwd_ret"]))
        group_returns, group_means, long_short = self._group_returns(merged, n_groups)
        turnover = self._top_turnover(values, n_groups, dates=dates)

        rank_ic = daily_ic["rank_ic"].dropna()
        half = len(rank_ic) // 2
        first_half = float(rank_ic.iloc[:half].mean()) if half else float("nan")
        second_half = float(rank_ic.iloc[half:].mean()) if len(rank_ic) > half else float("nan")

        if len(rank_ic) < 20:
            notes.append("有效截面不足 20 日，统计结论仅供参考")
        if values["group"].isna().any():
            notes.append(
                "部分截面因有效股票不足、因子缺失或重复分位边界无法完整分组；未强行拆分同值股票。"
            )
        if merged["fwd_ret"].isna().any():
            notes.append(
                "部分股票缺少完整未来收益，收益统计仅使用可观测样本；分组成员和换手不因此重算。"
            )

        ic = daily_ic["ic"].dropna()
        progress.report("计算不同持有期的因子衰减")
        decay_rows = []
        for period in sorted(set(decay_horizons)):
            deadline.check()
            if period < 1:
                raise ValueError("衰减持有期必须为正数")
            if period == horizon:
                decay_ic = rank_ic
            else:
                forward = self._forward_returns(close, entry, period)
                sample = values[["date", "symbol", "adjusted"]].merge(forward, on=["date", "symbol"])
                decay_ic = self._daily_ic(sample.dropna(subset=["adjusted"])).rank_ic
            decay_rows.append({"horizon": period, **ic_statistics(decay_ic, period)})

        annual = annual_ic(daily_ic, horizon)
        group_nav, rebalance_turnover = pd.DataFrame(), pd.DataFrame()
        nav_periods = nav_skipped = 0
        industry_distribution = None
        style_correlations: list[dict] = []
        cost_summary: dict | None = None
        if diagnostics:
            progress.report("生成分组净值和换手曲线")
            group_nav, nav_periods, nav_skipped, cost_summary = self._group_nav_with_cost(
                group_returns, dates, horizon, n_groups, values=values, cost_bps=cost_bps
            )
            industry_distribution = self._industry_distribution(values, dates, horizon, n_groups, changes)
            style_correlations = self._style_correlations(
                values,
                factor_bars,
                factor_name=factor.name,
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
            signals = dates[::horizon]
            rebalance_turnover = self._top_turnover(
                values[values["date"].isin(signals)], n_groups, dates=signals,
            ).set_index("date").reindex(signals).rename_axis("date").reset_index()
            daily_ic = daily_ic.set_index("date").reindex(dates).rename_axis("date").reset_index()
            for metric in ("ic", "rank_ic"):
                series = daily_ic[metric]
                rolling = series.rolling(ROLLING_IC_WINDOW, min_periods=ROLLING_IC_MIN_OBSERVATIONS)
                std = rolling.std()
                daily_ic[f"{metric}_ir"] = rolling.mean() / std.where(std.gt(1e-12) & series.notna())
        deadline.check()
        return FactorReport(
            significance=ic_statistics(rank_ic, horizon),
            annual=annual,
            decay=pd.DataFrame(decay_rows),
            group_nav=group_nav,
            rebalance_turnover=rebalance_turnover,
            nav_periods=nav_periods,
            nav_skipped=nav_skipped,
            industry_distribution=industry_distribution,
            neutralization_coverage=neutralization_coverage,
            style_correlations=style_correlations,
            cost_summary=cost_summary,
            factor_name=factor.name,
            display_name=factor.display_name,
            horizon=horizon,
            n_groups=n_groups,
            daily_ic=daily_ic,
            ic_mean=float(ic.mean()) if len(ic) else float("nan"),
            ic_ir=self._ir(ic),
            rank_ic_mean=float(rank_ic.mean()) if len(rank_ic) else float("nan"),
            rank_ic_ir=self._ir(rank_ic),
            group_returns=group_returns,
            group_mean_returns=group_means,
            long_short_mean=long_short,
            turnover=turnover,
            turnover_mean=(
                float(turnover["turnover"].mean()) if not turnover.empty else float("nan")
            ),
            first_half_ic=first_half,
            second_half_ic=second_half,
            notes=notes,
        )

    @staticmethod
    def _close_prices(bars: pd.DataFrame, exclude_suspended: bool = False) -> pd.DataFrame:
        price_field = (
            "adjusted_close"
            if "adjusted_close" in bars.columns and bars["adjusted_close"].notna().any()
            else "raw_close"
        )
        prices = bars[["trade_date", "symbol", price_field]]
        if exclude_suspended:
            tradable = bars.get("is_suspended", pd.Series(pd.NA, index=bars.index)).eq(False)
            prices = prices.assign(**{price_field: prices[price_field].where(tradable)})
        close = pivot_field(prices, price_field)
        # Preserve every observed market date, even when all prices on it are missing.
        calendar = pd.DatetimeIndex(
            pd.to_datetime(bars["trade_date"]).dt.normalize().unique()
        ).sort_values()
        close = close.reindex(calendar)
        return close.where((close > 0) & (close < float("inf")))

    @staticmethod
    def _limit_tradable_mask(bars: pd.DataFrame) -> pd.DataFrame:
        """Boolean wide mask: True when raw_close is strictly inside (down_limit, up_limit)."""

        frame = bars[["trade_date", "symbol"]].copy()
        close = pd.to_numeric(bars.get("raw_close", pd.Series(pd.NA, index=bars.index)), errors="coerce")
        up = pd.to_numeric(bars.get("up_limit", pd.Series(pd.NA, index=bars.index)), errors="coerce")
        down = pd.to_numeric(bars.get("down_limit", pd.Series(pd.NA, index=bars.index)), errors="coerce")
        known = close.gt(0) & up.gt(0) & down.gt(0)
        tradable = known & (close < up - 1e-6) & (close > down + 1e-6)
        frame["tradable"] = tradable.astype(float)
        wide = pivot_field(frame, "tradable")
        return wide.eq(1.0)

    @staticmethod
    def _forward_returns(close: pd.DataFrame, entry: pd.DataFrame, horizon: int) -> pd.DataFrame:
        """t+1 收盘买入、t+horizon+1 收盘卖出；不填补缺失价格。"""
        fwd = close.shift(-(horizon + 1)) / entry - 1.0
        long = fwd.stack(future_stack=True).rename("fwd_ret").reset_index()
        long.columns = pd.Index(["date", "symbol", "fwd_ret"])
        return long.dropna(subset=["fwd_ret"])

    @staticmethod
    def _group_nav(
        group_returns: pd.DataFrame, dates: pd.DatetimeIndex, horizon: int, n_groups: int
    ) -> tuple[pd.DataFrame, int, int]:
        """按不重叠持有期复利，收益记在平仓日，缺失分组的调仓期留空。"""
        nav, valid, skipped, _ = FactorEvaluator._group_nav_with_cost(
            group_returns, dates, horizon, n_groups
        )
        return nav, valid, skipped

    @staticmethod
    def _group_nav_with_cost(
        group_returns: pd.DataFrame,
        dates: pd.DatetimeIndex,
        horizon: int,
        n_groups: int,
        *,
        values: pd.DataFrame | None = None,
        cost_bps: float = 0.0,
    ) -> tuple[pd.DataFrame, int, int, dict | None]:
        """按不重叠持有期复利，收益记在平仓日，缺失分组的调仓期留空；可选按换手扣减单边 cost_bps。"""
        positions = range(0, len(dates) - horizon - 1, horizon)
        groups = list(range(1, n_groups + 1))
        returns = group_returns.pivot(index="date", columns="group", values="ret").reindex(
            index=dates[list(positions)], columns=groups,
        )
        covered = returns.dropna()
        skipped = len(returns) - len(covered)
        if covered.empty:
            return pd.DataFrame(), 0, skipped, None
        nav = (1 + covered).cumprod().rename(columns={group: f"G{group}" for group in groups})
        # 固定名义本金的头尾组收益差，逐期相加。
        nav["long_short"] = (covered[n_groups] - covered[1]).cumsum()
        cost_summary: dict | None = None
        if cost_bps > 0 and values is not None and not values.empty:
            rate = float(cost_bps) / 10_000.0
            member_sets: dict[tuple[pd.Timestamp, int], set[str]] = {}
            sub = values[values["date"].isin(covered.index) & values["group"].notna()]
            for (sig_date, grp), grp_df in sub.groupby(["date", "group"], observed=True):
                member_sets[(pd.Timestamp(sig_date), int(grp))] = set(grp_df["symbol"].astype(str))
            prev_sets: dict[int, set[str]] = {}
            net_covered = covered.copy()
            top_turnovers: list[float] = []
            for sig_date in covered.index:
                ts = pd.Timestamp(sig_date)
                for grp in groups:
                    curr = member_sets.get((ts, grp), set())
                    prev = prev_sets.get(grp)
                    if not prev:
                        turnover = 1.0
                        period_cost = rate  # 首次建仓计单边买入成本
                    else:
                        overlap = len(prev & curr) / len(curr) if curr else 0.0
                        turnover = 1.0 - overlap
                        period_cost = 2.0 * turnover * rate  # 换仓同时产生卖出与买入双边成本
                    if grp == n_groups:
                        top_turnovers.append(turnover)
                    net_covered.loc[sig_date, grp] = float(covered.loc[sig_date, grp]) - period_cost
                    if curr:
                        prev_sets[grp] = curr
            net_top_nav = (1 + net_covered[n_groups]).cumprod()
            net_ls_series = net_covered[n_groups] - net_covered[1]
            nav[f"net_G{n_groups}"] = net_top_nav
            nav["net_long_short"] = net_ls_series.cumsum()
            cost_summary = {
                "cost_bps": float(cost_bps),
                "gross_top_return": float(nav[f"G{n_groups}"].iloc[-1] - 1.0),
                "net_top_return": float(net_top_nav.iloc[-1] - 1.0),
                "gross_long_short_total": float(nav["long_short"].iloc[-1]),
                "net_long_short_total": float(nav["net_long_short"].iloc[-1]),
                "net_long_short_mean": float(net_ls_series.mean()),
                "avg_top_turnover": float(np.mean(top_turnovers)) if top_turnovers else 0.0,
            }
        nav = nav.reindex(returns.index)
        nav.index = dates[[position + horizon + 1 for position in positions]]
        init_row: list[float] = [1.0] * n_groups + [0.0]
        if cost_summary is not None:
            init_row.extend([1.0, 0.0])
        nav.loc[dates[1]] = init_row
        return nav.sort_index().rename_axis("date").reset_index(), len(covered), skipped, cost_summary

    @staticmethod
    def _industry_distribution(
        values: pd.DataFrame, dates: pd.DatetimeIndex, horizon: int, n_groups: int, changes: pd.DataFrame,
    ) -> dict | None:
        """Snapshot the last formed top group with a full holding window, before using prices."""

        signals = dates[:max(0, len(dates) - horizon - 1):horizon]
        latest = values.loc[values["group"].eq(n_groups) & values["date"].isin(signals), "date"].max()
        if pd.isna(latest):
            return None
        sample = values.loc[values["date"].eq(latest) & values["group"].notna(), ["date", "symbol", "group"]].copy()
        sample["industry"] = industry_on(sample, changes, infer_early=False).fillna("未分类")
        sample["top"] = sample["group"].eq(n_groups)
        counts = sample.groupby("industry").agg(pool_count=("symbol", "size"), group_count=("top", "sum"))
        group_count = int(sample["top"].sum())
        counts["group_weight"] = counts["group_count"] / group_count
        counts["pool_weight"] = counts["pool_count"] / len(sample)
        rows = counts.sort_values(["group_count", "pool_count", "industry"], ascending=[False, False, True])
        return {
            "date": latest.date().isoformat(), "group_count": group_count, "pool_count": len(sample),
            "rows": rows.reset_index().to_dict(orient="records"),
        }

    def _style_correlations(
        self,
        values: pd.DataFrame,
        factor_bars: pd.DataFrame,
        *,
        factor_name: str,
        start_date: date,
        end_date: date,
        symbols: list[str] | None,
    ) -> list[dict]:
        """Compute cross-sectional Spearman correlations against standard A-share style factors."""

        valid_values = values[["date", "symbol", "adjusted"]].dropna(subset=["adjusted"])
        if valid_values.empty:
            return []
        target_wide = (
            valid_values.assign(date=pd.to_datetime(valid_values["date"]).dt.normalize())
            .pivot_table(index="date", columns="symbol", values="adjusted", aggfunc="last")
            .sort_index()
        )
        target_wide = target_wide.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        if target_wide.empty:
            return []

        bars = factor_bars
        style_extras = ("turnover_rate", "pe_ttm", "pb_mrq")
        if any(col not in bars.columns for col in style_extras):
            extra_cols = extra_columns(style_extras)
            if extra_cols:
                try:
                    enriched = self.repository.get_daily_bars(
                        symbols=symbols, end_date=end_date, extras=extra_cols
                    )
                    if not enriched.empty:
                        bars = enriched
                except Exception:  # noqa: BLE001 - optional extra data should never fail evaluation
                    pass

        price_col = (
            "adjusted_close"
            if "adjusted_close" in bars.columns and bars["adjusted_close"].notna().any()
            else "raw_close"
        )
        close_wide = pivot_field(bars, price_col).sort_index()

        style_specs: list[tuple[str, str, str, str, pd.DataFrame | None]] = []

        # 1. 规模：对数总市值
        if factor_name != "ln_market_cap" and "raw_close" in bars.columns and hasattr(self.repository, "get_fundamentals"):
            try:
                fundamentals = self.repository.get_fundamentals()
                if not fundamentals.empty:
                    days = bars[["symbol", "trade_date", "raw_close"]].copy()
                    days["trade_date"] = pd.to_datetime(days["trade_date"]).astype("datetime64[ns]")
                    days = days[days["trade_date"].isin(target_wide.index)]
                    if not days.empty:
                        shares = point_in_time(days, fundamentals, ["total_shares"])["total_shares"]
                        cap = market_capitalization(days["raw_close"], shares)
                        days["ln_cap"] = np.log(cap.where(cap.gt(0)))
                        cap_wide = (
                            days.dropna(subset=["ln_cap"])
                            .pivot_table(index="trade_date", columns="symbol", values="ln_cap", aggfunc="last")
                        )
                        style_specs.append(("ln_market_cap", "规模（对数总市值）", "偏大盘", "偏小盘", cap_wide))
            except Exception:  # noqa: BLE001 - missing fundamentals is acceptable
                pass

        # 2. 波动率：20日历史波动率
        if factor_name != "volatility_20" and not close_wide.empty:
            vol_wide = close_wide.pct_change(fill_method=None).rolling(20, min_periods=20).std()
            style_specs.append(("volatility_20", "波动率（20日历史波动率）", "偏高波", "偏低波", vol_wide))

        # 3. 动量：20日涨跌幅
        if factor_name != "momentum_20" and not close_wide.empty:
            mom_wide = close_wide / close_wide.shift(20) - 1.0
            style_specs.append(("momentum_20", "动量（20日涨跌幅）", "偏强势动量", "偏超跌反转", mom_wide))

        # 4. 流动性：20日平均换手率
        if factor_name != "turnover_20" and "turnover_rate" in bars.columns and bars["turnover_rate"].notna().any():
            turn_wide = pivot_field(bars, "turnover_rate").sort_index().rolling(20, min_periods=20).mean()
            style_specs.append(("turnover_20", "流动性（20日平均换手率）", "偏高换手", "偏低换手", turn_wide))

        # 5. 估值：盈利收益率 EP (1 / PE_TTM)
        if factor_name != "ep_ttm" and "pe_ttm" in bars.columns and bars["pe_ttm"].notna().any():
            pe_wide = pivot_field(bars, "pe_ttm").sort_index()
            ep_wide = 1.0 / pe_wide.where(pe_wide.gt(0))
            style_specs.append(("ep_ttm", "估值（盈利收益率 EP）", "偏低估值", "偏高估值", ep_wide))

        # 6. 估值：账面市值比 BP (1 / PB_MRQ)
        if factor_name != "bp_mrq" and "pb_mrq" in bars.columns and bars["pb_mrq"].notna().any():
            pb_wide = pivot_field(bars, "pb_mrq").sort_index()
            bp_wide = 1.0 / pb_wide.where(pb_wide.gt(0))
            style_specs.append(("bp_mrq", "估值（账面市值比 BP）", "偏低市净率", "偏高市净率", bp_wide))

        results: list[dict] = []
        for style_key, label, pos_tilt, neg_tilt, style_wide in style_specs:
            if style_wide is None or style_wide.empty:
                continue
            aligned_style = style_wide.reindex(index=target_wide.index, columns=target_wide.columns)
            aligned_style = aligned_style.replace([float("inf"), -float("inf")], float("nan"))
            mask = target_wide.notna() & aligned_style.notna()
            valid_rows = mask.sum(axis=1) >= 3
            if int(valid_rows.sum()) < 5:
                continue
            rx = target_wide.loc[valid_rows].where(mask.loc[valid_rows]).rank(axis=1)
            ry = aligned_style.loc[valid_rows].where(mask.loc[valid_rows]).rank(axis=1)
            dx = rx.sub(rx.mean(axis=1), axis=0)
            dy = ry.sub(ry.mean(axis=1), axis=0)
            denom = np.sqrt((dx * dx).sum(axis=1) * (dy * dy).sum(axis=1))
            daily_corr = (dx * dy).sum(axis=1).div(denom.where(denom > 1e-12)).dropna()
            if len(daily_corr) < 5:
                continue
            mean_corr = float(daily_corr.mean())
            if not np.isfinite(mean_corr):
                continue
            if mean_corr >= 0.2:
                tilt = pos_tilt
            elif mean_corr <= -0.2:
                tilt = neg_tilt
            else:
                tilt = "关联较弱"
            results.append(
                {
                    "style": style_key,
                    "label": label,
                    "correlation": round(mean_corr, 4),
                    "observations": int(len(daily_corr)),
                    "tilt": tilt,
                    "high_overlap": abs(mean_corr) >= 0.4,
                }
            )
        return sorted(results, key=lambda item: -abs(item["correlation"]))

    @staticmethod
    def _daily_ic(merged: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for trade_date, group in merged.groupby("date", observed=True):
            if len(group) < 3:
                continue
            if group["adjusted"].nunique() < 2 or group["fwd_ret"].nunique() < 2:
                rows.append({"date": trade_date, "ic": float("nan"), "rank_ic": float("nan")})
                continue
            ic = group["adjusted"].corr(group["fwd_ret"], method="pearson")
            rank_ic = group["adjusted"].corr(group["fwd_ret"], method="spearman")
            rows.append({"date": trade_date, "ic": ic, "rank_ic": rank_ic})
        return pd.DataFrame(rows, columns=["date", "ic", "rank_ic"])

    @staticmethod
    def _assign_groups(values: pd.DataFrame, n_groups: int) -> pd.DataFrame:
        """Require all quantile groups; ties never get arbitrary symbol-based ranks."""
        values = values.copy()
        values["group"] = float("nan")
        for _, group in values.groupby("date", observed=True):
            valid = group["adjusted"].dropna()
            if len(valid) < n_groups:
                continue
            try:
                labels = pd.qcut(valid, n_groups, labels=False, duplicates="raise")
            except ValueError:
                continue
            if labels.nunique() != n_groups:
                continue
            values.loc[labels.index, "group"] = labels + 1
        return values

    @staticmethod
    def _group_returns(
        merged: pd.DataFrame, n_groups: int
    ) -> tuple[pd.DataFrame, pd.Series, float]:
        if "group" not in merged:
            merged = FactorEvaluator._assign_groups(merged, n_groups)
        frame = (
            merged.dropna(subset=["group", "fwd_ret"])
            .groupby(["date", "group"], observed=True)["fwd_ret"]
            .mean()
            .rename("ret")
            .reset_index()
        )
        if frame.empty:
            return frame, pd.Series(dtype=float), float("nan")
        means = frame.groupby("group", observed=True)["ret"].mean()
        paired = (
            frame.pivot(index="date", columns="group", values="ret")
            .reindex(columns=[1, n_groups])
            .dropna()
        )
        long_short = float((paired[n_groups] - paired[1]).mean())
        return frame, means, long_short

    @staticmethod
    def _top_turnover(
        merged: pd.DataFrame, n_groups: int, *, dates: pd.DatetimeIndex | None = None
    ) -> pd.DataFrame:
        """相邻有效截面新增成员 / 当日 Top 组人数；无效截面中断比较。"""

        if "group" not in merged:
            merged = FactorEvaluator._assign_groups(merged, n_groups)
        top_sets: list[tuple[pd.Timestamp, set[str]]] = []
        for trade_date, group in merged.groupby("date", observed=True):
            top_sets.append((trade_date, set(group.loc[group["group"] == n_groups, "symbol"])))
        if dates is not None:
            by_date = dict(top_sets)
            top_sets = [(day, by_date.get(day, set())) for day in dates]
        rows: list[dict[str, object]] = []
        for (_, prev), (trade_date, current) in zip(top_sets, top_sets[1:], strict=False):
            if not prev or not current:
                continue
            overlap = len(prev & current) / len(current) if current else 0.0
            rows.append({"date": trade_date, "turnover": 1.0 - overlap})
        return pd.DataFrame(rows, columns=["date", "turnover"])

    @staticmethod
    def _ir(series: pd.Series) -> float:
        std = float(series.std())
        if not len(series) or std == 0.0 or pd.isna(std):
            return float("nan")
        return float(series.mean()) / std
