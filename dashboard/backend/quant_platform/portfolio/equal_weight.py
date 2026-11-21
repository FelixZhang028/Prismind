"""Equal-weight target portfolio constructor."""

from __future__ import annotations

from math import fsum
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
    ) -> list[TargetPosition]:
        """Build equal-weight targets; an empty signal set means all cash."""

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
        if effective_buffer > 0 and held_symbols:
            kept = [
                signal
                for signal in ranked[: self.top_n + effective_buffer]
                if signal.symbol in held_symbols
            ][: self.top_n]
            kept_symbols = {signal.symbol for signal in kept}
            remaining = self.top_n - len(kept)
            added = [signal for signal in ranked if signal.symbol not in kept_symbols][:remaining]
            selected = sorted([*kept, *added], key=lambda signal: (-signal.score, signal.symbol))
        else:
            selected = ranked[: self.top_n]
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
