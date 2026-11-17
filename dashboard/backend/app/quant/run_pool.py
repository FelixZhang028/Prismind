"""Report the stock scope recorded for a run, independent of today's settings."""
from pathlib import Path

import yaml

from quant_platform.data.index_constituents import INDEX_UNIVERSES, index_name


def _pool(section: dict, market: str, count: int | None = None) -> dict:
    index = section.get("index")
    if not index and market in INDEX_UNIVERSES:
        index = market
    if index in INDEX_UNIVERSES:
        return {"name": f"{index_name(index)}历史成分股", "kind": "historical", "count": count}
    if count is None and section.get("mode") != "historical" and isinstance(section.get("symbols"), list):
        symbols = section["symbols"]
        if all(isinstance(symbol, str) for symbol in symbols):
            count = len(set(symbols))
    preset = section.get("preset")
    if isinstance(preset, dict) and preset.get("name"):
        return {**preset, "kind": "snapshot", "count": count}
    if market == "当前股票池" or section.get("symbols"):
        return {"name": "当前股票池", "kind": "fixed", "count": count}
    return {"name": None, "count": None}


def pool_from_snapshot(snapshot: dict, market: str, count: int | None = None) -> dict:
    root = snapshot.get("universe", {})
    section = root.get("universe", {}) if isinstance(root, dict) else {}
    return _pool(section if isinstance(section, dict) else {}, market, count)


def persisted_pool(result: dict, market: str, directory: Path | None) -> dict:
    if isinstance(result.get("pool"), dict):
        return result["pool"]
    if directory is not None:
        try:
            snapshot = yaml.safe_load((directory / "config.snapshot.yaml").read_text(encoding="utf-8"))
            if isinstance(snapshot, dict):
                return pool_from_snapshot(snapshot, market)
        except (OSError, UnicodeError, yaml.YAMLError):
            pass
    return _pool({}, market)
