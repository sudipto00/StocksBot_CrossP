"""
Tests for Market Screener Service.
"""

import pytest
from services.market_screener import MarketScreener, AssetType


def test_market_screener_initialization():
    """Test market screener can be initialized."""
    screener = MarketScreener()
    assert screener is not None
    assert screener._cache == {}


def test_get_active_stocks():
    """Test getting active stocks."""
    screener = MarketScreener()
    stocks = screener.get_active_stocks(limit=10)
    
    assert len(stocks) == 10
    assert all(stock["asset_type"] == "stock" for stock in stocks)
    assert all("symbol" in stock for stock in stocks)
    assert all("name" in stock for stock in stocks)
    assert all("volume" in stock for stock in stocks)
    assert all("price" in stock for stock in stocks)


def test_get_active_etfs():
    """Test getting active ETFs."""
    screener = MarketScreener()
    etfs = screener.get_active_etfs(limit=10)
    
    assert len(etfs) == 10
    assert all(etf["asset_type"] == "etf" for etf in etfs)
    assert all("symbol" in etf for etf in etfs)
    assert all("name" in etf for etf in etfs)


def test_limit_clamping():
    """Test that limits are clamped to valid range."""
    screener = MarketScreener()
    
    # Test minimum
    stocks = screener.get_active_stocks(limit=5)
    assert len(stocks) == 10  # Should be clamped to 10
    
    # Test maximum
    stocks = screener.get_active_stocks(limit=300)
    assert len(stocks) <= 200  # Should be clamped to 200


def test_get_screener_results_stocks_only():
    """Test screener with stocks only."""
    screener = MarketScreener()
    results = screener.get_screener_results(AssetType.STOCK, limit=15)
    
    assert len(results) == 15
    assert all(r["asset_type"] == "stock" for r in results)


def test_get_screener_results_etfs_only():
    """Test screener with ETFs only."""
    screener = MarketScreener()
    results = screener.get_screener_results(AssetType.ETF, limit=15)
    
    assert len(results) == 15
    assert all(r["asset_type"] == "etf" for r in results)


def test_get_screener_results_both():
    """Test screener with both stocks and ETFs."""
    screener = MarketScreener()
    results = screener.get_screener_results(AssetType.BOTH, limit=20)
    
    assert len(results) == 20
    # Should have mix of stocks and ETFs
    asset_types = set(r["asset_type"] for r in results)
    assert "stock" in asset_types
    assert "etf" in asset_types


def test_cache_functionality():
    """Test that caching works."""
    screener = MarketScreener()
    
    # First call should populate cache
    stocks1 = screener.get_active_stocks(limit=10)
    assert "stocks_10" in screener._cache
    
    # Second call should use cache
    stocks2 = screener.get_active_stocks(limit=10)
    assert stocks1 == stocks2
    
    # Clear cache
    screener.clear_cache()
    assert len(screener._cache) == 0


def test_fallback_stocks_data():
    """Test that fallback data includes expected stocks."""
    screener = MarketScreener()
    stocks = screener.get_active_stocks(limit=25)
    
    symbols = [s["symbol"] for s in stocks]
    
    # Check some well-known stocks are included
    expected_symbols = ["AAPL", "MSFT", "TSLA", "GOOGL", "AMZN"]
    for symbol in expected_symbols:
        assert symbol in symbols, f"{symbol} should be in fallback stocks"


def test_fallback_etfs_data():
    """Test that fallback data includes expected ETFs."""
    screener = MarketScreener()
    etfs = screener.get_active_etfs(limit=20)
    
    symbols = [e["symbol"] for e in etfs]
    
    # Check some well-known ETFs are included
    expected_symbols = ["SPY", "QQQ", "IWM", "VOO"]
    for symbol in expected_symbols:
        assert symbol in symbols, f"{symbol} should be in fallback ETFs"


def test_screener_data_format():
    """Test that screener returns properly formatted data."""
    screener = MarketScreener()
    stocks = screener.get_active_stocks(limit=5)
    
    for stock in stocks:
        # Required fields
        assert isinstance(stock["symbol"], str)
        assert isinstance(stock["name"], str)
        assert isinstance(stock["asset_type"], str)
        assert isinstance(stock["volume"], int)
        assert isinstance(stock["price"], (int, float))
        assert isinstance(stock["change_percent"], (int, float))
        assert isinstance(stock["last_updated"], str)
        
        # Valid values
        assert len(stock["symbol"]) > 0
        assert stock["volume"] >= 0
        assert stock["price"] > 0


def test_optimize_assets_accepts_portfolio_context_kwargs():
    """Regression: optimize_assets should accept portfolio context kwargs from API routes."""
    screener = MarketScreener()
    assets = screener.get_active_stocks(limit=30)

    optimized = screener.optimize_assets(
        assets=assets,
        limit=12,
        min_dollar_volume=1_000_000,
        max_spread_bps=200,
        max_sector_weight_pct=60,
        regime="range_bound",
        auto_regime_adjust=True,
        current_holdings=[{"symbol": "AAPL", "asset_type": "stock", "market_value": 1000}],
        buying_power=5_000,
        equity=25_000,
        weekly_budget=800,
    )

    assert isinstance(optimized, list)
    assert len(optimized) <= 12
    assert all("symbol" in item for item in optimized)


