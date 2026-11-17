"""今天符合条件的股票：和回测同一套判断，按排序列出，排除 ST、停牌和当天没有行情的股票。"""

from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from quant_platform.data.fundamentals import FUNDAMENTALS_TABLE
from quant_platform.data.indicators import INDICATOR_TABLE
from quant_platform.data.repositories.parquet_repository import ParquetMarketDataRepository
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_based import RuleBasedStrategy, rank_score
from quant_platform.strategies.rule_schema import RuleStrategyDefinition
from quant_platform.strategies.screen import screen
from quant_platform.universe.a_share import AShareUniverse, AShareUniverseConfig

DAY = date(2026, 10, 21)


def definition(**ranking):
    return RuleStrategyDefinition.from_mapping({
        "strategy_id": "t", "name": "t", "entry_logic": "all",
        "entry_rules": [{"left": {"name": "close"}, "operator": "greater_than", "right": {"name": "moving_average", "window": 5}}],
        "ranking": {"indicator": {"name": "return", "window": 3}, **(ranking or {"direction": "descending"})},
    })


def history(symbol, closes, *, last=DAY, st=False, suspended=False):
    days = [last - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))]
    rows = []
    for i, (day, close) in enumerate(zip(days, closes)):
        rows.append({"symbol": symbol, "trade_date": pd.Timestamp(day), "adjusted_close": close, "raw_close": close,
                     "pre_close": closes[i - 1] if i else close, "amount": 1e8,
                     "is_st": st and day == last, "is_suspended": suspended and day == last})
    return rows


def bars():
    rising = [10, 10, 10, 10, 10, 11, 12, 13]            # 在 5 日均线上方，近 3 日涨得最多
    slow = [10, 10, 10, 10, 10, 10, 10.2, 10.4]          # 在均线上方，涨得少
    falling = [13, 13, 13, 13, 13, 12, 11, 10]           # 在均线下方：不符合
    return pd.DataFrame(history("600001.SH", rising) + history("600002.SH", slow) + history("600003.SH", falling)
                        + history("600004.SH", rising, st=True)                  # ST：默认排除
                        + history("600005.SH", rising, suspended=True)           # 停牌：排除
                        + history("600006.SH", rising, last=DAY - timedelta(days=1)))   # 当天没有行情


def test_lists_the_passing_stocks_best_first_with_their_values():
    result = screen(definition(), bars(), DAY)
    assert result["checked"] == 3 and result["matched"] == 2
    first, second = result["items"]
    assert [first["symbol"], second["symbol"]] == ["600001.SH", "600002.SH"]
    assert first["close"] == 13 and first["change"] == pytest.approx(13 / 12 - 1)
    assert first["ranking"] == pytest.approx(13 / 10 - 1)
    assert first["conditions"] == [{"left": 13, "right": pytest.approx((10 + 11 + 12 + 13 + 10) / 5)}]


def test_ascending_ranking_puts_the_smallest_first_and_st_can_be_kept():
    result = screen(definition(direction="ascending"), bars(), DAY, exclude_st=False)
    assert [item["symbol"] for item in result["items"]][:1] == ["600002.SH"]
    assert "600004.SH" in {item["symbol"] for item in result["items"]} and result["checked"] == 4


def test_the_screen_agrees_with_the_backtest_rule_check():
    frame = bars()
    rule = definition()
    listed = {item["symbol"] for item in screen(rule, frame, DAY)["items"]}
    for symbol in ("600001.SH", "600002.SH", "600003.SH"):
        group = frame[frame["symbol"] == symbol].sort_values("trade_date")
        assert (rank_score(group, rule) is not None) == (symbol in listed)


def test_nothing_to_screen():
    assert screen(definition(), pd.DataFrame(), DAY) == {"checked": 0, "matched": 0, "items": []}


