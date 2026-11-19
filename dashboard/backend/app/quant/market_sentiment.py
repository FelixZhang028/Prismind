"""Cached daily market sentiment table & API payload builder.

Stores the aggregated daily series (~200 KB for 10+ years) under ``data/runtime/market_sentiment``
so restarts and repeated page loads return in milliseconds; when a new trading day lands, only
the new day(s) are computed incrementally and appended atomically.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.ai_research.market_sentiment import (
    SENTIMENT_COLUMNS,
    build_daily_sentiment_table,
    build_sentiment_payload,
    home_sentiment_summary,
    industry_sentiment,
)

from .runtime import RUNTIME_ROOT, market_repository

logger = logging.getLogger("uvicorn.error")

CHECK_SECONDS = 600
_STORE: Path = RUNTIME_ROOT / "market_sentiment"
_LOCK = threading.Lock()
_BUILD_LOCK = threading.Lock()
_WARMING = False
_CACHE: dict[str, Any] = {
    "key": None,
    "daily": None,
    "industries": None,
}


def configure(store: Path) -> None:
    """Override cache directory (used in tests for full isolation)."""
    global _STORE
    with _LOCK:
        _STORE = Path(store)
        _CACHE.update(key=None, daily=None, industries=None)


def _cache_file() -> Path:
    return _STORE / "daily_sentiment.parquet"


def _repo_key(repository: Any) -> tuple[str, str, str] | None:
    bounds = repository.daily_bar_bounds()
    if bounds is None:
        return None
    root = str(getattr(repository, "root", ""))
    return (root, bounds[0].isoformat(), bounds[1].isoformat())


def _read_disk_cache() -> pd.DataFrame | None:
    path = _cache_file()
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:  # noqa: BLE001 - 损坏的缓存直接重建
        return None
    if frame.empty or not set(SENTIMENT_COLUMNS) <= set(frame.columns):
        return None
    return frame


def _write_disk_cache(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    path = _cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp.parquet")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _ensure_loaded(repository: Any) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    key = _repo_key(repository)
    if key is None:
        return pd.DataFrame(columns=SENTIMENT_COLUMNS), []

    with _LOCK:
        if _CACHE["key"] == key and _CACHE["daily"] is not None:
            return _CACHE["daily"], _CACHE["industries"] or []

    with _BUILD_LOCK:
        with _LOCK:
            if _CACHE["key"] == key and _CACHE["daily"] is not None:
                return _CACHE["daily"], _CACHE["industries"] or []
            existing = _CACHE["daily"] if _CACHE["daily"] is not None else _read_disk_cache()

        daily = build_daily_sentiment_table(repository, existing=existing)
        industries = industry_sentiment(repository)
        try:
            _write_disk_cache(daily)
        except OSError:
            logger.warning("无法写入市场情绪缓存文件，将仅保留在内存中")

        with _LOCK:
            _CACHE.update(key=key, daily=daily, industries=industries)
        return daily, industries


def _warm_in_background(repository: Any) -> None:
    global _WARMING
    with _LOCK:
        if _WARMING:
            return
        _WARMING = True

    def _run() -> None:
        global _WARMING
        try:
            _ensure_loaded(repository)
        except Exception:  # noqa: BLE001 - 后台预热失败不影响首页
            logger.exception("后台预热市场情绪缓存失败")
        finally:
            with _LOCK:
                _WARMING = False

    threading.Thread(target=_run, name="market-sentiment-warmer", daemon=True).start()


def get_sentiment(repository: Any, *, window: int = 60) -> dict[str, Any]:
    """Return the full Market Sentiment payload for the requested window (60 / 120 / 250)."""
    daily, industries = _ensure_loaded(repository)
    return build_sentiment_payload(daily, repository, window=window, industries=industries)


def home_summary(repository: Any) -> dict[str, Any] | None:
    """Non-blocking compact sentiment summary for /api/v1/home.

    Uses the in-memory or disk cache immediately when present; if missing or behind the latest
    trading day, triggers a background refresh without delaying the home page.
    """
    key = _repo_key(repository)
    if key is None:
        return None
    with _LOCK:
        cached_key = _CACHE["key"]
        daily = _CACHE["daily"]
    if daily is None:
        daily = _read_disk_cache()
        if daily is not None and not daily.empty:
            with _LOCK:
                if _CACHE["daily"] is None:
                    _CACHE["daily"] = daily
    if daily is None or daily.empty:
        _warm_in_background(repository)
        return None
    latest_cached = pd.to_datetime(daily["trade_date"]).max().date().isoformat()
    if cached_key != key and latest_cached < key[2]:
        _warm_in_background(repository)
    return home_sentiment_summary(daily, repository)


def warming_enabled() -> bool:
    return os.getenv("FELLOWQUANT_SENTIMENT_WARMER", "on").strip().lower() not in ("0", "off", "false", "no")


class MarketSentimentWarmer:
    """Daemon thread: keeps the daily market sentiment cache up to date after daily bar updates."""

    def __init__(self) -> None:
        self._stop = threading.Event()

    def tick(self) -> bool:
        if not warming_enabled():
            return False
        repository = market_repository()
        key = _repo_key(repository)
        if key is None:
            return False
        with _LOCK:
            if _CACHE["key"] == key and _CACHE["daily"] is not None:
                return False
        logger.info("预先更新市场情绪缓存（截至 %s）", key[2])
        _ensure_loaded(repository)
        return True

    def _loop(self) -> None:
        if self._stop.wait(5):
            return
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - 后台检查失败不能让线程退出
                logger.exception("预先更新市场情绪缓存失败")
            if self._stop.wait(CHECK_SECONDS):
                return

    def start(self) -> None:
        threading.Thread(target=self._loop, name="market-sentiment-warmer", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
