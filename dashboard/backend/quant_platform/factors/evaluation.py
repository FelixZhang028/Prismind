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

        sample = values[["date", "symbol", "value"]].copy().reset_index(drop=True)
        sample["value"] = pd.to_numeric(sample["value"], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
        sample["date"] = pd.to_datetime(sample["date"]).astype("datetime64[ns]")
        exposures = sample[["date", "symbol"]].copy()
        usable = pd.Series(True, index=sample.index)
        if neutralization in {"industry", "both", "industry_rank"}:
            if changes is None:
                changes = self.repository.read_table(EXPOSURES_TABLE)
            if changes.empty or "industry" not in changes.columns:
                raise ValueError(MISSING_INDUSTRY_MESSAGE)
            exposures["industry"] = industry_on(exposures, changes, infer_early=False).to_numpy()
            usable &= exposures["industry"].notna()
        if neutralization in {"size", "both"}:
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
            usable &= (exposures["market_cap"] > 0).to_numpy()
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
        return result, notes

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
    ) -> FactorReport:
        """评估因子在 [start_date, end_date] 的横截面选股能力。"""

        if horizon < 1:
            raise ValueError("horizon 必须 >= 1")
        if n_groups < 2:
            raise ValueError("n_groups 必须 >= 2")
        if neutralization not in {"none", "industry", "size", "both", "industry_rank"}:
            raise ValueError("未知中性化方式")

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
        if neutralization != "none":
            progress.report("按历史暴露处理因子")
            values, exposure_notes = self._neutralized(values, factor_bars, neutralization, changes=changes)
            notes.extend(exposure_notes)
        values["adjusted"] = pd.to_numeric(values["value"], errors="coerce") * factor.direction

        values["adjusted"] = values["adjusted"].replace([float("inf"), -float("inf")], float("nan"))
        # Assign membership before inspecting future returns, including unlabelled tail dates.
        progress.report("计算分组与 IC")
        values = self._assign_groups(values, n_groups)
        close = self._close_prices(factor_bars, filters.exclude_suspended).loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        dates = close.index
        entry = close.shift(-1)
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
        if diagnostics:
            progress.report("生成分组净值和换手曲线")
            group_nav, nav_periods, nav_skipped = self._group_nav(group_returns, dates, horizon, n_groups)
            industry_distribution = self._industry_distribution(values, dates, horizon, n_groups, changes)
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
        positions = range(0, len(dates) - horizon - 1, horizon)
        groups = list(range(1, n_groups + 1))
        returns = group_returns.pivot(index="date", columns="group", values="ret").reindex(
            index=dates[list(positions)], columns=groups,
        )
        covered = returns.dropna()
        skipped = len(returns) - len(covered)
        if covered.empty:
            return pd.DataFrame(), 0, skipped
        nav = (1 + covered).cumprod().rename(columns={group: f"G{group}" for group in groups})
        # 固定名义本金的头尾组收益差，逐期相加。
        nav["long_short"] = (covered[n_groups] - covered[1]).cumsum()
        nav = nav.reindex(returns.index)
        nav.index = dates[[position + horizon + 1 for position in positions]]
        nav.loc[dates[1]] = [1.0] * n_groups + [0.0]
        return nav.sort_index().rename_axis("date").reset_index(), len(covered), skipped

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
