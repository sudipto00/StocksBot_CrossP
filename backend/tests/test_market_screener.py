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
