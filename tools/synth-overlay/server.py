"""
Local API server for the Synth Overlay extension.
Serves edge data from SynthClient; extension calls this from Polymarket pages.
"""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "../.."))
if _here not in sys.path:
    sys.path.insert(0, _here)

from flask import Flask, jsonify, request

from synth_client import SynthClient

from analyzer import EdgeAnalyzer
from edge import edge_from_range_bracket
from matcher import get_market_type, normalize_slug

app = Flask(__name__)
_client: SynthClient | None = None


def get_client() -> SynthClient:
    global _client
    if _client is None:
        _client = SynthClient()
    return _client


@app.after_request
def cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return "", 204
    return jsonify({"status": "ok", "mock": get_client().mock_mode})


@app.route("/api/edge", methods=["GET", "OPTIONS"])
def edge():
    if request.method == "OPTIONS":
        return "", 204
    raw = request.args.get("slug") or request.args.get("url") or ""
    slug = normalize_slug(raw)
    if not slug:
        return jsonify({"error": "Missing or invalid slug/url"}), 400
    market_type = get_market_type(slug)
    if not market_type:
        return jsonify({"error": "Unsupported market", "slug": slug}), 404
    try:
        client = get_client()
        if market_type in ("daily", "hourly"):
            daily_data = client.get_polymarket_daily()
            hourly_data = client.get_polymarket_hourly()
            expected_daily_slug = (daily_data.get("slug") or "").strip().lower()
            expected_hourly_slug = (hourly_data.get("slug") or "").strip().lower()
            request_slug = slug.strip().lower()
            if market_type == "daily" and request_slug != expected_daily_slug:
                return jsonify({"error": "Unsupported market", "slug": slug}), 404
            if market_type == "hourly" and request_slug != expected_hourly_slug:
                return jsonify({"error": "Unsupported market", "slug": slug}), 404
            pct_1h = None
            pct_24h = None
            try:
                pct_1h = client.get_prediction_percentiles("BTC", horizon="1h")
                pct_24h = client.get_prediction_percentiles("BTC", horizon="24h")
            except Exception:
                pass
            primary_horizon = "24h" if market_type == "daily" else "1h"
            analyzer = EdgeAnalyzer(daily_data, hourly_data, pct_1h, pct_24h)
            result = analyzer.analyze(primary_horizon=primary_horizon)
            primary_data = daily_data if market_type == "daily" else hourly_data
            return jsonify({
                "slug": primary_data.get("slug"),
                "horizon": primary_horizon,
                "edge_pct": result.primary.edge_pct,
                "signal": result.primary.signal,
                "strength": result.strength,
                "confidence_score": result.confidence_score,
                "edge_1h_pct": result.secondary.edge_pct if primary_horizon == "24h" else result.primary.edge_pct,
                "signal_1h": result.secondary.signal if primary_horizon == "24h" else result.primary.signal,
                "edge_24h_pct": result.primary.edge_pct if primary_horizon == "24h" else result.secondary.edge_pct,
                "signal_24h": result.primary.signal if primary_horizon == "24h" else result.secondary.signal,
                "no_trade_warning": result.no_trade,
                "explanation": result.explanation,
                "invalidation": result.invalidation,
                "synth_probability_up": primary_data.get("synth_probability_up"),
                "polymarket_probability_up": primary_data.get("polymarket_probability_up"),
                "current_time": primary_data.get("current_time"),
            })
        # range
        data = client.get_polymarket_range()
        if not isinstance(data, list):
            return jsonify({"error": "Invalid range data"}), 500
        bracket_title = request.args.get("bracket_title")
        brackets = [b for b in data if (b.get("slug") or "").strip() == slug]
        if not brackets:
            return jsonify({"error": "No brackets for slug", "slug": slug}), 404
        selected = None
        if bracket_title:
            matched = [b for b in brackets if (b.get("title") or "").strip() == bracket_title.strip()]
            if matched:
                selected = matched[0]
        if selected is None:
            selected = max(
                brackets,
                key=lambda b: float(b.get("polymarket_probability") or 0),
            )
        edge_pct, signal, strength = edge_from_range_bracket(selected)
        bracket_edges = []
        for bracket in brackets:
            b_edge, b_signal, b_strength = edge_from_range_bracket(bracket)
            bracket_edges.append(
                {
                    "title": bracket.get("title"),
                    "edge_pct": b_edge,
                    "signal": b_signal,
                    "strength": b_strength,
                    "synth_probability": bracket.get("synth_probability"),
                    "polymarket_probability": bracket.get("polymarket_probability"),
                }
            )
        return jsonify({
            "slug": selected.get("slug"),
            "horizon": "24h",
            "bracket_title": selected.get("title"),
            "edge_pct": edge_pct,
            "signal": signal,
            "strength": strength,
            "no_trade_warning": strength == "none",
            "synth_probability": selected.get("synth_probability"),
            "polymarket_probability": selected.get("polymarket_probability"),
            "current_time": selected.get("current_time"),
            "range_brackets": bracket_edges,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Server error", "detail": str(e)}), 500


def main():
    import warnings
    warnings.filterwarnings("ignore", message="No SYNTH_API_KEY")
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
