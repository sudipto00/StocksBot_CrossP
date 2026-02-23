"""
Order Execution Service.

Orchestrates the order lifecycle from submission to fill tracking.
Handles validation, broker integration, and storage persistence.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging
import threading
import time
import uuid
import math
from collections import deque

from sqlalchemy.orm import Session

from services.broker import BrokerInterface, OrderSide, OrderType, OrderStatus
from storage.service import StorageService
from storage.models import Order, OrderStatusEnum, Trade
from services.budget_tracker import get_budget_tracker
from config.risk_profiles import RiskProfile, validate_trade, get_position_size

logger = logging.getLogger(__name__)
_GLOBAL_KILL_SWITCH = False
_GLOBAL_KILL_SWITCH_LOCK = threading.Lock()
_GLOBAL_TRADING_ENABLED = True
_GLOBAL_TRADING_ENABLED_LOCK = threading.Lock()


def set_global_kill_switch(active: bool) -> None:
    """Enable/disable global kill switch for order submissions."""
    global _GLOBAL_KILL_SWITCH
    with _GLOBAL_KILL_SWITCH_LOCK:
        _GLOBAL_KILL_SWITCH = bool(active)


def get_global_kill_switch() -> bool:
    """Read global kill switch state."""
    with _GLOBAL_KILL_SWITCH_LOCK:
        return _GLOBAL_KILL_SWITCH


def set_global_trading_enabled(active: bool) -> None:
    """Enable/disable global trading execution gate."""
    global _GLOBAL_TRADING_ENABLED
    with _GLOBAL_TRADING_ENABLED_LOCK:
        _GLOBAL_TRADING_ENABLED = bool(active)


def get_global_trading_enabled() -> bool:
    """Read global trading execution gate."""
    with _GLOBAL_TRADING_ENABLED_LOCK:
        return _GLOBAL_TRADING_ENABLED


class OrderExecutionError(Exception):
    """Base exception for order execution errors."""
    pass


class OrderValidationError(OrderExecutionError):
    """Exception raised when order validation fails."""
    pass


class BrokerError(OrderExecutionError):
    """Exception raised when broker operation fails."""
    pass


class OrderExecutionService:
    """
    Service for executing trading orders.
    
    This service:
    1. Validates orders against account limits and risk rules
    2. Submits orders to the configured broker
    3. Persists orders and tracks external broker IDs
    4. Polls broker for order fills
    5. Creates trade records and updates positions
    """
    
    def __init__(
        self,
        broker: BrokerInterface,
        storage: StorageService,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
        enable_budget_tracking: bool = True,
        risk_profile: Optional[RiskProfile] = None,
        order_throttle_per_minute: int = 60,
    ):
        """
        Initialize order execution service.
        
        Args:
            broker: Broker interface for order execution
            storage: Storage service for persistence
            max_position_size: Maximum position size in dollars
            risk_limit_daily: Daily risk limit in dollars
            enable_budget_tracking: Enable weekly budget tracking
            risk_profile: Optional risk profile for validation
        """
        self.broker = broker
        self.storage = storage
        self.max_position_size = max_position_size
        self.risk_limit_daily = risk_limit_daily
        self.enable_budget_tracking = enable_budget_tracking
        self.risk_profile = risk_profile
        self.order_throttle_per_minute = max(1, int(order_throttle_per_minute))
        self._recent_order_timestamps: deque[float] = deque()
        self._throttle_lock = threading.Lock()
        
        # Get budget tracker if enabled
        if self.enable_budget_tracking:
            self.budget_tracker = get_budget_tracker()
        else:
            self.budget_tracker = None

    @staticmethod
    def _same_price(a: Optional[float], b: Optional[float]) -> bool:
        """Compare optional prices for duplicate-order detection."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    
    def validate_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None
    ) -> None:
        """
        Validate order against account and risk limits.
        
        Args:
            symbol: Stock symbol
            side: Order side (buy/sell)
            order_type: Order type (market/limit)
            quantity: Order quantity
            price: Order price (for limit orders)
            
        Raises:
            OrderValidationError: If validation fails
        """
        # Validate quantity
        if quantity <= 0:
            raise OrderValidationError("Order quantity must be positive")
        
        # Validate price for limit orders
        if order_type == "limit" and price is None:
            raise OrderValidationError("Price required for limit orders")
        
        if price is not None and price <= 0:
            raise OrderValidationError("Price must be positive")
        
        if get_global_kill_switch():
            raise OrderValidationError("Trading is blocked: kill switch is active")
        if not get_global_trading_enabled():
            raise OrderValidationError("Trading is disabled in Settings")

        # Check broker connection
        if not self.broker.is_connected():
            raise BrokerError("Broker is not connected")

        if not self.broker.is_symbol_tradable(symbol):
            raise OrderValidationError(f"Symbol {symbol} is not tradable")

        if not self.broker.is_market_open():
            raise OrderValidationError("Market is closed")
        
        # Check account info
        try:
            account_info = self.broker.get_account_info()
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerError(f"Failed to get account info: {e}")
        
        # Validate buying power for buy orders
        if side == "buy":
            # Estimate order cost
            if order_type == "market":
                # For market orders, get current price
                try:
                    market_data = self.broker.get_market_data(symbol)
                    estimated_price = market_data.get("price", price or 0)
                except Exception as e:
                    logger.warning(f"Failed to get market data for {symbol}: {e}")
                    # Use provided price or a conservative estimate
                    estimated_price = price or 0
                    if estimated_price == 0:
                        raise OrderValidationError(
                            "Cannot validate market order without price data"
                        )
            else:
                estimated_price = price
            
            order_value = quantity * estimated_price
            equity = float(account_info.get("equity", account_info.get("portfolio_value", 0)) or 0)
            buying_power = float(account_info.get("buying_power", 0) or 0)

            # Buying power should be surfaced as the primary insufficiency reason.
            if order_value > buying_power:
                raise OrderValidationError(
                    f"Insufficient buying power: need ${order_value:.2f}, "
                    f"have ${buying_power:.2f}"
                )

            # Dynamic guardrails are clamped to account equity scale.
            effective_max_position_size = float(self.max_position_size)
            if equity > 0:
                effective_max_position_size = min(effective_max_position_size, max(100.0, equity * 0.25))
            effective_max_position_size = max(1.0, effective_max_position_size)
            
            # Check position size limit
            if order_value > effective_max_position_size:
                raise OrderValidationError(
                    f"Order value ${order_value:.2f} exceeds maximum position "
                    f"size ${effective_max_position_size:.2f} (balance-adjusted)"
                )

            # Clamp daily risk to account equity scale.
            effective_risk_limit_daily = float(self.risk_limit_daily)
            if equity > 0:
                effective_risk_limit_daily = min(effective_risk_limit_daily, max(50.0, equity * 0.05))
            effective_risk_limit_daily = max(1.0, effective_risk_limit_daily)
            logger.debug(
                "Dynamic limits for %s: max_position=%.2f daily_risk=%.2f equity=%.2f buying_power=%.2f",
                symbol,
                effective_max_position_size,
                effective_risk_limit_daily,
                equity,
                buying_power,
            )
            
            # Check weekly budget if enabled
            if self.enable_budget_tracking and self.budget_tracker:
                can_trade, reason = self.budget_tracker.can_trade(order_value)
                if not can_trade:
                    raise OrderValidationError(f"Budget check failed: {reason}")
            
            # Check risk profile limits if configured
            if self.risk_profile:
                # Get current positions count
                positions = self.storage.get_open_positions()
                current_positions = len(positions)
                
                # Get budget status for weekly loss calculation
                weekly_loss = 0.0
                if self.budget_tracker:
                    status = self.budget_tracker.get_budget_status()
                    # Weekly loss is negative P&L
                    weekly_loss = abs(min(0.0, status.get("weekly_pnl", 0.0)))
                    weekly_budget = status.get("weekly_budget", 200.0)
                else:
                    weekly_budget = 200.0
                
                # Validate against risk profile
                is_valid, msg = validate_trade(
                    self.risk_profile,
                    order_value,
                    weekly_budget,
                    current_positions,
                    weekly_loss
                )
                
                if not is_valid:
                    raise OrderValidationError(f"Risk profile check failed: {msg}")
    
    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        strategy_id: Optional[int] = None
    ) -> Order:
        """
        Submit an order for execution.
        
        This method:
        1. Validates the order
        2. Creates an order record in storage
        3. Submits the order to the broker
        4. Updates the order with the broker's external ID
        
        Args:
            symbol: Stock symbol
            side: Order side (buy/sell)
            order_type: Order type (market/limit)
            quantity: Order quantity
            price: Order price (for limit orders)
            strategy_id: Optional strategy ID
            
        Returns:
            Created order
            
        Raises:
            OrderValidationError: If validation fails
            BrokerError: If broker submission fails
        """
        if not self._acquire_throttle_slot():
            raise OrderValidationError(
                f"Order throttle exceeded: max {self.order_throttle_per_minute} orders/minute"
            )

        # Validate order
        self.validate_order(symbol, side, order_type, quantity, price)

        # Duplicate order prevention: reject if an open order already exists
        # for the same symbol + side + strategy.
        existing_open = self.storage.get_open_orders(limit=500)
        for existing_order in existing_open:
            is_same_order_shape = (
                existing_order.symbol == symbol
                and existing_order.side.value == side
                and existing_order.strategy_id == strategy_id
                and existing_order.type.value == order_type
                and self._same_price(existing_order.price, price)
            )
            if is_same_order_shape:
                raise OrderValidationError(
                    f"Duplicate order: pending {side} order already exists for {symbol} "
                    f"(order #{existing_order.id})"
                )

        # Create order in storage with PENDING status
        order = self.storage.create_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            strategy_id=strategy_id
        )

        try:
            # Generate deterministic client_order_id for broker-side idempotency
            ts_bucket = int(time.time() // 60)
            idem_seed = f"{strategy_id or 'manual'}-{symbol}-{side}-{order_type}-{quantity}-{price or 'market'}-{ts_bucket}"
            client_order_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, idem_seed))

            # Submit to broker
            broker_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            broker_type = OrderType[order_type.upper()]

            broker_response = self.broker.submit_order(
                symbol=symbol,
                side=broker_side,
                order_type=broker_type,
                quantity=quantity,
                price=price,
                client_order_id=client_order_id,
            )
            
            # Update order with broker's external ID and status
            raw_external_id = broker_response.get("id")
            external_id = str(raw_external_id).strip() if raw_external_id is not None else None
            if external_id == "":
                external_id = None
            if external_id:
                existing_order = self.storage.orders.get_by_external_id(str(external_id))
                if existing_order and existing_order.id != order.id:
                    logger.warning(
                        "Duplicate broker order detected for external_id=%s. "
                        "Returning existing order #%s and rejecting duplicate local row #%s.",
                        external_id,
                        existing_order.id,
                        order.id,
                    )
                    order.status = OrderStatusEnum.REJECTED
                    self.storage.orders.update(order)
                    return existing_order
            order.external_id = external_id
            order.status = self._map_broker_status(broker_response.get("status"))
            
            # Update fill information if available
            filled_quantity = broker_response.get("filled_quantity", 0)
            avg_fill_price = broker_response.get("avg_fill_price")
            
            if filled_quantity > 0:
                order.filled_quantity = filled_quantity
                order.avg_fill_price = avg_fill_price

            immediate_fill = order.status.value == "filled" and filled_quantity > 0
            order = self.storage.orders.update(order, auto_commit=not immediate_fill)
            
            logger.info(
                f"Order submitted: {order.id} (external: {order.external_id}), "
                f"{side} {quantity} {symbol} @ {price or 'market'}, "
                f"status: {order.status.value}"
            )
            
            # If order was filled immediately, process the fill
            if immediate_fill:
                commission = float(broker_response.get("commission", 0) or 0)
                self._process_fill(order, filled_quantity, avg_fill_price, commission=commission)
                
                # Record trade in budget tracker if enabled
                if self.enable_budget_tracking and self.budget_tracker and side == "buy":
                    trade_value = filled_quantity * avg_fill_price
                    self.budget_tracker.record_trade(trade_value, is_buy=True)
                    logger.info(f"Recorded trade in budget tracker: ${trade_value:.2f}")
            
            # Create audit log
            self.storage.create_audit_log(
                event_type="order_created",
                description=f"Order created: {side} {quantity} {symbol}",
                details={
                    "order_id": order.id,
                    "external_id": order.external_id,
                    "symbol": symbol,
                    "side": side,
                    "type": order_type,
                    "quantity": quantity,
                    "price": price,
                    "status": order.status.value
                },
                order_id=order.id,
                strategy_id=strategy_id
            )
            
            return order
            
        except Exception as e:
            self.storage.rollback()
            # Mark order as rejected
            order.status = OrderStatusEnum.REJECTED
            order = self.storage.orders.update(order)
            
            logger.error(f"Failed to submit order {order.id}: {e}")
            raise BrokerError(f"Failed to submit order to broker: {e}")

    def _acquire_throttle_slot(self) -> bool:
        """Rate-limit order submissions per rolling minute window."""
        now = time.time()
        window_start = now - 60.0
        with self._throttle_lock:
            while self._recent_order_timestamps and self._recent_order_timestamps[0] < window_start:
                self._recent_order_timestamps.popleft()
            if len(self._recent_order_timestamps) >= self.order_throttle_per_minute:
                return False
            self._recent_order_timestamps.append(now)
            return True
    
    def update_order_status(self, order: Order) -> Order:
        """
        Update order status from broker.
        
        Args:
            order: Order to update
            
        Returns:
            Updated order
        """
        if not order.external_id:
            logger.warning(f"Order {order.id} has no external ID, cannot update status")
            return order
        
        try:
            # Get current status from broker
            broker_order = self.broker.get_order(order.external_id)
            broker_status = broker_order.get("status")

            # Map broker status to our status
            new_status = self._map_broker_status(broker_status)

            # Broker returns cumulative filled_quantity; calculate delta vs what
            # we have already processed locally to avoid double-counting.
            filled_quantity = broker_order.get("filled_quantity", 0)
            avg_fill_price = broker_order.get("avg_fill_price")
            previously_processed = order.filled_quantity or 0.0
            fill_delta = filled_quantity - previously_processed

            should_process_fill = fill_delta > 0 and new_status.value in ("filled", "partially_filled")

            # Update order in storage
            if new_status != order.status or filled_quantity != order.filled_quantity:
                order = self.storage.update_order_status(
                    order.id,
                    new_status.value,
                    filled_quantity=filled_quantity,
                    avg_fill_price=avg_fill_price,
                    auto_commit=not should_process_fill,
                )

                logger.info(
                    f"Order {order.id} updated: {new_status.value}, "
                    f"filled {filled_quantity}/{order.quantity} (delta: {fill_delta})"
                )

                # Process NEW fill quantity only (works for both partial and full fills)
                if should_process_fill:
                    commission = float(broker_order.get("commission", 0) or 0)
                    # Prorate commission for partial fills
                    if filled_quantity > 0 and fill_delta < filled_quantity:
                        commission = commission * (fill_delta / filled_quantity)
                    self._process_fill(order, fill_delta, avg_fill_price, commission=commission)
            
            return order
            
        except Exception as e:
            self.storage.rollback()
            logger.error(f"Failed to update order {order.id} status: {e}")
            return order
    
    def _process_fill(
        self,
        order: Order,
        filled_quantity: float,
        avg_fill_price: float,
        commission: float = 0.0,
    ) -> None:
        """
        Process order fill atomically — trade + position + audit in one transaction.

        All DB operations use auto_commit=False so they are flushed but not
        committed individually. A single commit at the end ensures atomicity;
        if any step fails the entire fill is rolled back.

        Args:
            order: Filled order
            filled_quantity: Quantity filled (delta, not cumulative)
            avg_fill_price: Average fill price
            commission: Commission charged by broker (prorated for partial fills)
        """
        try:
            # Create trade record (flush only — no commit yet)
            trade = self.storage.record_trade(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side.value,
                quantity=filled_quantity,
                price=avg_fill_price,
                commission=commission,
                fees=0.0,
                strategy_id=getattr(order, "strategy_id", None),
                auto_commit=False,
            )

            logger.info(
                f"Trade recorded: {trade.id}, {order.side.value} "
                f"{filled_quantity} {order.symbol} @ ${avg_fill_price:.2f}"
            )

            # Update or create position (flush only — no commit yet)
            position = self.storage.get_position_by_symbol(order.symbol)

            if position is None:
                # Create new position
                pos_side = "long" if order.side.value == "buy" else "short"
                self.storage.create_position(
                    symbol=order.symbol,
                    side=pos_side,
                    quantity=filled_quantity,
                    avg_entry_price=avg_fill_price,
                    commission=commission,
                    auto_commit=False,
                )
                logger.info(
                    f"Position opened: {pos_side.upper()} {filled_quantity} {order.symbol} "
                    f"@ ${avg_fill_price:.2f}"
                )
            else:
                # Update existing position
                quantity_delta = filled_quantity if order.side.value == "buy" else -filled_quantity

                updated_position = self.storage.update_position_quantity(
                    position,
                    quantity_delta,
                    avg_fill_price,
                    commission=commission,
                    auto_commit=False,
                )

                if updated_position.is_open:
                    logger.info(
                        f"Position updated: {updated_position.side.value.upper()} "
                        f"{updated_position.quantity} {order.symbol} "
                        f"@ ${updated_position.avg_entry_price:.2f}"
                    )
                else:
                    logger.info(
                        f"Position closed: {order.symbol}, "
                        f"P&L: ${updated_position.realized_pnl:.2f}"
                    )

            # Create audit log (flush only — no commit yet)
            self.storage.create_audit_log(
                event_type="order_filled",
                description=f"Order filled: {order.side.value} {filled_quantity} {order.symbol}",
                details={
                    "order_id": order.id,
                    "trade_id": trade.id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": filled_quantity,
                    "price": avg_fill_price,
                    "commission": commission,
                },
                order_id=order.id,
                auto_commit=False,
            )

            # Atomically commit trade + position + audit together
            self.storage.commit()

        except Exception as exc:
            logger.error(
                f"Fill processing failed for order {order.id}, rolling back: {exc}"
            )
            self.storage.rollback()
            raise
    
    def _map_broker_status(self, broker_status: str) -> Any:
        """
        Map broker status to our OrderStatus enum.
        
        Args:
            broker_status: Broker status string
            
        Returns:
            OrderStatusEnum value
        """
        from storage.models import OrderStatusEnum
        
        # Normalize status string
        status_lower = broker_status.lower() if broker_status else "pending"
        
        # Map common broker statuses
        status_mapping = {
            "pending": OrderStatusEnum.PENDING,
            "submitted": OrderStatusEnum.OPEN,
            "accepted": OrderStatusEnum.OPEN,
            "new": OrderStatusEnum.OPEN,
            "open": OrderStatusEnum.OPEN,
            "filled": OrderStatusEnum.FILLED,
            "partially_filled": OrderStatusEnum.PARTIALLY_FILLED,
            "partial_fill": OrderStatusEnum.PARTIALLY_FILLED,
            "cancelled": OrderStatusEnum.CANCELLED,
            "canceled": OrderStatusEnum.CANCELLED,
            "rejected": OrderStatusEnum.REJECTED,
            "expired": OrderStatusEnum.CANCELLED,
        }
        
        return status_mapping.get(status_lower, OrderStatusEnum.PENDING)
