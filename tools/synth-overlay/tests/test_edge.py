"""Tests for edge calculation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from edge import (
    compute_edge_pct,
    signal_from_edge,
    strength_from_edge,
    signals_conflict,
    strength_from_horizons,
    uncertainty_high_from_percentiles,
    edge_from_daily_or_hourly,
    edge_from_range_bracket,
)


def test_compute_edge_pct_positive():
    assert compute_edge_pct(0.50, 0.40) == 10.0


def test_compute_edge_pct_negative():
    assert compute_edge_pct(0.35, 0.45) == -10.0


def test_compute_edge_pct_fair():
    assert compute_edge_pct(0.40, 0.40) == 0.0


def test_compute_edge_pct_invalid_raises():
    with pytest.raises(ValueError):
        compute_edge_pct(1.5, 0.5)
    with pytest.raises(ValueError):
        compute_edge_pct(0.5, -0.1)


def test_signal_underpriced():
    assert signal_from_edge(3.0) == "underpriced"
    assert signal_from_edge(0.6) == "underpriced"


def test_signal_overpriced():
    assert signal_from_edge(-3.0) == "overpriced"
    assert signal_from_edge(-0.6) == "overpriced"


def test_signal_fair():
    assert signal_from_edge(0.0) == "fair"
    assert signal_from_edge(0.4) == "fair"
    assert signal_from_edge(-0.4) == "fair"


def test_strength_strong():
    assert strength_from_edge(5.0) == "strong"
    assert strength_from_edge(-4.0) == "strong"


def test_strength_moderate():
    assert strength_from_edge(2.0) == "moderate"
    assert strength_from_edge(-1.5) == "moderate"


def test_strength_none():
    assert strength_from_edge(0.5) == "none"
    assert strength_from_edge(0.0) == "none"


def test_edge_from_daily_or_hourly():
    data = {"synth_probability_up": 0.4151, "polymarket_probability_up": 0.395}
    edge_pct, signal, strength = edge_from_daily_or_hourly(data)
    assert edge_pct == 2.0
    assert signal == "underpriced"
    assert strength == "moderate"


def test_edge_from_daily_or_hourly_missing_keys():
    with pytest.raises(ValueError):
        edge_from_daily_or_hourly({"synth_probability_up": 0.5})


def test_edge_from_range_bracket():
    bracket = {"synth_probability": 0.3773, "polymarket_probability": 0.395}
    edge_pct, signal, strength = edge_from_range_bracket(bracket)
    assert edge_pct == -1.8
    assert signal == "overpriced"
    assert strength == "moderate"


def test_signals_conflict():
    assert signals_conflict("underpriced", "overpriced") is True
    assert signals_conflict("overpriced", "underpriced") is True
    assert signals_conflict("underpriced", "underpriced") is False
    assert signals_conflict("fair", "overpriced") is False
    assert signals_conflict("underpriced", "fair") is False


def test_strength_from_horizons_aligned_strong():
    assert strength_from_horizons(4.0, 5.0) == "strong"


def test_strength_from_horizons_aligned_moderate():
    assert strength_from_horizons(1.5, 2.0) == "moderate"


def test_strength_from_horizons_conflicting_none():
    assert strength_from_horizons(3.0, -3.0) == "none"


def test_strength_from_horizons_weak_none():
    assert strength_from_horizons(0.3, 0.4) == "none"


def test_uncertainty_high_from_percentiles_wide_spread():
    data = {
        "current_price": 100.0,
        "forecast_future": {
            "percentiles": [{"0.05": 90.0, "0.95": 115.0}],
        },
    }
    assert uncertainty_high_from_percentiles(data, relative_spread_threshold=0.05) is True


def test_uncertainty_high_from_percentiles_narrow_spread():
    data = {
        "current_price": 100.0,
        "forecast_future": {
            "percentiles": [{"0.05": 99.0, "0.95": 101.0}],
        },
    }
    assert uncertainty_high_from_percentiles(data, relative_spread_threshold=0.05) is False
