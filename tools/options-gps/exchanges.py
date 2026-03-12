"""
Multi-exchange price comparison for Options GPS Market Line Shopping.

Compares Synth's theoretical option prices against exchange prices
(Aevo, Deribit, etc.) to identify divergence — like shopping for lines.

Three modes of operation:
1. LIVE — when exchange API keys are present, fetches real-time quotes
   via public REST endpoints and uses them for comparison.
2. PARTIAL — some live providers succeeded, some fell back to mock.
3. MOCK — no API keys configured; uses mock providers for demonstration.

Edge detection philosophy: alpha is found in *disagreement*, not consensus.
When Synth's theoretical prices diverge from the market mean, it signals
a potential exploitable edge. This is quantified via z-scores:
  z = (synth_price - market_mean) / market_stddev
"""

from __future__ import annotations

import logging
import math
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DivergenceSummary:
    """Per-exchange divergence metrics vs Synth fair value."""
    exchange: str
    avg_abs_div: float   # average absolute % divergence across all strikes
    max_abs_div: float   # maximum absolute % divergence
    rich_calls: float    # signed avg divergence for calls (+ = exchange richer)
    rich_puts: float     # signed avg divergence for puts  (+ = exchange richer)
    n_strikes: int       # number of strikes compared


@dataclass
class StrikeEdge:
    """Z-score edge signal for a single strike."""
    strike: str
    option_type: str        # "call" or "put"
    synth_price: float
    market_mean: float
    market_std: float
    z_score: float          # (synth - mean) / std; positive = Synth overvalues
    prices: dict[str, float]  # exchange_name -> price


@dataclass
class BestVenueInfo:
    """Best execution venue for a specific option leg."""
    strike: float
    option_type: str        # "Call" or "Put"
    action: str             # "BUY" or "SELL"
    best_exchange: str
    best_price: float
    synth_price: float
    savings_vs_synth: float  # positive = better than Synth
    all_prices: dict[str, float]


MarketConsensus = Literal["strong_agreement", "moderate_agreement", "weak_agreement", "disagreement"]


@dataclass
class MarketLineResult:
    """Aggregated result across all exchanges."""
    summaries: list[DivergenceSummary]
    avg_divergence: float
    max_divergence: float
    consensus: MarketConsensus
    edge_score: float = 0.0                        # average |z-score| across strikes
    strike_edges: list[StrikeEdge] = field(default_factory=list)
    best_venues: list[BestVenueInfo] = field(default_factory=list)
    data_source: str = "mock"                      # "live", "partial", or "mock"
    exchange_prices: dict = field(default_factory=dict)  # {name: {call_options, put_options}}


# ---------------------------------------------------------------------------
# Exchange Provider ABC
# ---------------------------------------------------------------------------

