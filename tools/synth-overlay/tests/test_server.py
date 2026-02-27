"""Tests for overlay API server (mock client)."""

import sys
import os
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from synth_client import SynthClient

from server import app


@pytest.fixture
def client():
    return app.test_client()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "mock" in data


def test_edge_daily(client):
    resp = client.get("/api/edge?slug=bitcoin-up-or-down-on-february-26")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "edge_pct" in data
    assert data["signal"] in ("underpriced", "overpriced", "fair")
    assert data["strength"] in ("strong", "moderate", "none")
    assert data["horizon"] == "24h"
    assert "edge_1h_pct" in data
    assert "edge_24h_pct" in data
    assert "signal_1h" in data
    assert "signal_24h" in data
    assert "no_trade_warning" in data
    assert "confidence_score" in data
    assert 0 <= data["confidence_score"] <= 1
    assert "explanation" in data
    assert len(data["explanation"]) > 10
    assert "invalidation" in data
    assert len(data["invalidation"]) > 10


def test_edge_hourly_uses_hourly_primary_fields(client):
    resp = client.get("/api/edge?slug=bitcoin-up-or-down-february-25-6pm-et")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["horizon"] == "1h"
    assert data["slug"] == "bitcoin-up-or-down-february-25-6pm-et"
    assert data["synth_probability_up"] == 0.0004
    assert data["polymarket_probability_up"] == 0.006500000000000001


def test_edge_missing_slug(client):
    resp = client.get("/api/edge")
    assert resp.status_code == 400


def test_edge_unsupported_slug(client):
    resp = client.get("/api/edge?slug=unsupported-random-market")
    assert resp.status_code == 404


def test_edge_pattern_matched_slug_supported(client):
    resp = client.get("/api/edge?slug=btc-up-or-down-on-march-1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["slug"] == "btc-up-or-down-on-march-1"


def test_edge_range(client):
    resp = client.get("/api/edge?slug=bitcoin-price-on-february-26")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "edge_pct" in data
    assert "bracket_title" in data
    assert "no_trade_warning" in data
    assert "range_brackets" in data
    assert isinstance(data["range_brackets"], list)
    assert len(data["range_brackets"]) > 1
    assert "confidence_score" in data
    assert 0 <= data["confidence_score"] <= 1
    assert "explanation" in data
    assert len(data["explanation"]) > 10
    assert "invalidation" in data
    assert len(data["invalidation"]) > 10


def test_edge_range_respects_bracket_title(client):
    resp = client.get(
        "/api/edge?slug=bitcoin-price-on-february-26&bracket_title=%5B68000%2C%2070000%5D"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["bracket_title"] == "[68000, 70000]"


def test_edge_range_unknown_slug_404(client):
    resp = client.get("/api/edge?slug=bitcoin-price-on-february-26-nonexistent")
    assert resp.status_code == 404
