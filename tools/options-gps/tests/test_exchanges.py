"""Tests for multi-exchange market line shopping (issue #32)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exchanges import (
    compute_divergence,
    compute_edge_zscores,
    find_best_venues,
    get_market_lines,
    MockExchangeProvider,
    LiveDeribitProvider,
    LiveAevoProvider,
    MarketLineResult,
    _classify_consensus,
    _default_providers,
)
from pipeline import (
    adjust_confidence_for_divergence,
    forecast_confidence,
)

SYNTH_OPTIONS = {
    "current_price": 67723,
    "call_options": {
        "66500": 1400, "67000": 987, "67500": 640,
        "68000": 373, "68500": 197, "69000": 90,
    },
    "put_options": {
        "66500": 57, "67000": 140, "67500": 291,
        "68000": 526, "68500": 850, "69000": 1200,
    },
}

P24H = {
    "0.05": 66000, "0.2": 67000, "0.35": 67400,
    "0.5": 67800, "0.65": 68200, "0.8": 68800, "0.95": 70000,
}


# ── compute_divergence ──────────────────────────────────────────

def test_divergence_identical_prices():
    """Zero divergence when exchange prices match Synth exactly."""
    ex_prices = {
        "call_options": dict(SYNTH_OPTIONS["call_options"]),
        "put_options": dict(SYNTH_OPTIONS["put_options"]),
    }
    result = compute_divergence(SYNTH_OPTIONS, ex_prices, "TestExchange")
    assert result is not None
    assert result.avg_abs_div == 0.0
    assert result.max_abs_div == 0.0
    assert result.rich_calls == 0.0
    assert result.rich_puts == 0.0
    assert result.n_strikes == 12  # 6 calls + 6 puts


def test_divergence_uniformly_rich():
    """Exchange prices 10% above Synth -> positive divergence."""
    ex_prices = {
        "call_options": {k: float(v) * 1.10 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 1.10 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    result = compute_divergence(SYNTH_OPTIONS, ex_prices, "RichExchange")
    assert result is not None
    assert abs(result.avg_abs_div - 10.0) < 0.5
    assert result.rich_calls > 0
    assert result.rich_puts > 0


def test_divergence_uniformly_cheap():
    """Exchange prices 5% below Synth -> negative signed divergence."""
    ex_prices = {
        "call_options": {k: float(v) * 0.95 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 0.95 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    result = compute_divergence(SYNTH_OPTIONS, ex_prices, "CheapExchange")
    assert result is not None
    assert abs(result.avg_abs_div - 5.0) < 0.5
    assert result.rich_calls < 0
    assert result.rich_puts < 0


def test_divergence_empty_exchange_prices():
    """No overlapping strikes -> None."""
    result = compute_divergence(SYNTH_OPTIONS, {"call_options": {}, "put_options": {}}, "Empty")
    assert result is None


def test_divergence_zero_synth_prices():
    """Synth prices at zero are skipped (no division by zero)."""
    opts = {
        "current_price": 100,
        "call_options": {"100": 0, "110": 10},
        "put_options": {"90": 0, "100": 10},
    }
    ex = {"call_options": {"100": 5, "110": 12}, "put_options": {"90": 3, "100": 11}}
    result = compute_divergence(opts, ex, "ZeroTest")
    assert result is not None
    assert result.n_strikes == 2  # only the non-zero synth prices


def test_divergence_partial_overlap():
    """Exchange has only some strikes."""
    ex_prices = {
        "call_options": {"67000": 1000},  # only 1 of 6 call strikes
        "put_options": {"68000": 500},     # only 1 of 6 put strikes
    }
    result = compute_divergence(SYNTH_OPTIONS, ex_prices, "Partial")
    assert result is not None
    assert result.n_strikes == 2


# ── MockExchangeProvider ────────────────────────────────────────

def test_mock_provider_returns_all_strikes():
    """Mock provider should return prices for every strike in Synth data."""
    provider = MockExchangeProvider("Test", call_bias=0.0, put_bias=0.0, noise_scale=0.0, seed=0)
    prices = provider.get_option_prices("BTC", SYNTH_OPTIONS)
    assert set(prices["call_options"].keys()) == set(SYNTH_OPTIONS["call_options"].keys())
    assert set(prices["put_options"].keys()) == set(SYNTH_OPTIONS["put_options"].keys())


def test_mock_provider_zero_noise_matches_bias():
    """With zero noise, divergence should equal the bias exactly."""
    provider = MockExchangeProvider("Exact", call_bias=0.05, put_bias=-0.03, noise_scale=0.0, seed=0)
    prices = provider.get_option_prices("BTC", SYNTH_OPTIONS)
    for strike, synth_price in SYNTH_OPTIONS["call_options"].items():
        synth_f = float(synth_price)
        ex_f = float(prices["call_options"][strike])
        assert abs(ex_f - synth_f * 1.05) < 0.02, f"Call {strike}: expected {synth_f * 1.05}, got {ex_f}"


def test_mock_provider_deterministic():
    """Same seed should produce identical prices."""
    p1 = MockExchangeProvider("A", 0.01, -0.01, 0.03, seed=99)
    p2 = MockExchangeProvider("B", 0.01, -0.01, 0.03, seed=99)
    prices1 = p1.get_option_prices("BTC", SYNTH_OPTIONS)
    prices2 = p2.get_option_prices("BTC", SYNTH_OPTIONS)
    assert prices1 == prices2


def test_mock_provider_positive_prices():
    """All mock prices should be > 0."""
    provider = MockExchangeProvider("Floor", call_bias=-0.5, put_bias=-0.5, noise_scale=0.1, seed=42)
    prices = provider.get_option_prices("BTC", SYNTH_OPTIONS)
    for k, v in prices["call_options"].items():
        assert v > 0, f"Call {k} has non-positive price {v}"
    for k, v in prices["put_options"].items():
        assert v > 0, f"Put {k} has non-positive price {v}"


def test_mock_provider_is_not_live():
    """Mock providers report is_live=False."""
    p = MockExchangeProvider("Test", 0, 0, 0, seed=0)
    assert p.is_live is False


# ── Live provider properties ────────────────────────────────────

def test_live_deribit_provider_is_live():
    p = LiveDeribitProvider("id", "secret")
    assert p.is_live is True
    assert p.name == "Deribit"


def test_live_aevo_provider_is_live():
    p = LiveAevoProvider("key")
    assert p.is_live is True
    assert p.name == "Aevo"


# ── _classify_consensus ────────────────────────────────────────

def test_consensus_classification():
    assert _classify_consensus(1.0) == "strong_agreement"
    assert _classify_consensus(2.9) == "strong_agreement"
    assert _classify_consensus(3.0) == "moderate_agreement"
    assert _classify_consensus(6.9) == "moderate_agreement"
    assert _classify_consensus(7.0) == "weak_agreement"
    assert _classify_consensus(14.9) == "weak_agreement"
    assert _classify_consensus(15.0) == "disagreement"
    assert _classify_consensus(50.0) == "disagreement"


# ── Z-score edge detection ──────────────────────────────────────

def test_edge_zscores_basic():
    """Z-scores computed correctly when Synth diverges from exchange mean."""
    # Two exchanges: one 10% above Synth, one 10% below → mean ≈ Synth, small z
    ex_high = {
        "call_options": {k: float(v) * 1.10 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 1.10 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    ex_low = {
        "call_options": {k: float(v) * 0.90 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 0.90 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    edges = compute_edge_zscores(SYNTH_OPTIONS, {"ExHigh": ex_high, "ExLow": ex_low})
    assert len(edges) == 12  # 6 calls + 6 puts
    for e in edges:
        # Mean of high+low = Synth, so z ≈ 0
        assert abs(e.z_score) < 0.5


def test_edge_zscores_synth_overvalued():
    """When both exchanges price below Synth, z-scores should be positive."""
    ex_a = {
        "call_options": {k: float(v) * 0.80 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 0.80 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    ex_b = {
        "call_options": {k: float(v) * 0.85 for k, v in SYNTH_OPTIONS["call_options"].items()},
        "put_options": {k: float(v) * 0.85 for k, v in SYNTH_OPTIONS["put_options"].items()},
    }
    edges = compute_edge_zscores(SYNTH_OPTIONS, {"A": ex_a, "B": ex_b})
    for e in edges:
        assert e.z_score > 0, f"Expected positive z for overvalued Synth, got {e.z_score}"


def test_edge_zscores_needs_two_exchanges():
    """Single exchange → no z-scores (need at least 2 for stddev)."""
    ex = {
        "call_options": dict(SYNTH_OPTIONS["call_options"]),
        "put_options": dict(SYNTH_OPTIONS["put_options"]),
    }
    edges = compute_edge_zscores(SYNTH_OPTIONS, {"Only": ex})
    assert edges == []


def test_edge_zscores_zero_std_uses_pseudo():
    """When all exchanges agree perfectly, uses pseudo-std (1% of mean)."""
    ex_a = {
        "call_options": {"67000": 1000.0},
        "put_options": {},
    }
    ex_b = {
        "call_options": {"67000": 1000.0},  # identical
        "put_options": {},
    }
    synth = {"current_price": 67000, "call_options": {"67000": 950.0}, "put_options": {}}
    edges = compute_edge_zscores(synth, {"A": ex_a, "B": ex_b})
    assert len(edges) == 1
    # std = 0 → pseudo_std = 1000 * 0.01 = 10, z = (950 - 1000) / 10 = -5.0
    assert abs(edges[0].z_score - (-5.0)) < 0.01


# ── Best venue identification ───────────────────────────────────

def test_best_venue_buy_cheapest():
    """For BUY, the exchange with the lowest price wins."""
    ex_prices = {
        "Aevo": {"call_options": {"67500": 650.0}, "put_options": {}},
        "Deribit": {"call_options": {"67500": 620.0}, "put_options": {}},
    }
    legs = [{"action": "BUY", "strike": 67500, "option_type": "Call"}]
    venues = find_best_venues(SYNTH_OPTIONS, ex_prices, legs)
    assert len(venues) == 1
    assert venues[0].best_exchange == "Deribit"
    assert venues[0].best_price == 620.0


def test_best_venue_sell_highest():
    """For SELL, the exchange with the highest price wins."""
    ex_prices = {
        "Aevo": {"put_options": {"68000": 530.0}, "call_options": {}},
        "Deribit": {"put_options": {"68000": 510.0}, "call_options": {}},
    }
    legs = [{"action": "SELL", "strike": 68000, "option_type": "Put"}]
    venues = find_best_venues(SYNTH_OPTIONS, ex_prices, legs)
    assert len(venues) == 1
    assert venues[0].best_exchange == "Aevo"
    assert venues[0].best_price == 530.0


def test_best_venue_savings_positive_when_better():
    """Savings > 0 when best venue price beats Synth."""
    ex_prices = {
        "Aevo": {"call_options": {"67500": 600.0}, "put_options": {}},
        "Deribit": {"call_options": {"67500": 610.0}, "put_options": {}},
    }
    legs = [{"action": "BUY", "strike": 67500, "option_type": "Call"}]
    venues = find_best_venues(SYNTH_OPTIONS, ex_prices, legs)
    assert len(venues) == 1
    # Synth call 67500 = 640, best = 600 → savings = 640 - 600 = 40
    assert venues[0].savings_vs_synth == 40.0


def test_best_venue_no_legs_returns_empty():
    """No strategy legs → no best venues."""
    venues = find_best_venues(SYNTH_OPTIONS, {}, [])
    assert venues == []
    venues2 = find_best_venues(SYNTH_OPTIONS, {}, None)
    assert venues2 == []


# ── get_market_lines ────────────────────────────────────────────

def test_market_lines_default_providers():
    """Full pipeline with default mock providers returns valid result."""
    result = get_market_lines(SYNTH_OPTIONS, asset="BTC")
    assert isinstance(result, MarketLineResult)
    assert len(result.summaries) == 3  # Aevo, Deribit, OKX
    assert result.avg_divergence > 0
    assert result.max_divergence >= result.avg_divergence
    assert result.consensus in ("strong_agreement", "moderate_agreement", "weak_agreement", "disagreement")
    assert result.data_source == "mock"
    assert result.edge_score >= 0
    assert len(result.strike_edges) > 0
    assert len(result.exchange_prices) == 3
    for s in result.summaries:
        assert s.n_strikes == 12
        assert s.avg_abs_div >= 0
        assert s.max_abs_div >= s.avg_abs_div


def test_market_lines_empty_options():
    """Empty option data returns safe empty result."""
    result = get_market_lines({"current_price": 0, "call_options": {}, "put_options": {}})
    assert result.summaries == []
    assert result.avg_divergence == 0.0
    assert result.consensus == "disagreement"


def test_market_lines_custom_providers():
    """Custom provider list is respected."""
    tight = MockExchangeProvider("Tight", call_bias=0.0, put_bias=0.0, noise_scale=0.001, seed=1)
    result = get_market_lines(SYNTH_OPTIONS, providers=[tight])
    assert len(result.summaries) == 1
    assert result.summaries[0].exchange == "Tight"
    assert result.summaries[0].avg_abs_div < 1.0  # very tight


def test_market_lines_failing_provider():
    """A provider that raises should be skipped, not crash the pipeline."""
    class BrokenProvider:
        name = "Broken"
        is_live = False
        def get_option_prices(self, asset, synth_options):
            raise ConnectionError("simulated failure")
    good = MockExchangeProvider("Good", 0.0, 0.0, 0.01, seed=1)
    result = get_market_lines(SYNTH_OPTIONS, providers=[BrokenProvider(), good])
    assert len(result.summaries) == 1
    assert result.summaries[0].exchange == "Good"


def test_market_lines_live_failure_sets_partial():
    """A live provider that fails sets data_source to 'partial'."""
    class FailingLive:
        name = "FailLive"
        is_live = True
        def get_option_prices(self, asset, synth_options):
            raise ConnectionError("network down")
    good = MockExchangeProvider("Good", 0.0, 0.0, 0.01, seed=1)
    result = get_market_lines(SYNTH_OPTIONS, providers=[FailingLive(), good])
    assert result.data_source == "partial"
    assert len(result.summaries) == 1


# ── adjust_confidence_for_divergence (edge-based) ───────────────

def test_confidence_strong_edge():
    """edge_score >= 2.0 → +0.10 (strong alpha signal)."""
    adjusted = adjust_confidence_for_divergence(0.5, 2.5, "disagreement")
    assert abs(adjusted - 0.60) < 1e-9


def test_confidence_moderate_edge():
    """edge_score >= 1.0 → +0.06."""
    adjusted = adjust_confidence_for_divergence(0.5, 1.5, "weak_agreement")
    assert abs(adjusted - 0.56) < 1e-9


def test_confidence_mild_edge():
    """edge_score >= 0.5 → +0.03."""
    adjusted = adjust_confidence_for_divergence(0.5, 0.7, "moderate_agreement")
    assert abs(adjusted - 0.53) < 1e-9


def test_confidence_no_edge():
    """edge_score < 0.5 → -0.02 (agreement, no alpha)."""
    adjusted = adjust_confidence_for_divergence(0.5, 0.3, "strong_agreement")
    assert abs(adjusted - 0.48) < 1e-9


def test_confidence_capped_at_one():
    adjusted = adjust_confidence_for_divergence(0.95, 2.5, "disagreement")
    assert adjusted == 1.0


def test_confidence_floored_at_point_one():
    adjusted = adjust_confidence_for_divergence(0.11, 0.2, "strong_agreement")
    assert adjusted == 0.1


def test_confidence_zero_edge_no_change():
    """Zero edge_score means no adjustment."""
    adjusted = adjust_confidence_for_divergence(0.6, 0.0, "strong_agreement")
    assert adjusted == 0.6


# ── End-to-end integration ──────────────────────────────────────

def test_end_to_end_line_shopping_adjusts_confidence():
    """Full flow: Synth data -> market lines -> edge-based confidence adjustment."""
    base_confidence = forecast_confidence(P24H, 67723.0)
    market = get_market_lines(SYNTH_OPTIONS, asset="BTC")
    adjusted = adjust_confidence_for_divergence(base_confidence, market.edge_score, market.consensus)
    # Mock providers produce some divergence -> confidence should shift
    assert abs(adjusted - base_confidence) <= 0.12
    assert 0.1 <= adjusted <= 1.0


def test_default_providers_count():
    providers, data_source = _default_providers()
    assert len(providers) == 3
    assert data_source == "mock"
    names = {p.name for p in providers}
    assert names == {"Aevo", "Deribit", "OKX"}


def test_market_lines_stores_exchange_prices():
    """exchange_prices dict is stored on the result for downstream use."""
    result = get_market_lines(SYNTH_OPTIONS, asset="BTC")
    assert len(result.exchange_prices) == 3
    for name, prices in result.exchange_prices.items():
        assert "call_options" in prices
        assert "put_options" in prices
