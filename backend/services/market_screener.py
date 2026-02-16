"""
Market Screener Service.

Fetches and filters most actively traded stocks and ETFs.
Supports different asset types and volume-based screening.
"""

from typing import List, Dict, Any, Optional, Literal, Tuple
from datetime import datetime, timedelta
import logging
from enum import Enum
import math

from config.settings import get_settings, has_alpaca_credentials

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except Exception:
    StockHistoricalDataClient = None
    StockBarsRequest = None
    TimeFrame = None

try:
    from alpaca.trading.client import TradingClient
except Exception:
    TradingClient = None

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
    
    def __init__(self, alpaca_client=None, require_real_data: bool = False):
        """
        Initialize market screener.
        
        Args:
            alpaca_client: Optional Alpaca trading client for real data
            require_real_data: If true, raise when Alpaca data is unavailable instead of using fallback data
        """
        self.alpaca_client = alpaca_client
        self.require_real_data = bool(require_real_data)
        self._cache: Dict[str, Any] = {}
        self._cache_timeout = 300  # 5 minutes
        self._data_client = None
        self._trading_client = None
        self._last_source = "fallback"
        runtime_api_key = None
        runtime_secret_key = None
        if isinstance(alpaca_client, dict):
            runtime_api_key = (alpaca_client.get("api_key") or "").strip()
            runtime_secret_key = (alpaca_client.get("secret_key") or "").strip()

        if StockHistoricalDataClient:
            if runtime_api_key and runtime_secret_key:
                self._data_client = StockHistoricalDataClient(
                    api_key=runtime_api_key,
                    secret_key=runtime_secret_key
                )
                self._trading_client = self._create_trading_client(
                    api_key=runtime_api_key,
                    secret_key=runtime_secret_key,
                    paper=True,
                )
            elif has_alpaca_credentials():
                settings = get_settings()
                self._data_client = StockHistoricalDataClient(
                    api_key=settings.alpaca_api_key,
                    secret_key=settings.alpaca_secret_key
                )
                self._trading_client = self._create_trading_client(
                    api_key=settings.alpaca_api_key,
                    secret_key=settings.alpaca_secret_key,
                    paper=True,
                )
        if self.require_real_data and self._data_client is None:
            raise RuntimeError(
                "Strict Alpaca data mode is enabled but Alpaca data client could not be initialized"
            )

    def _create_trading_client(self, api_key: str, secret_key: str, paper: bool) -> Any:
        """Create TradingClient with raw payloads when supported by installed SDK."""
        if not TradingClient:
            return None
        try:
            # raw_data avoids strict enum parsing failures when Alpaca introduces new values.
            return TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=paper,
                raw_data=True,
            )
        except TypeError:
            # Older SDK builds may not accept raw_data; fall back to model mode.
            return TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=paper,
            )
    
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
            self._last_source = self._cache[cache_key].get("source", "fallback")
            return self._cache[cache_key]["data"]
        
        # Fetch from Alpaca data client or use fallback
        if self._data_client:
            try:
                stocks = self._fetch_active_from_data_client("stock", limit)
                self._last_source = "alpaca"
            except Exception as e:
                if self.require_real_data:
                    raise RuntimeError(f"Failed to fetch active stocks from Alpaca: {e}") from e
                logger.warning(f"Failed to fetch from Alpaca: {e}, using fallback")
                stocks = self._get_fallback_stocks(limit)
                self._last_source = "fallback"
        else:
            if self.require_real_data:
                raise RuntimeError("Strict Alpaca data mode is enabled but no Alpaca data client is available")
            stocks = self._get_fallback_stocks(limit)
            self._last_source = "fallback"
        
        # Cache results
        stocks = self._enrich_assets(stocks)
        self._cache[cache_key] = {
            "data": stocks,
            "timestamp": datetime.now(),
            "source": self._last_source,
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
            self._last_source = self._cache[cache_key].get("source", "fallback")
            return self._cache[cache_key]["data"]
        
        # Fetch from Alpaca data client or use fallback
        if self._data_client:
            try:
                etfs = self._fetch_active_from_data_client("etf", limit)
                self._last_source = "alpaca"
            except Exception as e:
                if self.require_real_data:
                    raise RuntimeError(f"Failed to fetch active ETFs from Alpaca: {e}") from e
                logger.warning(f"Failed to fetch from Alpaca: {e}, using fallback")
                etfs = self._get_fallback_etfs(limit)
                self._last_source = "fallback"
        else:
            if self.require_real_data:
                raise RuntimeError("Strict Alpaca data mode is enabled but no Alpaca data client is available")
            etfs = self._get_fallback_etfs(limit)
            self._last_source = "fallback"
        
        # Cache results
        etfs = self._enrich_assets(etfs)
        self._cache[cache_key] = {
            "data": etfs,
            "timestamp": datetime.now(),
            "source": self._last_source,
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
            stocks_source = self._last_source
            etfs = self.get_active_etfs(etf_limit)
            etfs_source = self._last_source
            
            # Combine and sort by volume
            combined = stocks + etfs
            combined.sort(key=lambda x: x.get("volume", 0), reverse=True)
            self._last_source = "alpaca" if stocks_source == "alpaca" and etfs_source == "alpaca" else (
                "fallback" if stocks_source == "fallback" and etfs_source == "fallback" else "mixed"
            )
            
            return combined[:limit]

    def get_last_source(self) -> str:
        """Return source used for latest screener pull."""
        return self._last_source

    def get_preset_assets(
        self,
        asset_type: str,
        preset: str,
        limit: int = 50,
        seed_only: bool = False,
        preset_universe_mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get curated assets for a specific strategy preset.

        Args:
            asset_type: "stock" or "etf"
            preset: Preset name
            limit: Max results (10-200)
            seed_only: Deprecated compatibility flag. When True and
                preset_universe_mode is not provided, behaves like seed_only mode.
            preset_universe_mode: One of:
                - "seed_only": preset seeds only (no backfill)
                - "seed_guardrail_blend": seed + active-universe backfill
                - "guardrail_only": ignore seeds and use active universe only
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
            "micro_budget": ["SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"],
        }
        etf_presets = {
            "conservative": ["SPY", "VOO", "IVV", "AGG", "TLT", "XLP", "XLV", "VEA", "VTI", "DIA"],
            "balanced": ["SPY", "QQQ", "VTI", "IWM", "XLF", "XLK", "XLI", "VEA", "VWO", "AGG"],
            "aggressive": ["QQQ", "IWM", "XLE", "XLK", "XLY", "EEM", "VWO", "XLF", "SPY", "DIA"],
        }

        # Pull a wider active universe so preset seed symbols have a better chance
        # to resolve from live data before any fallback is needed.
        active_universe_limit = max(200, min(800, limit * 8))
        all_assets = self.get_active_stocks(active_universe_limit) if asset_type == "stock" else self.get_active_etfs(active_universe_limit)
        by_symbol = {asset["symbol"]: asset for asset in all_assets}
        fallback_seed_assets = self._get_fallback_stocks(400) + self._get_fallback_etfs(200)
        fallback_by_symbol = {asset["symbol"]: asset for asset in fallback_seed_assets}

        preset_map = stock_presets if asset_type == "stock" else etf_presets
        symbols = preset_map.get(preset)
        if not symbols:
            raise ValueError(f"Unknown preset '{preset}' for asset type '{asset_type}'")

        normalized_mode = (preset_universe_mode or "").strip().lower()
        if not normalized_mode:
            normalized_mode = "seed_only" if seed_only else "seed_guardrail_blend"
        allowed_modes = {"seed_only", "seed_guardrail_blend", "guardrail_only"}
        if normalized_mode not in allowed_modes:
            raise ValueError(
                f"Unknown preset_universe_mode '{normalized_mode}'. "
                "Expected one of: seed_only, seed_guardrail_blend, guardrail_only"
            )

        selected: List[Dict[str, Any]] = []
        for symbol in symbols:
            live_row = by_symbol.get(symbol)
            if live_row:
                selected.append(dict(live_row))
                continue
            fallback_row = fallback_by_symbol.get(symbol)
            if fallback_row:
                selected.append(dict(fallback_row))
                continue
            selected.append({
                "symbol": symbol,
                "name": symbol,
                "asset_type": asset_type,
                "volume": 0,
                "price": 0.0,
                "change_percent": 0.0,
                "last_updated": datetime.now().isoformat(),
            })
        if normalized_mode == "guardrail_only":
            selected = list(all_assets)
        elif normalized_mode == "seed_guardrail_blend" and len(selected) < limit:
            existing = {s["symbol"] for s in selected}
            for asset in all_assets:
                if asset["symbol"] in existing:
                    continue
                selected.append(asset)
                if len(selected) >= limit:
                    break

        return self._enrich_assets(selected[:limit])
    
    def _fetch_active_from_data_client(self, asset_class: str, limit: int) -> List[Dict[str, Any]]:
        """Fetch active securities by ranking latest daily volume from Alpaca bars."""
        if not self._data_client or not StockBarsRequest or not TimeFrame:
            raise RuntimeError("Alpaca data client unavailable")

        symbols, seed_asset_rows = self._get_candidate_symbols_for_asset_class(asset_class)
        if not symbols:
            raise RuntimeError("No active symbols available from Alpaca universe")
        by_symbol = {asset["symbol"]: asset for asset in seed_asset_rows}

        start = datetime.now() - timedelta(days=10)
        bars_by_symbol: Dict[str, List[Any]] = {}
        for chunk_start in range(0, len(symbols), 200):
            chunk = symbols[chunk_start:chunk_start + 200]
            req = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Day,
                start=start,
            )
            bars_resp = self._data_client.get_stock_bars(req)
            if hasattr(bars_resp, "data"):
                chunk_data = bars_resp.data or {}
            elif isinstance(bars_resp, dict):
                chunk_data = bars_resp
            else:
                chunk_data = {}
            for symbol, bars in chunk_data.items():
                bars_by_symbol[symbol] = bars

        ranked_assets: List[Dict[str, Any]] = []
        for symbol in symbols:
            bars = bars_by_symbol.get(symbol, [])
            if not bars:
                ranked_assets.append(by_symbol[symbol])
                continue
            latest = bars[-1]
            previous = bars[-2] if len(bars) > 1 else None
            latest_close = float(getattr(latest, "close", by_symbol[symbol]["price"]))
            latest_volume = int(getattr(latest, "volume", by_symbol[symbol]["volume"]))
            if previous and float(getattr(previous, "close", 0.0)) > 0:
                prev_close = float(previous.close)
                change_percent = ((latest_close - prev_close) / prev_close) * 100.0
            else:
                change_percent = float(by_symbol[symbol]["change_percent"])
            ranked_assets.append({
                "symbol": symbol,
                "name": by_symbol[symbol]["name"],
                "asset_type": asset_class,
                "volume": latest_volume,
                "price": latest_close,
                "change_percent": change_percent,
                "last_updated": datetime.now().isoformat(),
            })

        ranked_assets.sort(key=lambda x: x.get("volume", 0), reverse=True)
        return ranked_assets[:limit]

    def _asset_field(self, asset: Any, key: str, default: Any = None) -> Any:
        """Read asset fields from either SDK model objects or raw dict payloads."""
        if isinstance(asset, dict):
            value = asset.get(key, default)
        else:
            value = getattr(asset, key, default)
        if key == "asset_class" and (value is None or str(value).strip() == ""):
            if isinstance(asset, dict):
                value = asset.get("class")
            else:
                value = getattr(asset, "class", default)
        if hasattr(value, "value"):
            return value.value
        return value if value is not None else default

    def _asset_bool(self, asset: Any, key: str, default: bool = False) -> bool:
        """Coerce mixed payload fields to bool (supports string/integer payloads)."""
        value = self._asset_field(asset, key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        if isinstance(value, (int, float)):
            return bool(value)
        return bool(default)

    def _get_candidate_symbols_for_asset_class(self, asset_class: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Resolve candidate symbols using Alpaca tradable universe with fallback safety."""
        fallback_assets = (
            self._get_fallback_stocks(200)
            if asset_class == "stock"
            else self._get_fallback_etfs(200)
        )
        fallback_by_symbol = {asset["symbol"]: asset for asset in fallback_assets}
        fallback_symbols = [asset["symbol"] for asset in fallback_assets]

        if not self._trading_client:
            return fallback_symbols, fallback_assets

        try:
            all_assets = self._trading_client.get_all_assets()
        except Exception as exc:
            if self.require_real_data:
                raise RuntimeError(f"Failed to fetch Alpaca tradable asset universe: {exc}") from exc
            logger.warning("Failed to fetch Alpaca tradable assets: %s", exc)
            return fallback_symbols, fallback_assets

        candidate_rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for asset in all_assets:
            symbol = str(self._asset_field(asset, "symbol", "") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            # Keep only active, US-equity style tradable rows.
            if not self._asset_bool(asset, "tradable", False):
                continue
            status = str(self._asset_field(asset, "status", "")).lower()
            if status not in {"active", "assetstatus.active"}:
                continue
            asset_class_name = str(self._asset_field(asset, "asset_class", "")).lower()
            if asset_class_name and "us_equity" not in asset_class_name and "us-equity" not in asset_class_name:
                continue
            asset_name = str(self._asset_field(asset, "name", "") or "")
            is_probable_etf = self._is_probable_etf_asset(symbol, asset_name)
            if asset_class == "etf" and not is_probable_etf:
                continue
            if asset_class == "stock" and is_probable_etf:
                continue
            seen.add(symbol)
            fallback_row = fallback_by_symbol.get(symbol)
            candidate_rows.append({
                "symbol": symbol,
                "name": str(asset_name or (fallback_row or {}).get("name", symbol)),
                "asset_type": asset_class,
                "volume": int((fallback_row or {}).get("volume", 0)),
                "price": float((fallback_row or {}).get("price", 0.0)),
                "change_percent": float((fallback_row or {}).get("change_percent", 0.0)),
                "last_updated": datetime.now().isoformat(),
            })
            # Keep request payload bounded so bar pulls stay practical.
            if len(candidate_rows) >= 1500:
                break

        if not candidate_rows:
            if self.require_real_data:
                raise RuntimeError(f"No Alpaca tradable symbols found for asset class {asset_class}")
            return fallback_symbols, fallback_assets

        symbols = [row["symbol"] for row in candidate_rows]
        return symbols, candidate_rows

    def _is_probable_etf_asset(self, symbol: str, name: str) -> bool:
        """Heuristic ETF classifier for Alpaca asset metadata."""
        text = f"{symbol} {name}".lower()
        etf_terms = (" etf", "fund", "trust", "index", "ishares", "vanguard", "spdr", "invesco")
        return any(term in text for term in etf_terms)

    def detect_market_regime(self) -> str:
        """Detect simple market regime from SPY trend and volatility."""
        points = self.get_symbol_chart("SPY", days=80)
        closes = [float(p["close"]) for p in points][-60:]
        if len(closes) < 30:
            return "unknown"
        start = closes[0]
        end = closes[-1]
        trend = (end - start) / start if start else 0.0
        returns = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            if prev > 0:
                returns.append((closes[i] - prev) / prev)
        vol = (sum((r * r) for r in returns) / len(returns)) ** 0.5 if returns else 0.0
        if trend > 0.04 and vol < 0.02:
            return "trending_up"
        if trend < -0.04 and vol < 0.02:
            return "trending_down"
        if vol >= 0.02:
            return "high_volatility_range"
        return "range_bound"

    def get_preset_guardrails(self, asset_type: str, preset: str) -> Dict[str, float]:
        """Default guardrails per preset profile."""
        key = f"{asset_type}:{preset}".lower()
        defaults = {
            "stock:weekly_optimized": {"min_dollar_volume": 20_000_000, "max_spread_bps": 35, "max_sector_weight_pct": 40},
            "stock:three_to_five_weekly": {"min_dollar_volume": 12_000_000, "max_spread_bps": 45, "max_sector_weight_pct": 45},
            "stock:monthly_optimized": {"min_dollar_volume": 8_000_000, "max_spread_bps": 60, "max_sector_weight_pct": 50},
            "stock:small_budget_weekly": {"min_dollar_volume": 5_000_000, "max_spread_bps": 80, "max_sector_weight_pct": 55},
            "stock:micro_budget": {"min_dollar_volume": 2_000_000, "max_spread_bps": 150, "max_sector_weight_pct": 60},
            "etf:conservative": {"min_dollar_volume": 15_000_000, "max_spread_bps": 30, "max_sector_weight_pct": 35},
            "etf:balanced": {"min_dollar_volume": 10_000_000, "max_spread_bps": 40, "max_sector_weight_pct": 40},
            "etf:aggressive": {"min_dollar_volume": 7_000_000, "max_spread_bps": 55, "max_sector_weight_pct": 45},
        }
        return defaults.get(key, {"min_dollar_volume": 10_000_000, "max_spread_bps": 50, "max_sector_weight_pct": 45})

    def optimize_assets(
        self,
        assets: List[Dict[str, Any]],
        limit: int,
        min_dollar_volume: float,
        max_spread_bps: float,
        max_sector_weight_pct: float,
        regime: str,
        auto_regime_adjust: bool = True,
        current_holdings: Optional[List[Dict[str, Any]]] = None,
        buying_power: float = 0.0,
        equity: float = 0.0,
        weekly_budget: float = 0.0,
        symbol_capabilities: Optional[Dict[str, Dict[str, Any]]] = None,
        require_broker_tradable: bool = False,
        require_fractionable: bool = False,
        target_position_size: float = 0.0,
        dca_tranches: int = 1,
        min_fractional_notional: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """Apply scoring and guardrails (liquidity/spread/sector concentration)."""

        def _safe_non_negative(value: Any) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(parsed):
                return 0.0
            return max(0.0, parsed)

        if auto_regime_adjust:
            if regime == "high_volatility_range":
                max_spread_bps = min(max_spread_bps, 35)
                min_dollar_volume = max(min_dollar_volume, 15_000_000)
            elif regime == "trending_up":
                max_spread_bps = min(max_spread_bps + 10, 90)
            elif regime == "trending_down":
                min_dollar_volume = max(min_dollar_volume, 18_000_000)

        holdings = current_holdings or []
        held_symbols = {
            str(row.get("symbol", "")).strip().upper()
            for row in holdings
            if str(row.get("symbol", "")).strip()
        }
        safe_buying_power = _safe_non_negative(buying_power)
        safe_equity = _safe_non_negative(equity)
        safe_weekly_budget = _safe_non_negative(weekly_budget)
        budget_candidates = [value for value in (safe_buying_power, safe_weekly_budget, safe_equity * 0.20) if value > 0]
        portfolio_budget_cap = min(budget_candidates) if budget_candidates else 0.0
        capability_map = symbol_capabilities if isinstance(symbol_capabilities, dict) else {}
        safe_min_fractional_notional = max(1.0, _safe_non_negative(min_fractional_notional))
        safe_dca_tranches = max(1, int(_safe_non_negative(dca_tranches) or 1))
        safe_target_position_size = _safe_non_negative(target_position_size)
        if safe_target_position_size <= 0:
            if safe_weekly_budget > 0:
                safe_target_position_size = max(safe_min_fractional_notional, safe_weekly_budget * 0.5)
            elif portfolio_budget_cap > 0:
                safe_target_position_size = max(safe_min_fractional_notional, portfolio_budget_cap * 0.4)
            else:
                safe_target_position_size = 100.0
        per_tranche_target = max(safe_min_fractional_notional, safe_target_position_size / safe_dca_tranches)

        candidates = self._enrich_assets(assets)
        for asset in candidates:
            dollar_volume = float(asset.get("dollar_volume", 0.0))
            spread = float(asset.get("spread_bps", 999.0))
            symbol = str(asset.get("symbol", "")).upper()
            price = max(0.0, float(asset.get("price", 0.0)))
            capability = capability_map.get(symbol, {}) if isinstance(capability_map.get(symbol, {}), dict) else {}
            broker_tradable = bool(capability.get("tradable", True))
            fractionable = bool(capability.get("fractionable", True))
            if fractionable:
                if portfolio_budget_cap > 0:
                    estimated_ticket = min(
                        per_tranche_target,
                        max(safe_min_fractional_notional, portfolio_budget_cap * 0.60),
                    )
                else:
                    estimated_ticket = per_tranche_target
                raw_affordable = portfolio_budget_cap <= 0 or portfolio_budget_cap >= safe_min_fractional_notional
            else:
                estimated_ticket = max(price, per_tranche_target)
                raw_affordable = portfolio_budget_cap <= 0 or estimated_ticket <= portfolio_budget_cap * 1.10
            if symbol in held_symbols:
                raw_affordable = True
            execution_ready = raw_affordable
            if require_broker_tradable and not broker_tradable:
                execution_ready = False
            if require_fractionable and not fractionable:
                execution_ready = False
            affordable = execution_ready
            tradable = dollar_volume >= min_dollar_volume and spread <= max_spread_bps and affordable
            asset["tradable"] = tradable
            asset["broker_tradable"] = broker_tradable
            asset["fractionable"] = fractionable
            asset["execution_ticket"] = round(estimated_ticket, 2)
            base_score = float(asset.get("score", 0.0))
            adjusted_score = base_score
            if symbol in held_symbols:
                adjusted_score += 3.0
            if portfolio_budget_cap > 0 and estimated_ticket > portfolio_budget_cap:
                adjusted_score -= min(20.0, ((estimated_ticket / portfolio_budget_cap) - 1.0) * 10.0)
            if require_fractionable and not fractionable:
                adjusted_score -= 25.0
            if require_broker_tradable and not broker_tradable:
                adjusted_score -= 25.0
            asset["_score_adjusted"] = round(adjusted_score, 2)
            if tradable:
                asset["selection_reason"] = (
                    f"Score {asset.get('_score_adjusted', asset.get('score', 0)):.1f}; "
                    f"${dollar_volume/1_000_000:.1f}M dollar vol; "
                    f"{spread:.1f} bps spread"
                )
                if symbol in held_symbols:
                    asset["selection_reason"] += "; continuity boost"
                if fractionable:
                    asset["selection_reason"] += "; fractional-ready"
            else:
                reasons = []
                if dollar_volume < min_dollar_volume:
                    reasons.append("low dollar volume")
                if spread > max_spread_bps:
                    reasons.append("wide spread")
                if require_broker_tradable and not broker_tradable:
                    reasons.append("not broker tradable")
                if require_fractionable and not fractionable:
                    reasons.append("not fractionable")
                if not raw_affordable and symbol not in held_symbols:
                    reasons.append("budget constrained")
                asset["selection_reason"] = "Filtered: " + ", ".join(reasons)

        tradable_assets = [a for a in candidates if a.get("tradable")]
        tradable_assets.sort(key=lambda a: float(a.get("_score_adjusted", a.get("score", 0.0))), reverse=True)
        max_sector_fraction = max(0.1, min(1.0, max_sector_weight_pct / 100.0))
        per_sector_cap = max(1, int(limit * max_sector_fraction))
        selected: List[Dict[str, Any]] = []
        sector_counts: Dict[str, int] = {}
        for asset in tradable_assets:
            sector = asset.get("sector", "Other")
            if sector_counts.get(sector, 0) >= per_sector_cap:
                continue
            selected.append(asset)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if len(selected) >= limit:
                break

        if len(selected) < limit:
            for asset in tradable_assets:
                if asset in selected:
                    continue
                selected.append(asset)
                if len(selected) >= limit:
                    break
        final = selected[:limit]
        for asset in final:
            asset.pop("_score_adjusted", None)
        return final

    def _enrich_assets(self, assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attach sector/spread/dollar-volume/score fields for explainability."""
        if not assets:
            return assets
        max_volume = max(float(a.get("volume", 0)) for a in assets) or 1.0
        enriched: List[Dict[str, Any]] = []
        for asset in assets:
            item = dict(asset)
            volume = float(item.get("volume", 0.0))
            price = float(item.get("price", 0.0))
            change = abs(float(item.get("change_percent", 0.0)))
            symbol = str(item.get("symbol", "")).upper()
            dollar_volume = volume * price
            spread_bps = max(4.0, 30.0 - min(24.0, volume / 7_000_000.0))
            sector = self._infer_sector(symbol, item.get("asset_type", "stock"))
            liquidity_score = min(100.0, (volume / max_volume) * 100.0)
            trend_score = max(0.0, 100.0 - (change * 4.5))
            spread_score = max(0.0, 100.0 - (spread_bps * 2.2))
            score = (liquidity_score * 0.5) + (trend_score * 0.3) + (spread_score * 0.2)
            item.update({
                "sector": sector,
                "dollar_volume": round(dollar_volume, 2),
                "spread_bps": round(spread_bps, 2),
                "score": round(score, 2),
                "tradable": True,
                "selection_reason": "Candidate in active universe",
            })
            enriched.append(item)
        return enriched

    def _infer_sector(self, symbol: str, asset_type: str) -> str:
        if asset_type == "etf":
            if symbol.startswith("XL"):
                return "Sector ETF"
            if symbol in {"AGG", "TLT", "IEF", "BND", "SHY", "LQD"}:
                return "Fixed Income"
            if symbol in {"GLD", "SLV", "USO", "UNG", "DBC"}:
                return "Commodities"
            return "Broad Market ETF"
        tech = {"AAPL", "MSFT", "NVDA", "AMD", "INTC", "META", "GOOGL", "ORCL", "ADBE", "CRM"}
        finance = {"JPM", "V", "MA", "C", "BAC", "WFC", "GS", "MS", "SCHW", "AXP"}
        energy = {"XOM", "CVX", "COP", "SLB", "OXY", "MPC", "PSX", "EOG"}
        health = {"PFE", "JNJ", "MRK", "ABBV", "UNH", "LLY", "AMGN", "GILD"}
        industrial = {"BA", "CAT", "DE", "GE", "HON", "MMM", "UNP", "CSX", "RTX", "LMT"}
        consumer = {"AMZN", "WMT", "KO", "PEP", "NKE", "DIS", "MCD", "SBUX", "TGT", "COST"}
        if symbol in tech:
            return "Technology"
        if symbol in finance:
            return "Financials"
        if symbol in energy:
            return "Energy"
        if symbol in health:
            return "Healthcare"
        if symbol in industrial:
            return "Industrials"
        if symbol in consumer:
            return "Consumer"
        return "Other"

    def get_symbol_chart(self, symbol: str, days: int = 300) -> List[Dict[str, Any]]:
        """Get historical chart with SMA50 and SMA250 overlays."""
        days = max(60, min(730, days))
        if self._data_client and StockBarsRequest and TimeFrame:
            try:
                start = datetime.now() - timedelta(days=days + 30)
                req = StockBarsRequest(
                    symbol_or_symbols=[symbol.upper()],
                    timeframe=TimeFrame.Day,
                    start=start
                )
                bars_resp = self._data_client.get_stock_bars(req)
                bars = []
                if hasattr(bars_resp, "data"):
                    bars = bars_resp.data.get(symbol.upper(), [])
                elif isinstance(bars_resp, dict):
                    bars = bars_resp.get(symbol.upper(), [])
                prices = []
                for bar in bars:
                    close = float(getattr(bar, "close", getattr(bar, "c", 0.0)))
                    high = float(getattr(bar, "high", getattr(bar, "h", close)))
                    low = float(getattr(bar, "low", getattr(bar, "l", close)))
                    if high < low:
                        high, low = low, high
                    ts = getattr(bar, "timestamp", getattr(bar, "t", datetime.now()))
                    prices.append({
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "close": close,
                        "high": high,
                        "low": low,
                    })
                if prices:
                    self._last_source = "alpaca"
                    return self._with_sma(prices)
                if self.require_real_data:
                    raise RuntimeError(f"No Alpaca chart data returned for {symbol.upper()}")
            except Exception as e:
                if self.require_real_data:
                    raise RuntimeError(f"Failed to fetch chart from Alpaca for {symbol.upper()}: {e}") from e
                logger.warning(f"Failed to fetch chart from Alpaca for {symbol}: {e}, using fallback")
        elif self.require_real_data:
            raise RuntimeError("Strict Alpaca data mode is enabled but no Alpaca data client is available")

        # Fallback synthetic series
        self._last_source = "fallback"
        base_price = 100.0
        for item in self._get_fallback_stocks(200) + self._get_fallback_etfs(200):
            if item["symbol"].upper() == symbol.upper():
                base_price = float(item["price"])
                break
        points = []
        now = datetime.now()
        for i in range(days):
            dt = now - timedelta(days=days - i)
            noise = math.sin(i / 7.0) * 0.8 + math.cos(i / 17.0) * 0.4
            trend = (i / max(days, 1)) * 0.05
            close = max(1.0, base_price * (1 + trend + noise / 100.0))
            intraday_range_pct = 0.004 + abs(noise) / 300.0
            high = close * (1.0 + intraday_range_pct)
            low = max(0.01, close * (1.0 - intraday_range_pct))
            points.append({
                "timestamp": dt.isoformat(),
                "close": close,
                "high": high,
                "low": low,
            })
        return self._with_sma(points)

    def get_chart_indicators(
        self,
        points: List[Dict[str, Any]],
        take_profit_pct: float = 5.0,
        trailing_stop_pct: float = 2.5,
        atr_stop_mult: float = 1.8,
        zscore_entry_threshold: float = -1.5,
        dip_buy_threshold_pct: float = 2.0,
    ) -> Dict[str, Any]:
        """Compute minimal high-value chart indicators/monitors."""
        if not points:
            return {}
        normalized_points = []
        for point in points:
            raw_close = point.get("close")
            if raw_close is None:
                continue
            try:
                close = float(raw_close)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(close) or close <= 0:
                continue
            raw_high = point.get("high")
            raw_low = point.get("low")
            high = None
            low = None
            if raw_high is not None:
                try:
                    parsed_high = float(raw_high)
                    if math.isfinite(parsed_high) and parsed_high > 0:
                        high = parsed_high
                except (TypeError, ValueError):
                    high = None
            if raw_low is not None:
                try:
                    parsed_low = float(raw_low)
                    if math.isfinite(parsed_low) and parsed_low > 0:
                        low = parsed_low
                except (TypeError, ValueError):
                    low = None
            normalized_points.append({
                "close": close,
                "high": high,
                "low": low,
                "sma50": point.get("sma50"),
            })

        closes = [point["close"] for point in normalized_points]
        if len(closes) < 2:
            return {}
        latest_close = closes[-1]
        # True ATR(14): TR = max(high-low, |high-prev_close|, |low-prev_close|).
        atr_window = min(14, len(closes) - 1)
        true_ranges = []
        start_idx = len(closes) - atr_window
        for idx in range(start_idx, len(closes)):
            prev_close = closes[idx - 1]
            close = closes[idx]
            high = normalized_points[idx].get("high")
            low = normalized_points[idx].get("low")
            if high is None:
                high = max(close, prev_close)
            if low is None:
                low = min(close, prev_close)
            if high < low:
                high, low = low, high
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            if math.isfinite(tr) and tr >= 0:
                true_ranges.append(tr)
        atr_abs = (sum(true_ranges) / len(true_ranges)) if true_ranges else 0.0
        atr_pct = (atr_abs / latest_close * 100.0) if latest_close > 0 else 0.0

        z_window = min(20, len(closes))
        z_slice = closes[-z_window:]
        z_mean = sum(z_slice) / len(z_slice)
        variance = sum((v - z_mean) ** 2 for v in z_slice) / len(z_slice)
        z_std = variance ** 0.5
        zscore20 = (latest_close - z_mean) / z_std if z_std > 0 else 0.0

        latest_sma50 = normalized_points[-1].get("sma50")
        dip_trigger_price = None
        dip_buy_signal = False
        if latest_sma50:
            dip_trigger_price = float(latest_sma50) * (1.0 - (dip_buy_threshold_pct / 100.0))
            dip_buy_signal = latest_close <= dip_trigger_price and zscore20 <= zscore_entry_threshold

        take_profit_price = latest_close * (1.0 + take_profit_pct / 100.0)
        trailing_peak = max(closes[-20:]) if len(closes) >= 20 else max(closes)
        trailing_stop_price = trailing_peak * (1.0 - trailing_stop_pct / 100.0)
        atr_stop_price = latest_close * (1.0 - (atr_stop_mult * atr_pct / 100.0))

        return {
            "latest_close": round(latest_close, 4),
            "atr14": round(atr_abs, 4),
            "atr14_pct": round(atr_pct, 4),
            "zscore20": round(zscore20, 4),
            "take_profit_price": round(take_profit_price, 4),
            "trailing_stop_price": round(trailing_stop_price, 4),
            "atr_stop_price": round(atr_stop_price, 4),
            "dip_trigger_price": round(dip_trigger_price, 4) if dip_trigger_price is not None else None,
            "dip_buy_signal": dip_buy_signal,
            "zscore_entry_threshold": zscore_entry_threshold,
            "dip_buy_threshold_pct": dip_buy_threshold_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "take_profit_pct": take_profit_pct,
            "atr_stop_mult": atr_stop_mult,
        }

    def _with_sma(self, points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attach SMA50 and SMA250 values to chart points."""
        closes = [p["close"] for p in points]
        result = []
        for idx, p in enumerate(points):
            sma50 = None
            sma250 = None
            if idx >= 49:
                sma50 = sum(closes[idx - 49:idx + 1]) / 50.0
            if idx >= 249:
                sma250 = sum(closes[idx - 249:idx + 1]) / 250.0
            point = {
                "timestamp": p["timestamp"],
                "close": p["close"],
                "sma50": sma50,
                "sma250": sma250,
            }
            if p.get("high") is not None:
                point["high"] = p["high"]
            if p.get("low") is not None:
                point["low"] = p["low"]
            result.append(point)
        return result
    
    def _get_fallback_stocks(self, limit: int) -> List[Dict[str, Any]]:
        """
        Get fallback list of popular stocks.
        
        Returns well-known, liquid stocks when API is unavailable.
        """
        # Popular, liquid stocks sorted roughly by typical volume.
        stock_seed = [
            ("TSLA", "Tesla Inc."), ("AAPL", "Apple Inc."), ("NVDA", "NVIDIA Corp."), ("AMD", "Advanced Micro Devices"),
            ("AMZN", "Amazon.com Inc."), ("MSFT", "Microsoft Corp."), ("META", "Meta Platforms Inc."), ("GOOGL", "Alphabet Inc."),
            ("INTC", "Intel Corp."), ("NFLX", "Netflix Inc."), ("DIS", "Walt Disney Co."), ("BABA", "Alibaba Group"),
            ("BA", "Boeing Co."), ("JPM", "JPMorgan Chase"), ("V", "Visa Inc."), ("WMT", "Walmart Inc."),
            ("PFE", "Pfizer Inc."), ("KO", "Coca-Cola Co."), ("PEP", "PepsiCo Inc."), ("NKE", "Nike Inc."),
            ("CSCO", "Cisco Systems"), ("ADBE", "Adobe Inc."), ("CRM", "Salesforce Inc."), ("ORCL", "Oracle Corp."),
            ("PYPL", "PayPal Holdings"), ("UBER", "Uber Technologies"), ("LYFT", "Lyft Inc."), ("SQ", "Block Inc."),
            ("SHOP", "Shopify Inc."), ("PLTR", "Palantir Technologies"), ("COIN", "Coinbase Global"), ("SNOW", "Snowflake Inc."),
            ("ZM", "Zoom Video"), ("DOCU", "DocuSign Inc."), ("ROKU", "Roku Inc."), ("F", "Ford Motor Co."),
            ("GM", "General Motors"), ("T", "AT&T Inc."), ("VZ", "Verizon Communications"), ("XOM", "Exxon Mobil"),
            ("CVX", "Chevron Corp."), ("COP", "ConocoPhillips"), ("SLB", "Schlumberger"), ("CAT", "Caterpillar Inc."),
            ("DE", "Deere & Co."), ("GE", "GE Aerospace"), ("HON", "Honeywell"), ("MMM", "3M Co."),
            ("IBM", "IBM"), ("QCOM", "Qualcomm"), ("AVGO", "Broadcom"), ("TXN", "Texas Instruments"),
            ("MU", "Micron Technology"), ("AMAT", "Applied Materials"), ("LRCX", "Lam Research"), ("KLAC", "KLA Corp."),
            ("MRVL", "Marvell Technology"), ("ADI", "Analog Devices"), ("MCHP", "Microchip"), ("ON", "ON Semiconductor"),
            ("PANW", "Palo Alto Networks"), ("CRWD", "CrowdStrike"), ("NET", "Cloudflare"), ("DDOG", "Datadog"),
            ("NOW", "ServiceNow"), ("TEAM", "Atlassian"), ("MDB", "MongoDB"), ("ZS", "Zscaler"),
            ("OKTA", "Okta Inc."), ("FTNT", "Fortinet"), ("WDAY", "Workday"), ("INTU", "Intuit"),
            ("ADBE", "Adobe Inc."), ("ANET", "Arista Networks"), ("GILD", "Gilead Sciences"), ("AMGN", "Amgen"),
            ("BIIB", "Biogen"), ("REGN", "Regeneron"), ("LLY", "Eli Lilly"), ("JNJ", "Johnson & Johnson"),
            ("MRK", "Merck & Co."), ("ABBV", "AbbVie"), ("UNH", "UnitedHealth"), ("CVS", "CVS Health"),
            ("COST", "Costco"), ("HD", "Home Depot"), ("LOW", "Lowe's"), ("MCD", "McDonald's"),
            ("SBUX", "Starbucks"), ("CMG", "Chipotle"), ("BKNG", "Booking Holdings"), ("ABNB", "Airbnb"),
            ("DAL", "Delta Air Lines"), ("UAL", "United Airlines"), ("AAL", "American Airlines"), ("MAR", "Marriott"),
            ("HLT", "Hilton"), ("SPOT", "Spotify"), ("SONY", "Sony Group"), ("RBLX", "Roblox"),
            ("EA", "Electronic Arts"), ("TTWO", "Take-Two Interactive"), ("ATVI", "Activision Blizzard"), ("RIOT", "Riot Platforms"),
            ("MARA", "MARA Holdings"), ("SOFI", "SoFi Technologies"), ("HOOD", "Robinhood Markets"), ("C", "Citigroup"),
            ("BAC", "Bank of America"), ("WFC", "Wells Fargo"), ("GS", "Goldman Sachs"), ("MS", "Morgan Stanley"),
            ("SCHW", "Charles Schwab"), ("AXP", "American Express"), ("BLK", "BlackRock"), ("SPGI", "S&P Global"),
            ("ICE", "Intercontinental Exchange"), ("CME", "CME Group"), ("MO", "Altria"), ("PM", "Philip Morris"),
            ("TGT", "Target Corp."), ("DG", "Dollar General"), ("DLTR", "Dollar Tree"), ("KR", "Kroger"),
            ("ELV", "Elevance Health"), ("HUM", "Humana"), ("CI", "Cigna"), ("ETSY", "Etsy"),
            ("PINS", "Pinterest"), ("SNAP", "Snap Inc."), ("TWLO", "Twilio"), ("FSLY", "Fastly"),
            ("CHWY", "Chewy"), ("WBD", "Warner Bros. Discovery"), ("PARA", "Paramount Global"), ("FOXA", "Fox Corp."),
            ("NEM", "Newmont"), ("FCX", "Freeport-McMoRan"), ("NUE", "Nucor"), ("X", "United States Steel"),
            ("CLF", "Cleveland-Cliffs"), ("OXY", "Occidental Petroleum"), ("MPC", "Marathon Petroleum"), ("PSX", "Phillips 66"),
            ("EOG", "EOG Resources"), ("PXD", "Pioneer Natural Resources"), ("KMI", "Kinder Morgan"), ("BKR", "Baker Hughes"),
            ("DOW", "Dow Inc."), ("DD", "DuPont"), ("LIN", "Linde"), ("APD", "Air Products"),
            ("UNP", "Union Pacific"), ("NSC", "Norfolk Southern"), ("CSX", "CSX Corp."), ("UPS", "UPS"),
            ("FDX", "FedEx"), ("RTX", "RTX Corp."), ("LMT", "Lockheed Martin"), ("NOC", "Northrop Grumman"),
            ("GD", "General Dynamics"), ("HII", "Huntington Ingalls"), ("BAH", "Booz Allen Hamilton"), ("PLD", "Prologis"),
            ("AMT", "American Tower"), ("CCI", "Crown Castle"), ("EQIX", "Equinix"), ("SPG", "Simon Property Group"),
            ("O", "Realty Income"), ("WELL", "Welltower"), ("PSA", "Public Storage"), ("EXR", "Extra Space Storage"),
        ]
        popular_stocks = []
        base_volume = 130_000_000
        for idx, (symbol, name) in enumerate(stock_seed):
            popular_stocks.append({
                "symbol": symbol,
                "name": name,
                "volume": max(1_000_000, base_volume - (idx * 700_000)),
                "price": round(20 + ((idx * 7.3) % 580), 2),
                "change_percent": round(((idx % 15) - 7) * 0.22, 2),
            })
        
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
        # Popular, liquid ETFs.
        etf_seed = [
            ("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ Trust"), ("IWM", "iShares Russell 2000 ETF"),
            ("VTI", "Vanguard Total Stock Market ETF"), ("EEM", "iShares MSCI Emerging Markets ETF"), ("GLD", "SPDR Gold Shares"),
            ("XLF", "Financial Select Sector SPDR"), ("XLE", "Energy Select Sector SPDR"), ("XLK", "Technology Select Sector SPDR"),
            ("TLT", "iShares 20+ Year Treasury Bond ETF"), ("VOO", "Vanguard S&P 500 ETF"), ("VEA", "Vanguard FTSE Developed Markets ETF"),
            ("AGG", "iShares Core U.S. Aggregate Bond ETF"), ("VWO", "Vanguard FTSE Emerging Markets ETF"), ("IVV", "iShares Core S&P 500 ETF"),
            ("DIA", "SPDR Dow Jones Industrial Average ETF"), ("XLV", "Health Care Select Sector SPDR"), ("XLI", "Industrial Select Sector SPDR"),
            ("XLP", "Consumer Staples Select Sector SPDR"), ("XLY", "Consumer Discretionary Select Sector SPDR"), ("XLC", "Communication Services Select Sector SPDR"),
            ("XLB", "Materials Select Sector SPDR"), ("XLRE", "Real Estate Select Sector SPDR"), ("XLU", "Utilities Select Sector SPDR"),
            ("SMH", "VanEck Semiconductor ETF"), ("SOXX", "iShares Semiconductor ETF"), ("ARKK", "ARK Innovation ETF"),
            ("ARKQ", "ARK Autonomous Tech ETF"), ("ARKG", "ARK Genomic Revolution ETF"), ("ARKW", "ARK Next Generation Internet ETF"),
            ("HYG", "iShares iBoxx High Yield Corporate Bond ETF"), ("LQD", "iShares iBoxx Investment Grade Corporate Bond ETF"),
            ("BND", "Vanguard Total Bond Market ETF"), ("IEF", "iShares 7-10 Year Treasury Bond ETF"), ("SHY", "iShares 1-3 Year Treasury Bond ETF"),
            ("TIP", "iShares TIPS Bond ETF"), ("VNQ", "Vanguard Real Estate ETF"), ("IYR", "iShares U.S. Real Estate ETF"),
            ("GDX", "VanEck Gold Miners ETF"), ("SLV", "iShares Silver Trust"), ("USO", "United States Oil Fund"),
            ("UNG", "United States Natural Gas Fund"), ("DBC", "Invesco DB Commodity Index Tracking Fund"), ("KRE", "SPDR S&P Regional Banking ETF"),
            ("XBI", "SPDR S&P Biotech ETF"), ("IBB", "iShares Biotechnology ETF"), ("ICLN", "iShares Global Clean Energy ETF"),
            ("TAN", "Invesco Solar ETF"), ("PBW", "Invesco WilderHill Clean Energy ETF"), ("JETS", "U.S. Global Jets ETF"),
            ("ITA", "iShares U.S. Aerospace & Defense ETF"), ("PAVE", "Global X U.S. Infrastructure Development ETF"), ("BOTZ", "Global X Robotics & Artificial Intelligence ETF"),
            ("ROBO", "ROBO Global Robotics and Automation Index ETF"), ("CLOU", "Global X Cloud Computing ETF"), ("SKYY", "First Trust Cloud Computing ETF"),
            ("FINX", "Global X FinTech ETF"), ("KWEB", "KraneShares CSI China Internet ETF"), ("FXI", "iShares China Large-Cap ETF"),
            ("EWJ", "iShares MSCI Japan ETF"), ("EWZ", "iShares MSCI Brazil ETF"), ("EFA", "iShares MSCI EAFE ETF"),
            ("SCHD", "Schwab U.S. Dividend Equity ETF"), ("VIG", "Vanguard Dividend Appreciation ETF"), ("DVY", "iShares Select Dividend ETF"),
            ("SPLV", "Invesco S&P 500 Low Volatility ETF"), ("SPHD", "Invesco S&P 500 High Dividend Low Volatility ETF"), ("RSP", "Invesco S&P 500 Equal Weight ETF"),
            ("MTUM", "iShares MSCI USA Momentum Factor ETF"), ("QUAL", "iShares MSCI USA Quality Factor ETF"), ("USMV", "iShares MSCI USA Min Vol Factor ETF"),
            ("EFAV", "iShares MSCI EAFE Min Vol Factor ETF"), ("VTV", "Vanguard Value ETF"), ("VUG", "Vanguard Growth ETF"),
            ("IWF", "iShares Russell 1000 Growth ETF"), ("IWD", "iShares Russell 1000 Value ETF"), ("MDY", "SPDR S&P MidCap 400 ETF"),
            ("IJH", "iShares Core S&P Mid-Cap ETF"), ("IJR", "iShares Core S&P Small-Cap ETF"), ("VB", "Vanguard Small-Cap ETF"),
            ("SCHA", "Schwab U.S. Small-Cap ETF"), ("SCHF", "Schwab International Equity ETF"), ("SCHX", "Schwab U.S. Large-Cap ETF"),
            ("SCHB", "Schwab U.S. Broad Market ETF"), ("ACWI", "iShares MSCI ACWI ETF"), ("VT", "Vanguard Total World Stock ETF"),
            ("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF"), ("SGOV", "iShares 0-3 Month Treasury Bond ETF"), ("VGSH", "Vanguard Short-Term Treasury ETF"),
            ("VCSH", "Vanguard Short-Term Corporate Bond ETF"), ("BSV", "Vanguard Short-Term Bond ETF"), ("MUB", "iShares National Muni Bond ETF"),
            ("EMB", "iShares J.P. Morgan USD Emerging Markets Bond ETF"), ("PFF", "iShares Preferred and Income Securities ETF"),
        ]
        popular_etfs = []
        base_volume = 90_000_000
        for idx, (symbol, name) in enumerate(etf_seed):
            popular_etfs.append({
                "symbol": symbol,
                "name": name,
                "volume": max(800_000, base_volume - (idx * 550_000)),
                "price": round(25 + ((idx * 5.8) % 460), 2),
                "change_percent": round(((idx % 13) - 6) * 0.18, 2),
            })
        
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
