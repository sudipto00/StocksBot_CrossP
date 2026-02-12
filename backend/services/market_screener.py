"""
Market Screener Service.

Fetches and filters most actively traded stocks and ETFs.
Supports different asset types and volume-based screening.
"""

from typing import List, Dict, Any, Optional, Literal
from datetime import datetime, timedelta
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class AssetType(Enum):
    """Asset type for screening."""
    STOCK = "stock"
    ETF = "etf"
    BOTH = "both"


class MarketScreener:
    """
    Market screener for finding actively traded securities.
    
    Fetches most actively traded stocks and ETFs from Alpaca
    and provides filtering capabilities.
    """
    
    def __init__(self, alpaca_client=None):
        """
        Initialize market screener.
        
        Args:
            alpaca_client: Optional Alpaca trading client for real data
        """
        self.alpaca_client = alpaca_client
        self._cache: Dict[str, Any] = {}
        self._cache_timeout = 300  # 5 minutes
    
    def get_active_stocks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get most actively traded stocks.
        
        Args:
            limit: Maximum number of stocks to return (10-200)
            
        Returns:
            List of stock dictionaries with symbol, volume, price, etc.
        """
        limit = max(10, min(200, limit))  # Clamp between 10-200
        
        # Check cache
        cache_key = f"stocks_{limit}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]["data"]
        
        # Fetch from Alpaca or use fallback
        if self.alpaca_client:
            try:
                stocks = self._fetch_active_from_alpaca("stock", limit)
            except Exception as e:
                logger.warning(f"Failed to fetch from Alpaca: {e}, using fallback")
                stocks = self._get_fallback_stocks(limit)
        else:
            stocks = self._get_fallback_stocks(limit)
        
        # Cache results
        self._cache[cache_key] = {
            "data": stocks,
            "timestamp": datetime.now()
        }
        
        return stocks
    
    def get_active_etfs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get most actively traded ETFs.
        
        Args:
            limit: Maximum number of ETFs to return (10-200)
            
        Returns:
            List of ETF dictionaries with symbol, volume, price, etc.
        """
        limit = max(10, min(200, limit))  # Clamp between 10-200
        
        # Check cache
        cache_key = f"etfs_{limit}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]["data"]
        
        # Fetch from Alpaca or use fallback
        if self.alpaca_client:
            try:
                etfs = self._fetch_active_from_alpaca("etf", limit)
            except Exception as e:
                logger.warning(f"Failed to fetch from Alpaca: {e}, using fallback")
                etfs = self._get_fallback_etfs(limit)
        else:
            etfs = self._get_fallback_etfs(limit)
        
        # Cache results
        self._cache[cache_key] = {
            "data": etfs,
            "timestamp": datetime.now()
        }
        
        return etfs
    
    def get_screener_results(
        self,
        asset_type: AssetType = AssetType.BOTH,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get screener results based on asset type preference.
        
        Args:
            asset_type: Type of assets to screen (stock, etf, both)
            limit: Maximum total number of results (10-200)
            
        Returns:
            List of asset dictionaries
        """
        limit = max(10, min(200, limit))
        
        if asset_type == AssetType.STOCK:
            return self.get_active_stocks(limit)
        elif asset_type == AssetType.ETF:
            return self.get_active_etfs(limit)
        else:  # BOTH
            # Split limit between stocks and ETFs
            stock_limit = limit // 2
            etf_limit = limit - stock_limit
            
            stocks = self.get_active_stocks(stock_limit)
            etfs = self.get_active_etfs(etf_limit)
            
            # Combine and sort by volume
            combined = stocks + etfs
            combined.sort(key=lambda x: x.get("volume", 0), reverse=True)
            
            return combined[:limit]

    def get_preset_assets(self, asset_type: str, preset: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get curated assets for a specific strategy preset.

        Args:
            asset_type: "stock" or "etf"
            preset: Preset name
            limit: Max results (10-200)
        """
        limit = max(10, min(200, limit))
        asset_type = asset_type.lower()
        preset = preset.lower()

        if asset_type not in ("stock", "etf"):
            raise ValueError("asset_type must be 'stock' or 'etf'")

        stock_presets = {
            "weekly_optimized": ["NVDA", "TSLA", "AMD", "META", "AMZN", "AAPL", "MSFT", "GOOGL", "INTC", "CRM"],
            "three_to_five_weekly": ["AAPL", "MSFT", "AMZN", "GOOGL", "JPM", "V", "WMT", "KO", "PEP", "DIS"],
            "monthly_optimized": ["MSFT", "AAPL", "GOOGL", "JPM", "V", "WMT", "PEP", "KO", "CSCO", "ORCL"],
            "small_budget_weekly": ["INTC", "PFE", "CSCO", "PYPL", "BABA", "NKE", "DIS", "KO", "XLF", "IWM"],
        }
        etf_presets = {
            "conservative": ["SPY", "VOO", "IVV", "AGG", "TLT", "XLP", "XLV", "VEA", "VTI", "DIA"],
            "balanced": ["SPY", "QQQ", "VTI", "IWM", "XLF", "XLK", "XLI", "VEA", "VWO", "AGG"],
            "aggressive": ["QQQ", "IWM", "XLE", "XLK", "XLY", "EEM", "VWO", "XLF", "SPY", "DIA"],
        }

        all_assets = self.get_active_stocks(200) if asset_type == "stock" else self.get_active_etfs(200)
        by_symbol = {asset["symbol"]: asset for asset in all_assets}

        preset_map = stock_presets if asset_type == "stock" else etf_presets
        symbols = preset_map.get(preset)
        if not symbols:
            raise ValueError(f"Unknown preset '{preset}' for asset type '{asset_type}'")

        selected = [by_symbol[s] for s in symbols if s in by_symbol]
        if len(selected) < limit:
            existing = {s["symbol"] for s in selected}
            for asset in all_assets:
                if asset["symbol"] in existing:
                    continue
                selected.append(asset)
                if len(selected) >= limit:
                    break

        return selected[:limit]
    
    def _fetch_active_from_alpaca(
        self,
        asset_class: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch actively traded securities from Alpaca API.
        
        Note: This is a simplified implementation. Alpaca doesn't have
        a direct "most active" endpoint, so we'll use a combination of
        getting assets and their recent volume data.
        
        Args:
            asset_class: "stock" or "etf"
            limit: Number of results to return
            
        Returns:
            List of asset dictionaries
        """
        # This would require the Alpaca data client
        # For now, we'll use fallback data
        # In production, you would:
        # 1. Get list of tradeable assets from Alpaca
        # 2. Fetch recent bar data for volume
        # 3. Sort by volume and return top N
        
        raise NotImplementedError("Alpaca active screener not yet implemented")
    
    def _get_fallback_stocks(self, limit: int) -> List[Dict[str, Any]]:
        """
        Get fallback list of popular stocks.
        
        Returns well-known, liquid stocks when API is unavailable.
        """
        # Popular, liquid stocks sorted roughly by typical volume
        popular_stocks = [
            {"symbol": "AAPL", "name": "Apple Inc.", "volume": 75000000, "price": 175.50, "change_percent": 0.5},
            {"symbol": "TSLA", "name": "Tesla Inc.", "volume": 120000000, "price": 245.30, "change_percent": 1.2},
            {"symbol": "NVDA", "name": "NVIDIA Corp.", "volume": 60000000, "price": 525.75, "change_percent": 2.1},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "volume": 28000000, "price": 390.25, "change_percent": 0.3},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "volume": 45000000, "price": 155.80, "change_percent": -0.2},
            {"symbol": "META", "name": "Meta Platforms Inc.", "volume": 22000000, "price": 385.50, "change_percent": 0.8},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "volume": 25000000, "price": 142.60, "change_percent": 0.4},
            {"symbol": "AMD", "name": "Advanced Micro Devices", "volume": 55000000, "price": 165.90, "change_percent": 1.5},
            {"symbol": "NFLX", "name": "Netflix Inc.", "volume": 8000000, "price": 485.20, "change_percent": -0.5},
            {"symbol": "DIS", "name": "Walt Disney Co.", "volume": 12000000, "price": 92.50, "change_percent": 0.2},
            {"symbol": "BABA", "name": "Alibaba Group", "volume": 18000000, "price": 78.40, "change_percent": -1.0},
            {"symbol": "INTC", "name": "Intel Corp.", "volume": 35000000, "price": 42.30, "change_percent": 0.7},
            {"symbol": "BA", "name": "Boeing Co.", "volume": 6000000, "price": 185.60, "change_percent": 1.3},
            {"symbol": "JPM", "name": "JPMorgan Chase", "volume": 10000000, "price": 165.40, "change_percent": 0.1},
            {"symbol": "V", "name": "Visa Inc.", "volume": 7000000, "price": 258.30, "change_percent": 0.6},
            {"symbol": "WMT", "name": "Walmart Inc.", "volume": 8000000, "price": 168.50, "change_percent": -0.1},
            {"symbol": "PFE", "name": "Pfizer Inc.", "volume": 30000000, "price": 28.75, "change_percent": 0.3},
            {"symbol": "KO", "name": "Coca-Cola Co.", "volume": 12000000, "price": 60.20, "change_percent": 0.2},
            {"symbol": "PEP", "name": "PepsiCo Inc.", "volume": 5000000, "price": 172.80, "change_percent": 0.1},
            {"symbol": "NKE", "name": "Nike Inc.", "volume": 7000000, "price": 98.40, "change_percent": -0.3},
            {"symbol": "CSCO", "name": "Cisco Systems", "volume": 18000000, "price": 49.60, "change_percent": 0.4},
            {"symbol": "ADBE", "name": "Adobe Inc.", "volume": 3000000, "price": 558.70, "change_percent": 0.9},
            {"symbol": "CRM", "name": "Salesforce Inc.", "volume": 6000000, "price": 248.50, "change_percent": 0.7},
            {"symbol": "ORCL", "name": "Oracle Corp.", "volume": 8000000, "price": 118.30, "change_percent": 0.5},
            {"symbol": "PYPL", "name": "PayPal Holdings", "volume": 12000000, "price": 62.40, "change_percent": -0.8},
        ]
        
        # Add asset type and timestamp
        for stock in popular_stocks:
            stock["asset_type"] = "stock"
            stock["last_updated"] = datetime.now().isoformat()
        
        return popular_stocks[:limit]
    
    def _get_fallback_etfs(self, limit: int) -> List[Dict[str, Any]]:
        """
        Get fallback list of popular ETFs.
        
        Returns well-known, liquid ETFs when API is unavailable.
        """
        # Popular, liquid ETFs sorted roughly by typical volume
        popular_etfs = [
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "volume": 80000000, "price": 485.20, "change_percent": 0.4},
            {"symbol": "QQQ", "name": "Invesco QQQ Trust", "volume": 50000000, "price": 395.60, "change_percent": 0.8},
            {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "volume": 35000000, "price": 198.30, "change_percent": 0.2},
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "volume": 5000000, "price": 242.50, "change_percent": 0.3},
            {"symbol": "EEM", "name": "iShares MSCI Emerging Markets ETF", "volume": 25000000, "price": 42.80, "change_percent": -0.5},
            {"symbol": "GLD", "name": "SPDR Gold Shares", "volume": 8000000, "price": 185.40, "change_percent": 0.1},
            {"symbol": "XLF", "name": "Financial Select Sector SPDR", "volume": 40000000, "price": 38.90, "change_percent": 0.3},
            {"symbol": "XLE", "name": "Energy Select Sector SPDR", "volume": 22000000, "price": 85.60, "change_percent": 1.2},
            {"symbol": "XLK", "name": "Technology Select Sector SPDR", "volume": 12000000, "price": 192.30, "change_percent": 0.6},
            {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "volume": 18000000, "price": 92.50, "change_percent": -0.2},
            {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "volume": 6000000, "price": 445.80, "change_percent": 0.4},
            {"symbol": "VEA", "name": "Vanguard FTSE Developed Markets ETF", "volume": 10000000, "price": 48.30, "change_percent": 0.1},
            {"symbol": "AGG", "name": "iShares Core U.S. Aggregate Bond ETF", "volume": 7000000, "price": 102.40, "change_percent": 0.0},
            {"symbol": "VWO", "name": "Vanguard FTSE Emerging Markets ETF", "volume": 15000000, "price": 43.70, "change_percent": -0.3},
            {"symbol": "IVV", "name": "iShares Core S&P 500 ETF", "volume": 5000000, "price": 485.30, "change_percent": 0.4},
            {"symbol": "DIA", "name": "SPDR Dow Jones Industrial Average ETF", "volume": 4000000, "price": 372.60, "change_percent": 0.2},
            {"symbol": "XLV", "name": "Health Care Select Sector SPDR", "volume": 8000000, "price": 142.80, "change_percent": 0.3},
            {"symbol": "XLI", "name": "Industrial Select Sector SPDR", "volume": 9000000, "price": 112.40, "change_percent": 0.5},
            {"symbol": "XLP", "name": "Consumer Staples Select Sector SPDR", "volume": 7000000, "price": 78.90, "change_percent": 0.1},
            {"symbol": "XLY", "name": "Consumer Discretionary Select Sector SPDR", "volume": 6000000, "price": 172.50, "change_percent": 0.7},
        ]
        
        # Add asset type and timestamp
        for etf in popular_etfs:
            etf["asset_type"] = "etf"
            etf["last_updated"] = datetime.now().isoformat()
        
        return popular_etfs[:limit]
    
    def _is_cache_valid(self, key: str) -> bool:
        """
        Check if cache entry is still valid.
        
        Args:
            key: Cache key to check
            
        Returns:
            True if cache is valid and not expired
        """
        if key not in self._cache:
            return False
        
        cache_age = (datetime.now() - self._cache[key]["timestamp"]).total_seconds()
        return cache_age < self._cache_timeout
    
    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