def test_historical_st_filter_reads_the_state_on_each_day():
    first = DAY - timedelta(days=1)
    symbol = "600001.SH"
    frame = pd.DataFrame(history(symbol, [10, 11], st=True)).assign(quality_status="OK", is_listed=True)
    universe = AShareUniverse(AShareUniverseConfig((symbol,), minimum_history_days=1))
    universe.prepare(frame)
    assert universe.select(first, frame) == [symbol]
    assert universe.select(DAY, frame) == []

    unknown = bars()
    unknown["is_st"] = unknown["is_st"].astype("boolean").mask(unknown["symbol"].eq(symbol))
    assert symbol not in {item["symbol"] for item in screen(definition(), unknown, DAY)["items"]}
    assert symbol in {item["symbol"] for item in screen(definition(), unknown, DAY, exclude_st=False)["items"]}


def test_fundamental_rules_share_point_in_time_data_between_screen_and_strategy(tmp_path, monkeypatch):
    from app.routes import workspace

    repo = ParquetMarketDataRepository(tmp_path)
    days = pd.date_range(DAY - timedelta(days=2), DAY)
    one, two, missing = "600001.SH", "600002.SH", "600003.SH"
    for symbol in (one, two, missing):
        repo.save_table("daily_bars", pd.DataFrame(history(symbol, [10, 10, 10])).assign(adjusted_close=20))
        repo.save_table(INDICATOR_TABLE, pd.DataFrame({
            "symbol": symbol, "trade_date": days, "pe_ttm": 12.0, "pb_mrq": 0.5,
        }))
    repo.save_table(FUNDAMENTALS_TABLE, pd.DataFrame([
        {"symbol": one, "stat_date": "2026-06-30", "pub_date": days[1], "roe_avg": 0.12},
        {"symbol": two, "stat_date": "2026-06-30", "pub_date": days[2], "roe_avg": 0.15},
    ]))
    repo.save_table("corporate_actions", pd.DataFrame([
        {"symbol": one, "ex_date": DAY - timedelta(days=365), "cash_per_share": 9.0, "share_multiplier": 1.0},
        {"symbol": one, "ex_date": DAY - timedelta(days=200), "cash_per_share": 0.6, "share_multiplier": 1.0},
        {"symbol": one, "ex_date": DAY, "cash_per_share": 0.2, "share_multiplier": 2.0},
        {"symbol": one, "ex_date": DAY + timedelta(days=1), "cash_per_share": 9.0, "share_multiplier": 1.0},
        {"symbol": two, "ex_date": DAY - timedelta(days=10), "cash_per_share": 0.7, "share_multiplier": 1.0},
    ]))
    monkeypatch.setattr(workspace, "market_repository", lambda: repo)
    monkeypatch.setattr(workspace, "local_data_bounds", lambda: (days[0].date(), DAY))
    request = workspace.ScreenIn.model_validate({"scope": "market", "definition": {
        "name": "红利质量",
        "entry_rules": [
            {"left": {"name": "roe_avg"}, "operator": "gte", "value": 0.10},
            {"left": {"name": "pe_ttm"}, "operator": "gt", "value": 0},
            {"left": {"name": "pb_mrq"}, "operator": "lt", "value": 0.8},
        ],
        "ranking": {"indicator": {"name": "dividend_yield"}},
    }})
    rule, day, result = workspace._run_screen(request, {"id": 1})
    assert day == DAY
    assert rule.entry_rules[-1].describe() == "市净率（PB 最近一季）小于0.8"
    assert [item["symbol"] for item in result["items"]] == [two, one]
    assert [item["ranking"] for item in result["items"]] == pytest.approx([0.07, 0.04])

    strategy = RuleBasedStrategy.from_parameters("dividend", {"definition_json": rule.to_json()})
    frame = repo.get_daily_bars(None, days[0].date(), DAY, extras=strategy.data_fields)
    for trading_day, expected in zip(days, [[], [one], [two, one]], strict=True):
        context = StrategyContext.create(trading_day.date(), frame, (one, two, missing))
        assert [signal.symbol for signal in strategy.generate_signals(context)] == expected

    monkeypatch.setattr(workspace, "local_data_bounds", lambda: (days[0].date(), days[0].date()))
    with pytest.raises(HTTPException) as exc:
        workspace._run_screen(request, {"id": 1})
    assert exc.value.status_code == 409 and "财务数据" in exc.value.detail


