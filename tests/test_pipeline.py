#!/usr/bin/env python3
"""Test pipeline utility functions with mock data."""
from __future__ import annotations

from execution.pipeline import (
    is_shadow_ready,
    is_catalyst_enabled,
    compute_empirical_bayes_win_rate,
    extract_attribution_layers,
    hierarchical_attribution,
)


def _candidate(
    symbol: str = "000001.SZ",
    direction: str = "buy",
    price: float = 10.0,
    chan_buy_point: str | None = "二买",
    chan_confirmed: bool = True,
    volume_confirmed: bool = True,
    **kwargs,
) -> dict:
    cand: dict = {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "chan_buy_point": chan_buy_point,
        "chan_confirmed": chan_confirmed,
        "volume_confirmed": volume_confirmed,
    }
    cand.update(kwargs)
    return cand


# ── is_shadow_ready ──


def test_is_shadow_ready_valid_buy() -> None:
    """Valid buy candidate passes shadow check."""
    cand = _candidate()
    assert is_shadow_ready(cand) is True


def test_is_shadow_ready_no_buy_point() -> None:
    """Candidate without buy point fails."""
    cand = _candidate(chan_buy_point=None)
    assert is_shadow_ready(cand) is False


def test_is_shadow_ready_no_volume() -> None:
    """Candidate without volume confirmation fails."""
    cand = _candidate(volume_confirmed=False)
    assert is_shadow_ready(cand) is False


def test_is_shadow_ready_no_chanlun() -> None:
    """Candidate without chanlun confirmation fails."""
    cand = _candidate(chan_confirmed=False)
    assert is_shadow_ready(cand) is False


def test_is_shadow_ready_sell() -> None:
    """Sell candidate needs chan_sell_point and confirmation."""
    cand = _candidate(direction="sell", chan_buy_point=None, chan_sell_point="一卖")
    assert is_shadow_ready(cand) is True


def test_is_shadow_ready_invalid_direction() -> None:
    """Invalid direction returns False."""
    cand = _candidate(direction="hold")
    assert is_shadow_ready(cand) is False


# ── is_catalyst_enabled ──


def test_is_catalyst_enabled_sell_bypass() -> None:
    """Sell direction always bypasses catalyst checks."""
    assert is_catalyst_enabled("technical_breakout", direction="sell") is True


def test_is_catalyst_enabled_blacklisted() -> None:
    """Blacklisted catalyst returns False."""
    params = {"blacklist": ["technical_breakout"]}
    assert is_catalyst_enabled("technical_breakout", params=params, direction="buy") is False


def test_is_catalyst_enabled_default() -> None:
    """Missing catalyst config defaults to enabled."""
    params = {}
    assert is_catalyst_enabled("momentum_breakout", params=params) is True


# ── compute_empirical_bayes_win_rate ──


def test_empirical_bayes_no_samples() -> None:
    """Zero samples returns prior."""
    rate = compute_empirical_bayes_win_rate(0, 0)
    assert rate == 0.5


def test_empirical_bayes_few_samples_shrinks() -> None:
    """Few samples are shrunk toward prior."""
    rate = compute_empirical_bayes_win_rate(3, 5, prior_win_rate=0.5, prior_weight=5.0)
    # (3 + 2.5) / (5 + 5) = 5.5 / 10 = 0.55
    assert rate == 0.55


def test_empirical_bayes_many_samples() -> None:
    """Many samples approach empirical rate."""
    rate = compute_empirical_bayes_win_rate(40, 50, prior_win_rate=0.5, prior_weight=5.0)
    # (40 + 2.5) / (50 + 5) = 42.5 / 55 ≈ 0.7727
    assert rate == 0.7727


# ── extract_attribution_layers ──


def test_extract_attribution_layers_standard() -> None:
    """Standard candidate produces correct attribution layers."""
    record = {
        "catalyst_type": "limit_up_breakout",
        "chan_buy_point": "二买",
        "volume_confirmed": True,
        "confidence": 0.75,
        "entry_rule": "limit_up_open",
    }
    layers = extract_attribution_layers(record)
    assert layers["level_1_catalyst"] == "limit_up_breakout"
    assert layers["level_2_pattern"] == "二买/vol_confirmed"
    assert layers["confidence_band"] == "0.70-0.80"
    assert layers["entry_rule"] == "limit_up_open"


# ── hierarchical_attribution ──


def test_hierarchical_attribution_empty() -> None:
    """Empty outcomes produce empty stats."""
    result = hierarchical_attribution([])
    assert result["level_1"] == {}
    assert result["level_2"] == {}