class ExchangeProvider(ABC):
    """Base class for exchange option price providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def get_option_prices(self, asset: str, synth_options: dict) -> dict:
        """Return option prices in same format as Synth:
        {call_options: {strike: price}, put_options: {strike: price}}.
        synth_options is passed so mock providers can perturb from it."""
        ...

    @property
    def is_live(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Live Deribit Provider
# ---------------------------------------------------------------------------

class LiveDeribitProvider(ExchangeProvider):
    """Fetches real-time option mark prices from Deribit public API.

    Uses public/get_book_summary_by_currency (no auth needed for market data).
    Deribit option prices are quoted in the base currency (e.g. BTC), so they
    are converted to USD using the underlying_price field.
    """

    BASE_URL = "https://www.deribit.com/api/v2"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret

    @property
    def name(self) -> str:
        return "Deribit"

    @property
    def is_live(self) -> bool:
        return True

    def get_option_prices(self, asset: str, synth_options: dict) -> dict:
        currency = asset.upper()
        if currency not in ("BTC", "ETH", "SOL"):
            return {"call_options": {}, "put_options": {}}

        resp = requests.get(
            f"{self.BASE_URL}/public/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        if not results:
            return {"call_options": {}, "put_options": {}}

        synth_strikes = set(
            str(k) for k in (synth_options.get("call_options") or {}).keys()
        )

        # Parse instruments — naming: BTC-28MAR25-90000-C
        by_expiry: dict[str, list[dict]] = {}
        for item in results:
            iname = item.get("instrument_name", "")
            mark = item.get("mark_price")
            underlying = item.get("underlying_price", 0)
            if mark is None or not underlying or float(underlying) <= 0:
                continue
            parts = iname.split("-")
            if len(parts) != 4:
                continue
            _, expiry_str, strike_str, opt_type = parts
            usd_price = float(mark) * float(underlying)
            by_expiry.setdefault(expiry_str, []).append({
                "strike": strike_str,
                "type": opt_type,
                "usd_price": usd_price,
            })

        if not by_expiry:
            return {"call_options": {}, "put_options": {}}

        # Pick expiry with the most overlap with Synth strikes
        best_expiry = max(
            by_expiry,
            key=lambda e: sum(
                1 for p in by_expiry[e]
                if str(int(float(p["strike"]))) in synth_strikes
            ),
        )

        calls: dict[str, float] = {}
        puts: dict[str, float] = {}
        for p in by_expiry[best_expiry]:
            strike_key = str(int(float(p["strike"])))
            if p["type"] == "C":
                calls[strike_key] = round(p["usd_price"], 2)
            else:
                puts[strike_key] = round(p["usd_price"], 2)

        return {"call_options": calls, "put_options": puts}


# ---------------------------------------------------------------------------
# Live Aevo Provider
# ---------------------------------------------------------------------------

class LiveAevoProvider(ExchangeProvider):
    """Fetches real-time option prices from Aevo public REST API.

    Uses GET /markets?asset=X&instrument_type=OPTION.
    """

    BASE_URL = "https://api.aevo.xyz"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Aevo"

    @property
    def is_live(self) -> bool:
        return True

    def get_option_prices(self, asset: str, synth_options: dict) -> dict:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        resp = requests.get(
            f"{self.BASE_URL}/markets",
            params={"asset": asset.upper(), "instrument_type": "OPTION"},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
        if not isinstance(markets, list) or not markets:
            return {"call_options": {}, "put_options": {}}

        synth_strikes = set(
            str(k) for k in (synth_options.get("call_options") or {}).keys()
        )

        calls: dict[str, float] = {}
        puts: dict[str, float] = {}
        for market in markets:
            iname = str(
                market.get("instrument_name")
                or market.get("instrument_id", "")
            )
            mark_price = market.get("mark_price")
            if not mark_price:
                continue
            parts = iname.split("-")
            if len(parts) < 4:
                continue
            strike_str, opt_type = parts[-2], parts[-1].upper()
            try:
                strike_key = str(int(float(strike_str)))
                price = float(mark_price)
            except (ValueError, TypeError):
                continue
            if strike_key not in synth_strikes:
                continue
            if opt_type == "C":
                calls[strike_key] = round(price, 2)
            elif opt_type == "P":
                puts[strike_key] = round(price, 2)

        return {"call_options": calls, "put_options": puts}


# ---------------------------------------------------------------------------
# Mock Provider
# ---------------------------------------------------------------------------

class MockExchangeProvider(ExchangeProvider):
    """Mock provider that perturbs Synth prices with a configurable bias profile."""

    def __init__(self, exchange_name: str, call_bias: float, put_bias: float, noise_scale: float, seed: int):
        self._name = exchange_name
        self._call_bias = call_bias
        self._put_bias = put_bias
        self._noise_scale = noise_scale
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return self._name

    def get_option_prices(self, asset: str, synth_options: dict) -> dict:
        return {
            "call_options": self._perturb(synth_options.get("call_options") or {}, self._call_bias),
            "put_options": self._perturb(synth_options.get("put_options") or {}, self._put_bias),
        }

    def _perturb(self, prices: dict, bias: float) -> dict:
        result = {}
        for strike, price in prices.items():
            price_f = float(price)
            if price_f <= 0:
                result[strike] = price_f
                continue
            noise = self._rng.gauss(0, self._noise_scale)
            factor = 1.0 + bias + noise
            result[strike] = round(max(0.01, price_f * factor), 2)
        return result


# ---------------------------------------------------------------------------
# Divergence computation
# ---------------------------------------------------------------------------

def compute_divergence(synth_options: dict, exchange_prices: dict, exchange_name: str) -> DivergenceSummary | None:
    """Compute divergence between Synth fair prices and one exchange's prices.
    Returns None if inputs are invalid or have no overlapping strikes."""
    synth_calls = {str(k): float(v) for k, v in (synth_options.get("call_options") or {}).items()}
    synth_puts = {str(k): float(v) for k, v in (synth_options.get("put_options") or {}).items()}
    ex_calls = {str(k): float(v) for k, v in (exchange_prices.get("call_options") or {}).items()}
    ex_puts = {str(k): float(v) for k, v in (exchange_prices.get("put_options") or {}).items()}

    call_divs: list[float] = []
    put_divs: list[float] = []

    for strike in synth_calls:
        synth_p = synth_calls[strike]
        ex_p = ex_calls.get(strike)
        if ex_p is not None and synth_p > 0:
            call_divs.append((ex_p - synth_p) / synth_p * 100)

    for strike in synth_puts:
        synth_p = synth_puts[strike]
        ex_p = ex_puts.get(strike)
        if ex_p is not None and synth_p > 0:
            put_divs.append((ex_p - synth_p) / synth_p * 100)

    all_divs = call_divs + put_divs
    if not all_divs:
        return None

    avg_abs = sum(abs(d) for d in all_divs) / len(all_divs)
    max_abs = max(abs(d) for d in all_divs)
    rich_calls = sum(call_divs) / len(call_divs) if call_divs else 0.0
    rich_puts = sum(put_divs) / len(put_divs) if put_divs else 0.0

    return DivergenceSummary(
        exchange=exchange_name,
        avg_abs_div=round(avg_abs, 2),
        max_abs_div=round(max_abs, 2),
        rich_calls=round(rich_calls, 2),
        rich_puts=round(rich_puts, 2),
        n_strikes=len(all_divs),
    )


# ---------------------------------------------------------------------------
# Z-score edge detection
# ---------------------------------------------------------------------------

def compute_edge_zscores(synth_options: dict, all_exchange_prices: dict[str, dict]) -> list[StrikeEdge]:
    """Compute z-score of Synth price vs market mean/stddev per strike.

    Alpha is in disagreement: higher |z| = Synth deviates more from market
    consensus = bigger potential edge.
      z > 0 → Synth overvalues vs market (sell opportunity on exchange)
      z < 0 → Synth undervalues vs market (buy opportunity on exchange)
    """
    edges: list[StrikeEdge] = []

    for opt_type, key in [("call", "call_options"), ("put", "put_options")]:
        synth_prices = {str(k): float(v) for k, v in (synth_options.get(key) or {}).items()}

        for strike, synth_p in synth_prices.items():
            if synth_p <= 0:
                continue

            ex_prices: dict[str, float] = {}
            for ex_name, ex_data in all_exchange_prices.items():
                ex_opts = {str(k): float(v) for k, v in (ex_data.get(key) or {}).items()}
                if strike in ex_opts and ex_opts[strike] > 0:
                    ex_prices[ex_name] = ex_opts[strike]

            if len(ex_prices) < 2:
                continue

            prices = list(ex_prices.values())
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            std = math.sqrt(variance) if variance > 0 else 0.0

            if std > 0:
                z = (synth_p - mean) / std
            else:
                # All exchanges agree — use 1% of mean as floor to avoid infinity
                pseudo_std = mean * 0.01 if mean > 0 else 1.0
                z = (synth_p - mean) / pseudo_std

            edges.append(StrikeEdge(
                strike=strike,
                option_type=opt_type,
                synth_price=round(synth_p, 2),
                market_mean=round(mean, 2),
                market_std=round(std, 2),
                z_score=round(z, 2),
                prices={k: round(v, 2) for k, v in ex_prices.items()},
            ))

    return edges


# ---------------------------------------------------------------------------
# Best venue identification
# ---------------------------------------------------------------------------

def find_best_venues(synth_options: dict, all_exchange_prices: dict[str, dict],
                     strategy_legs: list | None = None) -> list[BestVenueInfo]:
    """Identify which exchange offers the best execution price per option leg.

    For BUY legs: lowest exchange price wins.
    For SELL legs: highest exchange price wins.

    If strategy_legs is provided, only evaluates those specific legs.
    Otherwise evaluates all strikes as BUY legs.
    """
    venues: list[BestVenueInfo] = []

    if strategy_legs:
        for leg in strategy_legs:
            action = leg.action if hasattr(leg, "action") else leg.get("action", "BUY")
            strike = str(int(float(
                leg.strike if hasattr(leg, "strike") else leg.get("strike", 0)
            )))
            opt_type = leg.option_type if hasattr(leg, "option_type") else leg.get("option_type", "Call")
            key = "call_options" if opt_type == "Call" else "put_options"

            synth_p = float((synth_options.get(key) or {}).get(strike, 0))

            ex_prices: dict[str, float] = {}
            for ex_name, ex_data in all_exchange_prices.items():
                p = float((ex_data.get(key) or {}).get(strike, 0))
                if p > 0:
                    ex_prices[ex_name] = p

            if not ex_prices:
                continue

            if action == "BUY":
                best_ex = min(ex_prices, key=lambda k: ex_prices[k])
            else:
                best_ex = max(ex_prices, key=lambda k: ex_prices[k])

            best_p = ex_prices[best_ex]
            savings = (synth_p - best_p) if action == "BUY" else (best_p - synth_p)

            venues.append(BestVenueInfo(
                strike=float(strike),
                option_type=opt_type,
                action=action,
                best_exchange=best_ex,
                best_price=round(best_p, 2),
                synth_price=round(synth_p, 2),
                savings_vs_synth=round(savings, 2),
                all_prices={k: round(v, 2) for k, v in ex_prices.items()},
            ))

    return venues


# ---------------------------------------------------------------------------
# Consensus classification
# ---------------------------------------------------------------------------

def _classify_consensus(avg_div: float) -> MarketConsensus:
    if avg_div < 3.0:
        return "strong_agreement"
    if avg_div < 7.0:
        return "moderate_agreement"
    if avg_div < 15.0:
        return "weak_agreement"
    return "disagreement"


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def _default_providers() -> tuple[list[ExchangeProvider], str]:
    """Create exchange providers.  Returns (providers, data_source).

    Uses live adapters when API keys / credentials are configured;
    falls back to mock providers otherwise.
    """
    providers: list[ExchangeProvider] = []
    data_source = "mock"

    deribit_id = os.environ.get("DERIBIT_CLIENT_ID", "")
    deribit_secret = os.environ.get("DERIBIT_CLIENT_SECRET", "")
    aevo_key = os.environ.get("AEVO_API_KEY", "")

    if deribit_id and deribit_secret:
        providers.append(LiveDeribitProvider(deribit_id, deribit_secret))
        data_source = "live"
    if aevo_key:
        providers.append(LiveAevoProvider(aevo_key))
        data_source = "live"

    if not providers:
        providers = [
            MockExchangeProvider("Aevo", call_bias=0.03, put_bias=-0.02, noise_scale=0.02, seed=42),
            MockExchangeProvider("Deribit", call_bias=-0.01, put_bias=0.01, noise_scale=0.04, seed=137),
            MockExchangeProvider("OKX", call_bias=-0.02, put_bias=0.03, noise_scale=0.025, seed=271),
        ]

    return providers, data_source


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_market_lines(synth_options: dict, asset: str = "BTC",
                     providers: list[ExchangeProvider] | None = None,
                     strategy_legs: list | None = None) -> MarketLineResult:
    """Fetch prices from all exchanges and compute divergence, z-scores, and best venues."""
    if providers is not None:
        active_providers = providers
        data_source = "live" if any(p.is_live for p in providers) else "mock"
    else:
        active_providers, data_source = _default_providers()

    empty = MarketLineResult(
        summaries=[], avg_divergence=0.0, max_divergence=0.0,
        consensus="disagreement", data_source=data_source,
    )

    current_price = float(synth_options.get("current_price", 0))
    if current_price <= 0 or not synth_options.get("call_options"):
        return empty

    summaries: list[DivergenceSummary] = []
    all_exchange_prices: dict[str, dict] = {}
    live_failed = False

    for provider in active_providers:
        try:
            ex_prices = provider.get_option_prices(asset, synth_options)
            all_exchange_prices[provider.name] = ex_prices
            summary = compute_divergence(synth_options, ex_prices, provider.name)
            if summary is not None:
                summaries.append(summary)
        except Exception as exc:
            logger.warning("Exchange %s failed: %s", provider.name, exc)
            if provider.is_live:
                live_failed = True
            continue

    if live_failed and data_source == "live":
        data_source = "partial"

    if not summaries:
        return empty

    avg_div = sum(s.avg_abs_div for s in summaries) / len(summaries)
    max_div = max(s.max_abs_div for s in summaries)
    consensus = _classify_consensus(avg_div)

    strike_edges = compute_edge_zscores(synth_options, all_exchange_prices)
    edge_score = (
        sum(abs(e.z_score) for e in strike_edges) / len(strike_edges)
    ) if strike_edges else 0.0

    best_venues = find_best_venues(synth_options, all_exchange_prices, strategy_legs)

    return MarketLineResult(
        summaries=summaries,
        avg_divergence=round(avg_div, 2),
        max_divergence=round(max_div, 2),
        consensus=consensus,
        edge_score=round(edge_score, 2),
        strike_edges=strike_edges,
        best_venues=best_venues,
        data_source=data_source,
        exchange_prices=all_exchange_prices,
    )