def test_optimize_assets_enforces_tradable_and_fractionable_for_micro_workflows():
    """When strict execution filters are enabled, non-fractionable symbols should be excluded."""
    screener = MarketScreener()
    assets = [
        {
            "symbol": "AAA",
            "name": "High Price Non Fractionable",
            "asset_type": "stock",
            "volume": 25_000_000,
            "price": 500.0,
            "change_percent": 1.2,
            "last_updated": "2026-01-01T00:00:00",
        },
        {
            "symbol": "BBB",
            "name": "High Price Fractionable",
            "asset_type": "stock",
            "volume": 25_000_000,
            "price": 500.0,
            "change_percent": 1.0,
            "last_updated": "2026-01-01T00:00:00",
        },
    ]

    optimized = screener.optimize_assets(
        assets=assets,
        limit=2,
        min_dollar_volume=1_000_000,
        max_spread_bps=200,
        max_sector_weight_pct=100,
        regime="range_bound",
        auto_regime_adjust=False,
        buying_power=50,
        equity=500,
        weekly_budget=50,
        symbol_capabilities={
            "AAA": {"tradable": True, "fractionable": False},
            "BBB": {"tradable": True, "fractionable": True},
        },
        require_broker_tradable=True,
        require_fractionable=True,
        target_position_size=30,
        dca_tranches=1,
    )

    symbols = [row["symbol"] for row in optimized]
    assert "BBB" in symbols
    assert "AAA" not in symbols


def test_chart_indicators_use_true_atr_from_ohlc():
    """ATR should use true range from high/low/previous-close, not close-to-close proxy only."""
    screener = MarketScreener()
    points = [
        {"timestamp": "2026-01-01T00:00:00", "close": 100.0, "high": 102.0, "low": 98.0},
        {"timestamp": "2026-01-02T00:00:00", "close": 105.0, "high": 107.0, "low": 104.0},
        {"timestamp": "2026-01-03T00:00:00", "close": 103.0, "high": 106.0, "low": 101.0},
        {"timestamp": "2026-01-04T00:00:00", "close": 108.0, "high": 110.0, "low": 107.0},
        {"timestamp": "2026-01-05T00:00:00", "close": 107.0, "high": 109.0, "low": 106.0},
    ]

    indicators = screener.get_chart_indicators(points)

    # TR series uses gaps against previous close:
    # [7, 5, 7, 3] => ATR abs = 5.5; ATR% = 5.5 / 107 * 100 = 5.1402
    assert indicators["atr14"] == pytest.approx(5.5, rel=1e-6)
    assert indicators["atr14_pct"] == pytest.approx(5.1402, rel=1e-6)


def test_get_preset_assets_seed_only_disables_backfill():
    """seed_only should limit output to preset seed symbols only (no active-universe backfill)."""
    screener = MarketScreener()
    assets = screener.get_preset_assets(
        asset_type="stock",
        preset="micro_budget",
        limit=50,
        seed_only=True,
    )
    symbols = {row["symbol"] for row in assets}
    seed_symbols = {"SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"}
    assert symbols
    assert symbols.issubset(seed_symbols)
    assert len(assets) <= len(seed_symbols)


def test_get_preset_assets_guardrail_only_ignores_seed_subset():
    """guardrail_only should use active-universe candidates, not seed list only."""
    screener = MarketScreener()
    assets = screener.get_preset_assets(
        asset_type="stock",
        preset="micro_budget",
        limit=30,
        preset_universe_mode="guardrail_only",
    )
    symbols = {row["symbol"] for row in assets}
    seed_symbols = {"SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"}
    assert symbols
    assert any(symbol not in seed_symbols for symbol in symbols)


def test_get_preset_assets_rejects_unknown_universe_mode():
    """Invalid preset universe mode should fail fast."""
    screener = MarketScreener()
    with pytest.raises(ValueError):
        screener.get_preset_assets(
            asset_type="stock",
            preset="micro_budget",
            limit=20,
            preset_universe_mode="invalid_mode",
        )


def test_candidate_universe_tolerates_raw_alpaca_assets_with_new_enum_values():
    """Raw Alpaca rows with unknown enum values should be filtered, not crash screening."""
    screener = MarketScreener()

    class DummyTradingClient:
        def get_all_assets(self):
            return [
                {"symbol": "BTCUSD", "tradable": True, "status": "active", "class": "crypto_perp", "exchange": "CRYPTO", "name": "Bitcoin Perp"},
                {"symbol": "ABC", "tradable": True, "status": "active", "class": "us_equity", "exchange": "ASCX", "name": "ABC Corp"},
                {"symbol": "SPY", "tradable": True, "status": "active", "class": "us_equity", "exchange": "ARCA", "name": "SPDR S&P 500 ETF Trust"},
                {"symbol": "AAPL", "tradable": True, "status": "active", "class": "us_equity", "exchange": "NASDAQ", "name": "Apple Inc"},
                {"symbol": "ZZZZ", "tradable": False, "status": "active", "class": "us_equity", "exchange": "NYSE", "name": "Inactive"},
            ]

    screener._trading_client = DummyTradingClient()
    symbols, rows = screener._get_candidate_symbols_for_asset_class("stock")
    symbol_set = set(symbols)

    assert "AAPL" in symbol_set
    assert "ABC" in symbol_set
    assert "SPY" not in symbol_set  # ETF filtered in stock mode
    assert "BTCUSD" not in symbol_set  # Non us_equity class ignored
    assert all(row["asset_type"] == "stock" for row in rows)
