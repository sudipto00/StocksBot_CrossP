# Trading Features for Personal Weekly Trader

## Overview

This implementation adds comprehensive features for a small personal trader focused on weekly trading with a budget of up to $200 per week. The system supports both stocks and ETFs with multiple risk profiles.

## Key Features

### 1. Market Screener
- **Pulls 10-200 most actively traded securities**
- Supports both stocks and ETFs
- Configurable result limits (10, 25, 50, 100, 200)
- Real-time filtering by asset type
- Cached data for performance (5-minute cache)

**API Endpoints:**
- `GET /screener/stocks?limit=50` - Get most active stocks
- `GET /screener/etfs?limit=50` - Get most active ETFs  
- `GET /screener/all?asset_type=both&limit=100` - Get combined results

### 2. Risk Profiles

Three pre-configured risk profiles tailored for weekly trading:

#### Conservative Profile
- **Max Position Size:** $50
- **Max Positions:** 3 at once
- **Position Sizing:** 20% of weekly budget
- **Stop Loss:** 3%
- **Take Profit:** 5%
- **Max Weekly Loss:** 15% of budget
- **Best For:** Stable, low-risk trading with established securities

#### Balanced Profile
- **Max Position Size:** $80
- **Max Positions:** 4 at once
- **Position Sizing:** 30% of weekly budget
- **Stop Loss:** 5%
- **Take Profit:** 8%
- **Max Weekly Loss:** 25% of budget
- **Best For:** Moderate risk with growth potential

#### Aggressive Profile
- **Max Position Size:** $120
- **Max Positions:** 5 at once
- **Position Sizing:** 40% of weekly budget
- **Stop Loss:** 8%
- **Take Profit:** 15%
- **Max Weekly Loss:** 40% of budget
- **Best For:** Higher risk tolerance, seeking maximum growth

**API Endpoints:**
- `GET /risk-profiles` - Get all risk profile configurations

### 3. Weekly Budget Tracking

Automatic tracking and management of weekly trading budget:

**Features:**
- Set weekly budget (default: $200)
- Track budget utilization in real-time
- Automatic weekly reset (every Monday)
- Weekly P&L tracking
- Trade count monitoring
- Budget validation before order execution

**Status Information:**
- Total weekly budget
- Budget used/remaining
- Used percentage
- Number of trades
- Weekly profit/loss
- Days remaining in week

**API Endpoints:**
- `GET /budget/status` - Get current budget status
- `POST /budget/update` - Update weekly budget amount

### 4. Trading Preferences

User-configurable preferences for personalized trading:

**Configurable Options:**
- **Asset Type:** Stock, ETF, or Both
- **Risk Profile:** Conservative, Balanced, or Aggressive
- **Weekly Budget:** $50 - $1000 (recommended: $200)
- **Screener Limit:** 10-200 results

**API Endpoints:**
- `GET /preferences` - Get current preferences
- `POST /preferences` - Update preferences

## Order Execution Integration

The order execution service now validates:
1. **Weekly Budget:** Orders are rejected if they exceed remaining weekly budget
2. **Risk Profile Limits:**
   - Maximum position size per profile
   - Maximum number of concurrent positions
   - Weekly loss limits
3. **Position Sizing:** Automatic calculation based on risk profile
4. **Trade Recording:** All executed trades are recorded in budget tracker

## Example Workflow

### Setting Up for Weekly Trading

1. **Configure Preferences:**
```bash
curl -X POST http://127.0.0.1:8000/preferences \
  -H "Content-Type: application/json" \
  -d '{
    "asset_type": "both",
    "risk_profile": "balanced",
    "weekly_budget": 200.0,
    "screener_limit": 50
  }'
```

2. **Get Screener Results:**
```bash
curl http://127.0.0.1:8000/screener/all
```

3. **Check Budget Status:**
```bash
curl http://127.0.0.1:8000/budget/status
```

4. **Place Order:**
```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "side": "buy",
    "type": "market",
    "quantity": 1
  }'
```

### Risk Profile Comparison

For a $200 weekly budget:

| Feature | Conservative | Balanced | Aggressive |
|---------|-------------|----------|-----------|
| Position Size | $40 (20%) | $60 (30%) | $80 (40%) |
| Max Positions | 3 | 4 | 5 |
| Max Loss/Week | $30 (15%) | $50 (25%) | $80 (40%) |
| Diversification | Required | Recommended | Optional |