@pytest.fixture
def api(monkeypatch, tmp_path):
    from app import database
    from app.routes import workspace
    from app.routes.auth import get_current_user

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "app.db"))   # 选股会记一笔“第一次选股”，不能写进真的数据库
    database.init_db()
    with database.get_conn() as conn:
        conn.execute("INSERT INTO users (id, name, email, password_hash, salt, created_at) VALUES (1, 'u', 'u1@example.test', 'h', 's', 'now')")

    monkeypatch.setattr(workspace, "local_data_bounds", lambda: (date(2015, 1, 5), DAY))
    asked = {}

    class Repository:
        def get_daily_bars(self, symbols, start, end):
            asked.update(symbols=symbols, start=start, end=end)
            frame = bars()
            return frame if symbols is None else frame[frame["symbol"].isin(symbols)]

    monkeypatch.setattr(workspace, "market_repository", lambda: Repository())
    monkeypatch.setattr(workspace, "security_names", lambda: {"600001.SH": "上涨股份", "600002.SH": "慢涨股份"})
    monkeypatch.setattr(workspace, "_load_universe_symbols", lambda uid: ["600001", "600003"])
    app = FastAPI()
    app.include_router(workspace.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_admin": False}
    return TestClient(app), asked


PAYLOAD = {"definition": {"name": "", "entry_logic": "all",
                          "entry_rules": [{"left": {"name": "close"}, "operator": "gt", "right": {"name": "sma", "window": 5}}],
                          "ranking": {"indicator": {"name": "return_1d", "window": 3}, "direction": "descending"}}}


def test_the_endpoint_screens_the_pool_or_the_whole_market(api):
    client, asked = api
    pool = client.post("/api/v1/packages/screen", json={**PAYLOAD, "scope": "pool"}).json()
    assert asked["symbols"] == ["600001.SH", "600003.SH"] and asked["end"] == DAY
    assert pool["trade_date"] == "2026-10-21" and pool["checked"] == 2 and pool["matched"] == 1
    assert pool["items"][0]["symbol"] == "600001" and pool["items"][0]["name"] == "上涨股份"
    assert pool["conditions"] == ["收盘价大于5日移动平均线"] and pool["ranking_label"] == "3日区间涨跌幅"
    assert pool["condition_indicators"] == [{"left": "close", "right": "moving_average"}]
    market = client.post("/api/v1/packages/screen", json={**PAYLOAD, "scope": "market", "limit": 1}).json()
    assert asked["symbols"] is None and market["matched"] == 2 and market["shown"] == 1
    from app import database
    with database.get_conn() as conn:   # 首页“开始使用”的“用条件选股筛一次股票”打勾，只记第一次
        assert conn.execute("SELECT COUNT(*) FROM user_milestones WHERE user_id = 1 AND kind = 'stock_screen'").fetchone()[0] == 1


def test_bad_rules_and_an_empty_pool_are_explained(api, monkeypatch):
    from app.routes import workspace

    client, _ = api
    bad = {"definition": {**PAYLOAD["definition"], "entry_rules": [{"left": {"name": "nonsense"}, "operator": "gt", "value": 1}]}}
    assert client.post("/api/v1/packages/screen", json=bad).status_code == 422
    monkeypatch.setattr(workspace, "_load_universe_symbols", lambda uid: [])
    empty = client.post("/api/v1/packages/screen", json={**PAYLOAD, "scope": "pool"})
    assert empty.status_code == 409 and "股票池是空的" in empty.json()["detail"]
