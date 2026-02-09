# Storage Module

The storage module provides a database-backed persistence layer for StocksBot. It uses SQLAlchemy ORM with SQLite for development and supports PostgreSQL for production.

## Architecture

```
storage/
├── database.py        # Database configuration and session management
├── models.py          # SQLAlchemy ORM models (schema definitions)
├── repositories.py    # Repository classes for CRUD operations
├── service.py         # High-level storage service
└── __init__.py        # Module exports
```

## Database Models

### Position
Tracks current and historical positions.
- `id`: Primary key
- `symbol`: Stock symbol
- `side`: LONG or SHORT
- `quantity`: Number of shares
- `avg_entry_price`: Average entry price
- `cost_basis`: Total cost basis
- `realized_pnl`: Realized profit/loss
- `is_open`: Whether position is currently open
- Timestamps: `created_at`, `updated_at`, `opened_at`, `closed_at`

### Order
Tracks all orders (pending, filled, cancelled).
- `id`: Primary key
- `external_id`: Broker order ID
- `symbol`: Stock symbol
- `side`: BUY or SELL
- `type`: MARKET, LIMIT, STOP, STOP_LIMIT
- `status`: PENDING, OPEN, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED
- `quantity`: Order quantity
- `price`: Limit/stop price (optional)
- `filled_quantity`: How much has been filled
- `avg_fill_price`: Average fill price
- `strategy_id`: Associated strategy (optional)
- Timestamps: `created_at`, `updated_at`, `filled_at`

### Trade
Individual trade executions. A single order can result in multiple trades.
- `id`: Primary key
- `order_id`: Reference to order
- `external_id`: Broker trade ID
- `symbol`: Stock symbol
- `side`: BUY or SELL
- `type`: OPEN, CLOSE, ADJUSTMENT
- `quantity`: Trade quantity
- `price`: Execution price
- `commission`: Commission paid
- `fees`: Other fees
- `realized_pnl`: Realized P&L (optional)
- Timestamps: `executed_at`, `created_at`

### Strategy
Trading strategy configurations.
- `id`: Primary key
- `name`: Unique strategy name
- `description`: Strategy description
- `strategy_type`: Type (e.g., "momentum", "mean_reversion")
- `config`: JSON configuration
- `is_active`: Whether strategy is currently running
- `is_enabled`: Whether strategy is enabled
- Performance metrics: `total_trades`, `win_rate`, `total_pnl`
- Timestamps: `created_at`, `updated_at`, `last_run_at`

### Config
Application configuration settings (key-value store).
- `id`: Primary key
- `key`: Unique config key
- `value`: Config value (stored as text)
- `value_type`: Type ("string", "int", "float", "bool", "json")
- `description`: Description of config
- Timestamps: `created_at`, `updated_at`

## Usage

### Basic Usage

```python
from storage import get_db, StorageService

# In a FastAPI endpoint
@app.get("/positions")
async def get_positions(db: Session = Depends(get_db)):
    storage = StorageService(db)
    positions = storage.get_open_positions()
    return positions
```

### Repository Pattern

```python
from storage.repositories import PositionRepository
from storage.models import PositionSideEnum

# Create a position
position_repo = PositionRepository(db)
position = position_repo.create(
    symbol="AAPL",
    side=PositionSideEnum.LONG,
    quantity=100.0,
    avg_entry_price=150.0,
    cost_basis=15000.0
)

# Get position by symbol
position = position_repo.get_by_symbol("AAPL", is_open=True)

# Close a position
closed_position = position_repo.close_position(position, realized_pnl=500.0)
```

### Storage Service

```python
from storage.service import StorageService

storage = StorageService(db)

# Position operations
position = storage.create_position("AAPL", "long", 100.0, 150.0)
open_positions = storage.get_open_positions()

# Order operations
order = storage.create_order("MSFT", "buy", "market", 50.0)
recent_orders = storage.get_recent_orders(limit=10)

# Trade operations
trade = storage.record_trade(
    order_id=order.id,
    symbol="MSFT",
    side="buy",
    quantity=50.0,
    price=300.0
)

# Config operations
storage.set_config_value("trading_enabled", "true", "bool")
value = storage.get_config_value("trading_enabled")
```

## Database Migrations

### Setup (First Time)

```bash
cd backend
alembic upgrade head
```

### Create New Migration

After modifying models in `models.py`:

```bash
alembic revision --autogenerate -m "Description of changes"
alembic upgrade head
```

### Migration Commands

```bash
# Upgrade to latest
alembic upgrade head

# Downgrade one version
alembic downgrade -1

# View history
alembic history

# View current version
alembic current
```

## Database Configuration

### SQLite (Development - Default)

```python
# No configuration needed - uses sqlite:///./stocksbot.db
```

### PostgreSQL (Production)

```bash
# Set environment variable
export DATABASE_URL="postgresql://user:password@localhost/stocksbot"
```

### Enable SQL Echo (Debugging)

```bash
export SQL_ECHO=true
```

## Testing

Run storage tests:

```bash
cd backend
pytest tests/test_storage.py -v
```

Tests use an in-memory SQLite database for fast, isolated testing.

## Best Practices

1. **Use Storage Service**: Prefer `StorageService` over direct repository access for business logic
2. **Dependency Injection**: Use FastAPI's `Depends(get_db)` for database sessions
3. **Session Management**: Always use context managers or dependency injection for database sessions
4. **Migrations**: Never modify the database schema directly - always use Alembic migrations
5. **Testing**: Use in-memory SQLite for fast unit tests
6. **Enums**: Use the provided enum types for type safety

## Future Enhancements

- [ ] Add database connection pooling configuration
- [ ] Implement database backup/restore utilities
- [ ] Add soft delete support for critical entities
- [ ] Implement audit logging for all changes
- [ ] Add database performance monitoring
- [ ] Create database seeding utilities for testing
- [ ] Add support for read replicas
