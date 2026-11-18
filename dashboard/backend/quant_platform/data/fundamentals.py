"""Quarterly financial reports, stored in ``quarterly_fundamentals`` and used point in time.

One row per stock and reporting period (``stat_date``, the quarter end) with the day the report
was published (``pub_date``). A value may only be used from its publication day on: joining to
daily bars always goes through :func:`point_in_time`, never through ``stat_date``.

Flow figures are cumulative within the fiscal year, as reported (the half-year report covers
six months). Ratios and year-on-year changes are comparable across periods; levels are not.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from math import isfinite

import pandas as pd

from quant_platform.data.normalizers import canonical_symbol

FUNDAMENTALS_TABLE = "quarterly_fundamentals"
# BaoStock endpoint -> {vendor field: stored column}.
BAOSTOCK_FUNDAMENTAL_FIELDS: dict[str, dict[str, str]] = {
    "profit": {
        "roeAvg": "roe_avg",                 # 净资产收益率（平均），年初至报告期
        "npMargin": "net_margin",            # 销售净利率
        "gpMargin": "gross_margin",          # 销售毛利率（银行等没有）
        "netProfit": "net_profit",           # 净利润（元），年初至报告期
        "epsTTM": "eps_ttm",                 # 每股收益（TTM）
        "MBRevenue": "revenue",              # 主营营业收入（元），部分公司只在半年报和年报披露
        "totalShare": "total_shares",        # 总股本（股）
        "liqaShare": "float_shares",         # 流通股本（股）
    },
    "growth": {
        "YOYEquity": "yoy_equity",           # 净资产同比增长
        "YOYAsset": "yoy_asset",             # 总资产同比增长
        "YOYNI": "yoy_net_profit",           # 净利润同比增长
        "YOYEPSBasic": "yoy_eps",            # 基本每股收益同比增长
        "YOYPNI": "yoy_parent_net_profit",   # 归属母公司股东净利润同比增长
    },
    "balance": {
        "currentRatio": "current_ratio",     # 流动比率
        "quickRatio": "quick_ratio",         # 速动比率
        "assetToEquity": "asset_to_equity",  # 权益乘数（总资产 / 净资产）
        "liabilityToAsset": "liability_to_asset",
    },
}
FUNDAMENTAL_COLUMNS = [
    *(column for fields in BAOSTOCK_FUNDAMENTAL_FIELDS.values() for column in fields.values()),
    "operating_cash_flow",
]
MARKET_CAP_FIELDS = {"total_market_cap": "total_shares", "float_market_cap": "float_shares"}
DERIVED_COLUMNS = ["yoy_revenue", *MARKET_CAP_FIELDS]
FUNDAMENTAL_LABELS = {
    "roe_avg": "净资产收益率", "net_margin": "销售净利率", "gross_margin": "销售毛利率", "net_profit": "净利润",
    "eps_ttm": "每股收益（TTM）", "revenue": "主营营业收入", "total_shares": "总股本", "float_shares": "流通股本",
    "yoy_equity": "净资产同比增长", "yoy_asset": "总资产同比增长", "yoy_net_profit": "净利润同比增长",
    "yoy_eps": "每股收益同比增长", "yoy_parent_net_profit": "归母净利润同比增长",
    "current_ratio": "流动比率", "quick_ratio": "速动比率", "asset_to_equity": "权益乘数",
    "liability_to_asset": "资产负债率", "operating_cash_flow": "经营活动现金净流量（推算）",
}
STORED_COLUMNS = [
    "symbol", "stat_date", "pub_date", *FUNDAMENTAL_COLUMNS, "cash_flow_pub_date", "cash_flow_checked",
    "source", "ingested_at",
]
# 厂商偶尔把一份报告的这些比率按百分数给出（见 normalize_baostock_quarter）。
PERCENT_SCALE_SUSPECTS = ["roe_avg", "gross_margin", "yoy_equity", "yoy_asset", "yoy_net_profit", "yoy_eps", "yoy_parent_net_profit"]
# 一份财报最多用这么多天：公司不再披露（长期停牌、退市）时，不拿一年多以前的数字当现在的。
MAX_REPORT_AGE_DAYS = 370
MISSING_FUNDAMENTALS_MESSAGE = "平台还没有财务数据，管理员更新后就能用。"
MISSING_OPERATING_CASH_FLOW_MESSAGE = "所选股票暂无经营活动现金净流量数据，请在管理后台补充对应区间的财务数据。"


def quarter_end(year: int, quarter: int) -> date:
    return date(year, quarter * 3, 31 if quarter in (1, 4) else 30)


def quarters_between(first: date, last: date) -> list[tuple[int, int]]:
    """Every (year, quarter) whose quarter end falls in ``[first, last]``."""

    result = []
    for year in range(first.year, last.year + 1):
        for quarter in (1, 2, 3, 4):
            if first <= quarter_end(year, quarter) <= last:
                result.append((year, quarter))
    return result


def fundamental_columns(fields: Iterable[str]) -> list[str]:
    """The quarterly-report columns among the fields a factor or strategy asks for."""

    wanted = set(fields)
    return [column for column in [*FUNDAMENTAL_COLUMNS, *DERIVED_COLUMNS] if column in wanted]


def market_capitalization(close: pd.Series, shares: pd.Series) -> pd.Series:
    """Use unadjusted prices and positive, already reported shares (yuan)."""

    price = pd.to_numeric(close, errors="coerce")
    shares = pd.to_numeric(shares, errors="coerce")
    return price.where(price.gt(0) & price.lt(float("inf"))) * shares.where(shares.gt(0) & shares.lt(float("inf")))


def cash_flow_fields(frame: pd.DataFrame, net_profit: float | None) -> dict:
    """BaoStock supplies operating cash flow / net profit for the same reporting period."""

    fields = {"operating_cash_flow": float("nan"), "cash_flow_pub_date": pd.NaT, "cash_flow_checked": False}
    if frame.empty:
        return fields
    record = frame.iloc[0]
    published = pd.to_datetime(record.get("pubDate"), errors="coerce")
    if pd.isna(published):
        return fields
    fields["cash_flow_checked"] = True
    ratio = pd.to_numeric(record.get("CFOToNP"), errors="coerce")
    net_profit = pd.to_numeric(net_profit, errors="coerce")
    if pd.notna(ratio) and pd.notna(net_profit) and net_profit != 0:
        amount = float(ratio) * float(net_profit)
        if isfinite(amount):
            fields.update(operating_cash_flow=amount, cash_flow_pub_date=published.normalize())
    return fields


def normalize_baostock_quarter(symbol: str, year: int, quarter: int, responses: dict[str, pd.DataFrame]) -> dict | None:
    """One stored row from the endpoint responses for one stock and quarter; ``None`` if none answered.

    Core figures use the latest publication date of their sections. Cash flow has a separate
    publication date, so refreshing the supplementary section cannot delay existing factors.
    """

    row: dict = {column: float("nan") for column in FUNDAMENTAL_COLUMNS}
    published: list[pd.Timestamp] = []
    for endpoint, fields in BAOSTOCK_FUNDAMENTAL_FIELDS.items():
        frame = responses.get(endpoint)
        if frame is None or frame.empty:
            continue
        record = frame.iloc[0]
        day = pd.to_datetime(record.get("pubDate"), errors="coerce")
        if pd.isna(day):
            continue
        published.append(day)
        for vendor, column in fields.items():
            if vendor in frame.columns:
                row[column] = pd.to_numeric(pd.Series([record[vendor]]), errors="coerce").iloc[0]
    if not published:
        return None
    if row["gross_margin"] > 1:
        # 毛利率不可能超过 100%：这份报告的比率是按百分数给的（个别上市前的报告如此），
        # 而且同一份里各项的口径并不一致，所以不去猜怎么换算，受影响的几项都按缺失处理。
        for column in PERCENT_SCALE_SUSPECTS:
            row[column] = float("nan")
    if "cash_flow" in responses:
        row.update(cash_flow_fields(responses["cash_flow"], row["net_profit"]))
    return {"symbol": canonical_symbol(symbol), "stat_date": pd.Timestamp(quarter_end(year, quarter)),
            "pub_date": max(published).normalize(), **row, "source": "baostock", "ingested_at": datetime.now(UTC)}


def checked_empty_row(symbol: str, year: int, quarter: int) -> dict:
    """A marker for "asked, the vendor has no report for this period": keeps old gaps from being asked again."""

    return {"symbol": canonical_symbol(symbol), "stat_date": pd.Timestamp(quarter_end(year, quarter)), "pub_date": pd.NaT,
            **{column: float("nan") for column in FUNDAMENTAL_COLUMNS}, "source": "baostock", "ingested_at": datetime.now(UTC)}


def _revenue_growth_reports(published: pd.DataFrame) -> pd.DataFrame:
    prior = published[["symbol", "stat_date", "pub_date", "revenue"]].rename(
        columns={"pub_date": "_prior_pub_date", "revenue": "_prior_revenue"}
    )
    prior["stat_date"] += pd.DateOffset(years=1)
    paired = published.merge(prior, on=["symbol", "stat_date"], how="inner", validate="one_to_one")
    current = pd.to_numeric(paired["revenue"], errors="coerce")
    base = pd.to_numeric(paired["_prior_revenue"], errors="coerce")
    valid = current.ge(0) & current.lt(float("inf")) & base.gt(0) & base.lt(float("inf"))
    usable = paired.loc[valid, ["symbol", "stat_date", "pub_date", "_prior_pub_date"]].copy()
    usable["yoy_revenue"] = current[valid] / base[valid] - 1
    usable["pub_date"] = usable[["pub_date", "_prior_pub_date"]].max(axis=1)
    return usable


def _latest_report_fields(
    order: pd.DataFrame, published: pd.DataFrame, columns: list[str], max_age_days: int,
) -> pd.DataFrame:
    # A late release of an older quarter must not replace a newer period.
    published = published.sort_values(["symbol", "pub_date", "stat_date"])
    newest = published.groupby("symbol")["stat_date"].cummax()
    published = published[published["stat_date"] >= newest].sort_values(["pub_date", "stat_date"])
    joined = pd.merge_asof(
        order, published.reindex(columns=["symbol", "pub_date", *columns]),
        left_on="trade_date", right_on="pub_date", by="symbol", direction="backward",
    )
    stale = (joined["trade_date"] - joined["pub_date"]).dt.days > max_age_days
    joined.loc[stale, columns] = float("nan")
    return joined.sort_values("_row")[columns]


def point_in_time(days: pd.DataFrame, reports: pd.DataFrame, columns: list[str],
                  max_age_days: int = MAX_REPORT_AGE_DAYS) -> pd.DataFrame:
    """For each (symbol, trade_date) the values of the newest report already published that day.

    ``days`` has ``symbol`` and ``trade_date``; the result has the same rows, in the same order,
    with ``columns`` added. A report counts from its publication day. When an older period is
    published after a newer one (a late correction), the newer period stays in force. A report
    older than ``max_age_days`` gives missing values. Revenue growth uses the latest comparable pair
    of published reports. Operating cash flow uses the latest report with both inputs available.
    """

    result = days[["symbol", "trade_date"]].copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).astype("datetime64[ns]")
    if reports.empty:
        return result.assign(**{column: float("nan") for column in columns})
    published = reports.dropna(subset=["pub_date"]).copy()
    published["pub_date"] = pd.to_datetime(published["pub_date"]).astype("datetime64[ns]")
    published["stat_date"] = pd.to_datetime(published["stat_date"]).astype("datetime64[ns]")
    sources = {}
    if "yoy_revenue" in columns:
        sources["yoy_revenue"] = _revenue_growth_reports(published)
    if "liability_to_asset" in columns:
        reported = pd.to_numeric(published.reindex(columns=["liability_to_asset"])["liability_to_asset"], errors="coerce")
        leverage = pd.to_numeric(published["asset_to_equity"], errors="coerce")
        published["liability_to_asset"] = reported.where(reported.ge(0) & reported.lt(float("inf"))).fillna(
            1 - 1 / leverage.where(leverage.ge(1) & leverage.lt(float("inf")))
        )
    if "operating_cash_flow" in columns:
        cash_flow = published.reindex(columns=["symbol", "stat_date", "pub_date", "cash_flow_pub_date", "operating_cash_flow"])
        cash_flow["cash_flow_pub_date"] = pd.to_datetime(
            cash_flow["cash_flow_pub_date"], errors="coerce",
        ).astype("datetime64[ns]")
        cash_flow = cash_flow.dropna(subset=["cash_flow_pub_date", "operating_cash_flow"])
        cash_flow["pub_date"] = cash_flow[["pub_date", "cash_flow_pub_date"]].max(axis=1)
        sources["operating_cash_flow"] = cash_flow
    order = result.assign(_row=range(len(result))).sort_values("trade_date")
    common = [column for column in columns if column not in sources]
    matched = _latest_report_fields(order, published, common, max_age_days) if common else pd.DataFrame(index=order.index)
    for column, source in sources.items():
        matched[column] = _latest_report_fields(order, source, [column], max_age_days)[column].to_numpy()
    result[columns] = matched[columns].to_numpy()
    return result
