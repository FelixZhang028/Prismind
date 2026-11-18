"""Dated pool presets based on checked local index membership."""
import re
from dataclasses import dataclass

import pandas as pd

from quant_platform.data.index_constituents import (
    CHECKS_TABLE, CONSTITUENTS_TABLE, CSI_800, CSI_800_COMPONENTS, checked_range, members_on, stored_lists,
)

COMPONENT_COUNTS = {"000300.SH": 300, "000905.SH": 500}
INDEX_POOLS = {
    "000300.SH": ("沪深 300", ("000300.SH",), 300),
    CSI_800: ("中证 800", CSI_800_COMPONENTS, 800),
}
# CSI 800 combines the CSI 300 and CSI 500 samples on the same date:
# https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000906_Index_Methodology_cn.pdf


@dataclass(frozen=True)
class IndexPool:
    index: str
    name: str
    snapshot_date: str
    source: str
    symbols: tuple[str, ...]

    def metadata(self) -> dict:
        return {
            "index": self.index, "name": self.name, "snapshot_date": self.snapshot_date,
            "source": self.source, "count": len(self.symbols),
        }


def index_pools(repository) -> dict[str, IndexPool]:
    """Only offer complete snapshots on dates checked for every component."""
    checks = repository.read_table(CHECKS_TABLE)
    constituents = repository.read_table(CONSTITUENTS_TABLE)
    ranges = {code: checked_range(checks, code) for code in COMPONENT_COUNTS}
    lists = {code: stored_lists(constituents, code) for code in ranges}
    pools = {}
    for code, (name, components, size) in INDEX_POOLS.items():
        covered = [ranges[component] for component in components]
        if any(span is None for span in covered):
            continue
        day = min(span[1] for span in covered)
        if day < max(span[0] for span in covered):
            continue
        members = [members_on(lists[component], day) for component in components]
        if any(part is None for part in members):
            continue
        if any(len(part) != expected for part, expected in zip(members, (COMPONENT_COUNTS[c] for c in components), strict=True)):
            continue
        symbols = tuple(sorted(set().union(*members)))
        if len(symbols) != size or any(not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol) for symbol in symbols):
            continue
        sources = set()
        for component in components:
            effective = max(stamp for stamp in lists[component] if stamp <= day)
            rows = constituents[
                constituents["index_symbol"].eq(component)
                & pd.to_datetime(constituents["effective_date"]).eq(pd.Timestamp(effective))
            ]
            if "source" in rows:
                sources.update(str(value) for value in rows["source"].dropna() if value)
        source = "、".join("BaoStock" if value == "baostock" else value for value in sorted(sources)) or "本地历史成分记录"
        if len(components) > 1:
            source += "（同日沪深 300 与中证 500）"
        pools[code] = IndexPool(code, name, day.isoformat(), source, symbols)
    return pools