## UI Components

### Screener Page (`/ui/src/pages/ScreenerPage.tsx`)

Features:
- Budget status dashboard
- Filter controls (asset type, risk profile, limits)
- Live screener results table
- Automatic refresh capability

Components:
- Budget status card with progress bar
- Filter settings panel
- Asset results table with sorting

### Settings Page Updates

Added information section highlighting new features:
- Market Screener availability
- Risk Profiles
- Budget Tracking
- Asset Type Preferences

## Testing

### Unit Tests

All new services have comprehensive test coverage:

**Market Screener Tests (11 tests):**
- Initialization
- Stock/ETF retrieval
- Limit clamping
- Cache functionality
- Data format validation

**Budget Tracker Tests (13 tests):**
- Budget initialization
- Trade recording
- Weekly reset
- Budget validation
- P&L tracking

**Risk Profile Tests (18 tests):**
- Profile configurations
- Position sizing
- Trade validation
- Risk characteristics

**Run Tests:**
```bash
cd backend
pytest tests/test_market_screener.py -v
pytest tests/test_budget_tracker.py -v
pytest tests/test_risk_profiles.py -v
```

## Technical Implementation

### Backend Services

**`services/market_screener.py`**
- Fetches actively traded stocks and ETFs
- Implements caching for performance
- Provides fallback data when API unavailable
- Supports filtering by asset type and limit

**`services/budget_tracker.py`**
- Tracks weekly budget allocation
- Automatic weekly resets
- Real-time budget status
- Trade recording and P&L tracking

**`config/risk_profiles.py`**
- Risk profile configurations
- Position sizing calculations
- Trade validation logic
- Profile comparison utilities

**`services/order_execution.py` (Enhanced)**
- Integrated budget tracking
- Risk profile validation
- Automatic trade recording
- Enhanced error messages

### API Models

New Pydantic models in `api/models.py`:
- `AssetType` - Asset type enumeration
- `ScreenerAsset` - Screener result model
- `ScreenerResponse` - Screener API response
- `RiskProfile` - Risk profile enumeration
- `RiskProfileInfo` - Risk profile details
- `TradingPreferencesRequest` - Preferences update request
- `TradingPreferencesResponse` - Preferences response
- `BudgetStatus` - Budget status model
- `BudgetUpdateRequest` - Budget update request

## Future Enhancements

Potential improvements for production use:

1. **Real-time Data Integration:**
   - Connect to Alpaca or other market data providers
   - Stream live price updates
   - Real-time volume tracking

2. **Enhanced Screeners:**
   - Custom screener criteria
   - Technical indicator filters
   - Fundamental metrics
   - Sector/industry filtering

3. **Advanced Risk Management:**
   - Portfolio correlation analysis
   - Value-at-Risk (VaR) calculations
   - Drawdown protection
   - Dynamic position sizing

4. **Performance Analytics:**
   - Weekly/monthly performance reports
   - Win rate tracking
   - Risk-adjusted returns
   - Benchmark comparison

5. **Automation:**
   - Scheduled screener updates
   - Automatic rebalancing
   - Stop-loss order placement
   - Take-profit triggers

## Configuration

### Environment Variables

```bash
# Weekly Budget (optional, default: 200)
WEEKLY_BUDGET=200

# Default Risk Profile (optional, default: balanced)
DEFAULT_RISK_PROFILE=balanced

# Default Asset Type (optional, default: both)
DEFAULT_ASSET_TYPE=both

# Screener Cache Timeout in seconds (optional, default: 300)
SCREENER_CACHE_TIMEOUT=300
```

### Backend Configuration

Edit `backend/api/routes.py` to change defaults:
```python
_trading_preferences = TradingPreferencesResponse(
    asset_type=AssetType.BOTH,
    risk_profile=RiskProfile.BALANCED,
    weekly_budget=200.0,
    screener_limit=50,
)
```

## Security Considerations

1. **Budget Limits:** Always validated server-side
2. **Position Size:** Enforced by risk profile
3. **Weekly Loss:** Monitored and enforced
4. **API Validation:** All inputs validated with Pydantic
5. **No Hardcoded Secrets:** Use environment variables

## Support

For issues or questions:
1. Review API documentation in `API.md`
2. Check test cases for usage examples
3. Review this trading features guide
4. Open an issue on GitHub

## License

Same as parent project (see root LICENSE file)
