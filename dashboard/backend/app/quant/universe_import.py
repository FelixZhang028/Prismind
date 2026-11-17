"""Explicit, lossless stock-code import accounting."""
import re

MAX_POOL_SIZE = 6000


def merge_codes(current: list[str], supplied: list[str]) -> dict:
    symbols = list(dict.fromkeys(current))
    seen = set(symbols)
    added, duplicates, invalid = [], [], []
    for raw in supplied:
        value = raw.strip().upper()
        match = re.fullmatch(r"(?:(?:SH|SZ|BJ)\.?)(\d{6})", value)
        if match:
            value = match.group(1)
        else:
            match = re.fullmatch(r"(\d{6})(?:\.(?:SH|SZ|BJ))?", value)
            if not match:
                invalid.append(raw)
                continue
            value = match.group(1)
        if value in seen:
            duplicates.append(raw)
        else:
            seen.add(value)
            symbols.append(value)
            added.append(value)
    return dict(symbols=symbols, count=len(symbols), input_count=len(supplied),
                added_count=len(added), duplicate_count=len(duplicates), invalid_count=len(invalid),
                added=added, duplicates=duplicates, invalid=invalid, limit=MAX_POOL_SIZE)
