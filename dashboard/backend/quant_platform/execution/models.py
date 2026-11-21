"""Order and fill domain models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4


class OrderSide(StrEnum):
    """Long-only order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    """Order lifecycle shared by backtest, paper, and future live adapters."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class OrderRejectReason(StrEnum):
    """Stable machine-readable reasons for rejecting simulated orders."""

    MISSING_EXECUTION_BAR = "MISSING_EXECUTION_BAR"
    INVALID_EXECUTION_PRICE = "INVALID_EXECUTION_PRICE"
    SUSPENDED = "SUSPENDED"
    UNKNOWN_SUSPENSION_STATUS = "UNKNOWN_SUSPENSION_STATUS"
    UNKNOWN_MARKET_STATUS = "UNKNOWN_MARKET_STATUS"
    MARKET_DATA_NOT_TRADABLE = "MARKET_DATA_NOT_TRADABLE"
    UNKNOWN_PRICE_LIMIT = "UNKNOWN_PRICE_LIMIT"
    OPEN_AT_UPPER_LIMIT = "OPEN_AT_UPPER_LIMIT"
    OPEN_AT_LOWER_LIMIT = "OPEN_AT_LOWER_LIMIT"
    INSUFFICIENT_CASH_OR_QUANTITY = "INSUFFICIENT_CASH_OR_QUANTITY"


class TradeReason(StrEnum):
    """Stable machine-readable reason for why a simulated order or fill was generated."""

    REBALANCE_BUY = "REBALANCE_BUY"
    REBALANCE_SELL = "REBALANCE_SELL"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    MARKET_TIMING_SELL = "MARKET_TIMING_SELL"
    RISK_REDUCE = "RISK_REDUCE"
    RISK_LIQUIDATE = "RISK_LIQUIDATE"


TRADE_REASON_LABELS: dict[str, str] = {
    TradeReason.REBALANCE_BUY.value: "调仓买入",
    TradeReason.REBALANCE_SELL.value: "调仓卖出",
    TradeReason.STOP_LOSS.value: "个股止损",
    TradeReason.TRAILING_STOP.value: "移动止盈",
    TradeReason.MARKET_TIMING_SELL.value: "大盘择时降仓",
    TradeReason.RISK_REDUCE.value: "风控减仓",
    TradeReason.RISK_LIQUIDATE.value: "风控清仓",
}


@dataclass(frozen=True)
class Order:
    """Quantity order created after a signal for a later execution date."""

    order_id: str
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: int
    signal_date: date
    execution_date: date
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: int = 0
    reject_reason: str | None = None
    priority: int = 0
    reason: str = ""

    @classmethod
    def create(
        cls,
        strategy_id: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        signal_date: date,
        execution_date: date,
        *,
        priority: int = 0,
        reason: str = "",
    ) -> Order:
        """Create an order with a unique identifier."""

        return cls(
            str(uuid4()),
            strategy_id,
            symbol,
            side,
            quantity,
            signal_date,
            execution_date,
            priority=priority,
            reason=reason,
        )

    @property
    def remaining_quantity(self) -> int:
        """Return the unfilled quantity."""

        return max(self.quantity - self.filled_quantity, 0)

    def with_status(self, status: OrderStatus, reason: str | None = None) -> Order:
        """Return an updated immutable order."""

        return replace(self, status=status, reject_reason=reason)

    def with_fill(self, quantity: int) -> Order:
        """Apply a fill quantity and derive full or partial status."""

        if quantity <= 0 or self.filled_quantity + quantity > self.quantity:
            raise ValueError("invalid order fill quantity")
        filled = self.filled_quantity + quantity
        status = OrderStatus.FILLED if filled == self.quantity else OrderStatus.PARTIALLY_FILLED
        return replace(self, filled_quantity=filled, status=status)


@dataclass(frozen=True)
class Fill:
    """Executed paper trade, including its reference price and slippage cost."""

    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    commission: float
    stamp_tax: float
    trade_date: date
    filled_at: datetime
    reference_price: float
    slippage_cost: float
    adj_factor: float = 1.0
    transfer_fee: float = 0.0
    reason: str = ""

    @classmethod
    def create(
        cls,
        order: Order,
        quantity: int,
        price: float,
        commission: float,
        stamp_tax: float,
        reference_price: float | None = None,
        slippage_cost: float = 0.0,
        adj_factor: float = 1.0,
        transfer_fee: float = 0.0,
        reason: str | None = None,
    ) -> Fill:
        """Create a fill for an order on its configured execution date."""

        return cls(
            fill_id=str(uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
            commission=commission,
            stamp_tax=stamp_tax,
            trade_date=order.execution_date,
            filled_at=datetime.now(UTC),
            reference_price=(price if reference_price is None else reference_price),
            slippage_cost=slippage_cost,
            adj_factor=adj_factor,
            transfer_fee=transfer_fee,
            reason=order.reason if reason is None else reason,
        )
