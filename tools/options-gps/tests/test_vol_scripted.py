"""Scripted end-to-end test for volatility trading feature (issue #16).
Runs the full vol pipeline with mock option data and verifies the complete flow:
IV estimation -> vol comparison -> strategy generation -> ranking -> card selection."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import (
    estimate_implied_vol,
    compare_volatility,
    generate_strategies,
    rank_strategies,
    select_three_cards,
    should_no_trade,
    strategy_pnl_values,
    compute_payoff_metrics,
    forecast_confidence,
    run_forecast_fusion,
    StrategyCandidate,
)

OPTION_DATA = {
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

CURRENT_PRICE = 67723.0


def test_full_vol_pipeline_long_vol():
    """Synth vol >> implied vol -> long_vol bias -> long straddle/strangle recommended."""
    # Step 1: Estimate IV from option pricing
    iv = estimate_implied_vol(OPTION_DATA)
    assert iv > 0, f"IV should be positive, got {iv}"

    # Step 2: Simulate Synth forecasting higher vol than market prices imply
    synth_vol = iv * 1.5  # 50% above IV -> clear long_vol signal
    vol_bias = compare_volatility(synth_vol, iv)
    assert vol_bias == "long_vol", f"Expected long_vol, got {vol_bias}"

    # Step 3: Guardrails should allow trading with a clear vol edge
    confidence = forecast_confidence(P24H, CURRENT_PRICE)
    fusion = run_forecast_fusion(None, P24H, CURRENT_PRICE)
    no_trade = should_no_trade(fusion, "vol", False, confidence, vol_bias=vol_bias)
    assert no_trade is None, f"Should allow vol trading, got: {no_trade}"

    # Step 4: Generate vol strategies
    candidates = generate_strategies(OPTION_DATA, "vol", "medium", asset="BTC")
    types = {c.strategy_type for c in candidates}
    assert "long_straddle" in types, f"Missing long_straddle in {types}"
    assert "long_strangle" in types, f"Missing long_strangle in {types}"

    # Step 5: All candidates should have valid legs
    for c in candidates:
        assert len(c.legs) >= 2, f"{c.description} needs >= 2 legs"
        assert c.max_loss > 0, f"{c.description} needs positive max_loss"

    # Step 6: PnL sanity for long straddle
    straddle = next(c for c in candidates if c.strategy_type == "long_straddle")
    pnl = strategy_pnl_values(straddle, [60000, 65000, 67500, 70000, 75000])
    # At extremes, long straddle should profit
    assert pnl[0] > 0, "Long straddle should profit on big down move"
    assert pnl[-1] > 0, "Long straddle should profit on big up move"
    # At strike, should lose premium
    assert pnl[2] < 0, "Long straddle should lose at strike"

    # Step 7: Rank with long_vol bias
    outcome_prices = [float(P24H[k]) for k in sorted(P24H.keys())]
    scored = rank_strategies(
        candidates, fusion, "vol", outcome_prices, "medium", CURRENT_PRICE,
        confidence=confidence, vol_bias=vol_bias,
    )
    assert len(scored) >= 2, f"Expected >= 2 scored strategies, got {len(scored)}"

    # Step 8: With long_vol bias, top pick should be a long vol strategy
    best = scored[0]
    assert best.strategy.strategy_type in ("long_straddle", "long_strangle"), \
        f"Expected long vol strategy on top, got {best.strategy.strategy_type}"
    assert "vol bias" in best.rationale.lower()

    # Step 9: Card selection should produce 3 cards
    best_card, safer, upside = select_three_cards(scored)
    assert best_card is not None
    assert best_card.probability_of_profit > 0
    assert best_card.expected_value != 0


def test_full_vol_pipeline_short_vol():
    """Synth vol << implied vol -> short_vol bias -> iron condor / short strangle preferred."""
    iv = estimate_implied_vol(OPTION_DATA)
    synth_vol = iv * 0.6  # 40% below IV -> clear short_vol signal
    vol_bias = compare_volatility(synth_vol, iv)
    assert vol_bias == "short_vol"

    confidence = forecast_confidence(P24H, CURRENT_PRICE)
    fusion = run_forecast_fusion(None, P24H, CURRENT_PRICE)
    no_trade = should_no_trade(fusion, "vol", False, confidence, vol_bias=vol_bias)
    assert no_trade is None

    # High risk to include short straddle/strangle
    candidates = generate_strategies(OPTION_DATA, "vol", "high", asset="BTC")
    types = {c.strategy_type for c in candidates}
    assert "short_straddle" in types or "short_strangle" in types or "iron_condor" in types

    outcome_prices = [float(P24H[k]) for k in sorted(P24H.keys())]
    scored = rank_strategies(
        candidates, fusion, "vol", outcome_prices, "high", CURRENT_PRICE,
        confidence=confidence, vol_bias=vol_bias,
    )
    assert len(scored) >= 1

    # With short_vol bias, top pick should be a short vol strategy
    best = scored[0]
    assert best.strategy.strategy_type in ("short_straddle", "short_strangle", "iron_condor"), \
        f"Expected short vol strategy on top, got {best.strategy.strategy_type}"


def test_full_vol_pipeline_no_edge():
    """Synth vol ≈ implied vol -> neutral_vol -> no-trade guardrail fires."""
    iv = estimate_implied_vol(OPTION_DATA)
    synth_vol = iv * 1.05  # ~5% above IV -> within threshold -> no edge
    vol_bias = compare_volatility(synth_vol, iv)
    assert vol_bias == "neutral_vol"

    confidence = forecast_confidence(P24H, CURRENT_PRICE)
    fusion = run_forecast_fusion(None, P24H, CURRENT_PRICE)
    no_trade = should_no_trade(fusion, "vol", False, confidence, vol_bias=vol_bias)
    assert no_trade is not None, "Should block trading when no vol edge"
    assert "no vol edge" in no_trade.lower() or "similar" in no_trade.lower()


if __name__ == "__main__":
    test_full_vol_pipeline_long_vol()
    print("PASS: test_full_vol_pipeline_long_vol")
    test_full_vol_pipeline_short_vol()
    print("PASS: test_full_vol_pipeline_short_vol")
    test_full_vol_pipeline_no_edge()
    print("PASS: test_full_vol_pipeline_no_edge")
    print("\nAll scripted vol tests passed.")
