"""
Example integration of storage service with API endpoints.
This demonstrates how to use the storage layer in FastAPI routes.

NOTE: This is an example file. For production use, these patterns should be
integrated into the main api/routes.py file.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

from storage import get_db, StorageService
from storage.models import Position as DBPosition, Order as DBOrder

# Example router (would be integrated into main router)
storage_router = APIRouter(prefix="/storage-example", tags=["storage-example"])


# ============================================================================
# Database-backed Position Endpoints (Example)
# ============================================================================

@storage_router.get("/positions")
async def get_positions_db(db: Session = Depends(get_db)):
    """
    Get positions from database.
    Example of using storage service in an API endpoint.
    """
    storage = StorageService(db)
    positions = storage.get_open_positions()
    
    # Convert to API response format
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "cost_basis": p.cost_basis,
                "realized_pnl": p.realized_pnl,
                "is_open": p.is_open,
            }
            for p in positions
        ],
        "count": len(positions)
    }


@storage_router.post("/positions")
async def create_position_db(
    symbol: str,
    side: str,
    quantity: float,
    avg_entry_price: float,
    db: Session = Depends(get_db)
):
    """
    Create a new position in database.
    Example of creating database records via API.
    """
    storage = StorageService(db)
    
    # Validate input
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if avg_entry_price <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")
    if side not in ["long", "short"]:
        raise HTTPException(status_code=400, detail="Side must be 'long' or 'short'")
    
    # Create position
    position = storage.create_position(
        symbol=symbol,
        side=side,
        quantity=quantity,
        avg_entry_price=avg_entry_price
    )
    
    return {
        "message": "Position created successfully",
        "position": {
            "id": position.id,
            "symbol": position.symbol,
            "side": position.side.value,
            "quantity": position.quantity,
            "avg_entry_price": position.avg_entry_price,
            "cost_basis": position.cost_basis,
        }
    }


@storage_router.get("/positions/{symbol}")
async def get_position_by_symbol_db(symbol: str, db: Session = Depends(get_db)):
    """
    Get a specific position by symbol.
    Example of querying specific records.
    """
    storage = StorageService(db)
    position = storage.get_position_by_symbol(symbol)
    
    if not position:
        raise HTTPException(status_code=404, detail=f"Position for {symbol} not found")
    
    return {
        "symbol": position.symbol,
        "side": position.side.value,
        "quantity": position.quantity,
        "avg_entry_price": position.avg_entry_price,
        "cost_basis": position.cost_basis,
        "realized_pnl": position.realized_pnl,
        "is_open": position.is_open,
        "opened_at": position.opened_at.isoformat(),
    }


# ============================================================================
# Database-backed Order Endpoints (Example)
# ============================================================================

@storage_router.get("/orders")
async def get_orders_db(
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get orders from database.
    Example with query parameters.
    """
    storage = StorageService(db)
    
    if status:
        # Filter by status using repository directly
        from storage.models import OrderStatusEnum
        from storage.repositories import OrderRepository
        repo = OrderRepository(db)
        orders = repo.get_by_status(OrderStatusEnum(status), limit=limit)
    else:
        orders = storage.get_recent_orders(limit=limit)
    
    return {
        "orders": [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side.value,
                "type": o.type.value,
                "status": o.status.value,
                "quantity": o.quantity,
                "price": o.price,
                "filled_quantity": o.filled_quantity,
                "avg_fill_price": o.avg_fill_price,
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "count": len(orders)
    }


@storage_router.post("/orders")
async def create_order_db(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float] = None,
    db: Session = Depends(get_db)
):
    """
    Create a new order in database.
    Example of order creation workflow.
    """
    storage = StorageService(db)
    
    # Validate input
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if side not in ["buy", "sell"]:
        raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")
    if order_type not in ["market", "limit", "stop", "stop_limit"]:
        raise HTTPException(status_code=400, detail="Invalid order type")
    if order_type in ["limit", "stop_limit"] and not price:
        raise HTTPException(status_code=400, detail="Price required for limit orders")
    
    # Create order
    order = storage.create_order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price
    )
    
    return {
        "message": "Order created successfully",
        "order": {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.type.value,
            "status": order.status.value,
            "quantity": order.quantity,
            "price": order.price,
        }
    }


# ============================================================================
# Configuration Management with Database (Example)
# ============================================================================

@storage_router.get("/config")
async def get_config_db(db: Session = Depends(get_db)):
    """
    Get configuration from database.
    Example of using config storage.
    """
    storage = StorageService(db)
    config = storage.get_all_config()
    
    return {
        "config": config,
        "count": len(config)
    }


@storage_router.put("/config/{key}")
async def set_config_db(
    key: str,
    value: str,
    value_type: str = "string",
    description: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Set configuration value in database.
    Example of config upsert operation.
    """
    storage = StorageService(db)
    
    if value_type not in ["string", "int", "float", "bool", "json"]:
        raise HTTPException(status_code=400, detail="Invalid value_type")
    
    config = storage.set_config_value(key, value, value_type, description)
    
    return {
        "message": "Config updated successfully",
        "config": {
            "key": config.key,
            "value": config.value,
            "value_type": config.value_type,
            "description": config.description,
        }
    }


# ============================================================================
# How to integrate into main app
# ============================================================================
"""
To use this in your main app.py:

1. Import the router:
   from api.storage_examples import storage_router

2. Include it in your app:
   app.include_router(storage_router)

3. Or integrate these patterns directly into api/routes.py by:
   - Adding `db: Session = Depends(get_db)` to endpoint parameters
   - Creating StorageService instance: `storage = StorageService(db)`
   - Using storage methods instead of in-memory data
"""
