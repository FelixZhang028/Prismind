"""Equal-weight target portfolio constructor."""

from __future__ import annotations

from math import floor, fsum
from typing import cast

from quant_platform.portfolio.models import TargetPosition
from quant_platform.signals.models import Signal


class EqualWeightPortfolio:
    """Select the highest scored signals and allocate equal weights."""

    def __init__(self, top_n: int, *, hold_buffer: int = 0) -> None:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        if hold_buffer < 0:
            raise ValueError("hold_buffer must be non-negative")
        self.top_n = top_n
        self.hold_buffer = hold_buffer

    def construct(
        self,
        signals: list[Signal],
        *,
        held_symbols: set[str] | None = None,
        hold_buffer: int | None = None,
        max_industry_weight: float | None = None,
        industry_map: dict[str, str] | None = None,
    ) -> list[TargetPosition]:
        """Build equal-weight targets; an empty signal set means all cash.

        When ``max_industry_weight < 1`` and ``industry_map`` is available,
        each industry is capped at ``max(1, floor(max_industry_weight * top_n))``
        positions so remaining slots backfill with top-ranked stocks from other industries
        instead of leaving excessive uninvested cash.
        """

        if not signals:
            return []
        explicit = [signal for signal in signals if signal.target_weight is not None]
        if explicit and len(explicit) != len(signals):
            raise ValueError("signals must either all specify target_weight or all omit it")
        if explicit:
            total_weight = fsum(cast(float, signal.target_weight) for signal in explicit)
            if any(cast(float, signal.target_weight) <= 0.0 for signal in explicit):
                raise ValueError("explicit signal target weights must be positive")
            if total_weight > 1.0 + 1e-9:
                raise ValueError("explicit signal target weights must not exceed one")
            return [
                TargetPosition(
                    strategy_id=signal.strategy_id,
                    signal_date=signal.trade_date,
                    symbol=signal.symbol,
                    target_weight=cast(float, signal.target_weight),
                )
                for signal in sorted(
                    explicit,
                    key=lambda signal: (-signal.score, signal.symbol),
                )
            ]

        ranked = sorted(signals, key=lambda signal: (-signal.score, signal.symbol))
        effective_buffer = self.hold_buffer if hold_buffer is None else hold_buffer
        use_industry_cap = (
            max_industry_weight is not None
            and 0.0 < max_industry_weight < 1.0 - 1e-9
            and bool(industry_map)
        )
        max_per_industry = (
            max(1, int(floor(max_industry_weight * self.top_n + 1e-9)))
            if use_industry_cap and max_industry_weight is not None
            else self.top_n
        )

        def pick(candidates: list[Signal], limit: int, counts: dict[str, int], chosen: set[str]) -> list[Signal]:
            picked: list[Signal] = []
            for signal in candidates:
                if len(picked) >= limit:
                    break
                if signal.symbol in chosen:
                    continue
                if use_industry_cap and industry_map is not None:
                    ind = industry_map.get(signal.symbol)
                    if ind:
                        if counts.get(ind, 0) >= max_per_industry:
                            continue
                        counts[ind] = counts.get(ind, 0) + 1
                chosen.add(signal.symbol)
                picked.append(signal)
            return picked

        industry_counts: dict[str, int] = {}
        chosen_symbols: set[str] = set()
        if effective_buffer > 0 and held_symbols:
            kept_candidates = [
                signal
                for signal in ranked[: self.top_n + effective_buffer]
                if signal.symbol in held_symbols
            ]
            kept = pick(kept_candidates, self.top_n, industry_counts, chosen_symbols)
            added = pick(ranked, self.top_n - len(kept), industry_counts, chosen_symbols)
            selected = sorted([*kept, *added], key=lambda signal: (-signal.score, signal.symbol))
        else:
            selected = pick(ranked, self.top_n, industry_counts, chosen_symbols)
        if not selected:
            return []
        weight = 1.0 / len(selected)
        return [
            TargetPosition(
                strategy_id=signal.strategy_id,
                signal_date=signal.trade_date,
                symbol=signal.symbol,
                target_weight=weight,
            )
            for signal in selected
        ]
