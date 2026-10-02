#!/usr/bin/env python3
"""Test pipeline utility functions with mock data."""
from __future__ import annotations

from execution.pipeline import (
    is_shadow_ready,
    is_catalyst_enabled,
    compute_empirical_bayes_win_rate,
    extract_attribution_layers,
    hierarchical_attribution,
    degraded_risk_check,
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


# ── degraded_risk_check ──


def _make_trading_session(is_open: bool = True) -> dict:
    return {"is_trading_day": True, "is_open": is_open}


def _make_account(cash: float = 100000.0, total_assets: float = 200000.0) -> dict:
    return {"cash": cash, "total_assets": total_assets}


def _make_positions(*holdings) -> list[dict]:
    """Each holding: (symbol, quantity, market_value, available_quantity)."""
    result = []
    for h in holdings:
        sym, qty, mv, avail = h
        result.append({
            "symbol": sym,
            "quantity": qty,
            "market_value": mv,
            "available_quantity": avail,
        })
    return result


def _make_intent(
    symbol: str = "000001.SZ",
    direction: str = "buy",
    price: float = 10.0,
    quantity: int = 1000,
    name: str = "",
    agy_approved: bool = False,
) -> dict:
    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "quantity": quantity,
        "name": name or symbol,
        "agy_approved": agy_approved,
        "llm_approved": agy_approved,
    }


def test_degraded_risk_check_all_pass() -> None:
    """Healthy intent passes all degraded checks."""
    session = _make_trading_session(is_open=True)
    account = _make_account(cash=100000, total_assets=200000)
    positions = _make_positions()
    intents = [_make_intent("000001.SZ", "buy", 10.0, 1000)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is True


def test_degraded_risk_check_rejects_outside_session() -> None:
    """Intent rejected when market is closed."""
    session = {"is_trading_day": False, "is_open": False}
    account = _make_account()
    positions = _make_positions()
    intents = [_make_intent()]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "outside trading session" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_rejects_invalid_price() -> None:
    """Zero or negative price rejected."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions()
    intents = [_make_intent(price=0.0)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "invalid price" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_rejects_st_blacklist() -> None:
    """ST stocks rejected even in degraded mode."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions()
    intents = [_make_intent(symbol="000001.SZ", name="ST平安")]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "ST blacklisted" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_rejects_insufficient_cash() -> None:
    """Buy with insufficient cash rejected."""
    session = _make_trading_session()
    account = _make_account(cash=5000, total_assets=200000)
    positions = _make_positions()
    intents = [_make_intent(price=10.0, quantity=1000)]  # cost = 10000, cash = 5000
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "insufficient cash" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_rejects_avg_down() -> None:
    """Avg-down prohibited when already holding."""
    session = _make_trading_session()
    account = _make_account(cash=100000, total_assets=200000)
    positions = _make_positions(("000001.SZ", 500, 5000, 500))
    intents = [_make_intent("000001.SZ", "buy", 10.0, 1000)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "avg-down" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_rejects_max_position_limit() -> None:
    """Max position limit exceeded for new symbol."""
    session = _make_trading_session()
    account = _make_account(cash=200000, total_assets=500000)
    # Already holding 5 symbols with >200 shares each
    positions = _make_positions(
        ("A1.SZ", 500, 10000, 500),
        ("A2.SZ", 500, 10000, 500),
        ("A3.SZ", 500, 10000, 500),
        ("A4.SZ", 500, 10000, 500),
        ("A5.SZ", 500, 10000, 500),
    )
    intents = [_make_intent("NEW.SZ", "buy", 10.0, 1000)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "max position limit" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_sell_with_position_passes() -> None:
    """Sell with available shares passes."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions(("000001.SZ", 500, 5000, 500))
    intents = [_make_intent("000001.SZ", "sell", 10.0, 300)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is True


def test_degraded_risk_check_sell_without_position_rejected() -> None:
    """Sell without position rejected."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions()
    intents = [_make_intent("000001.SZ", "sell", 10.0, 300)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "no position" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_sell_insufficient_shares_rejected() -> None:
    """Sell with insufficient shares rejected."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions(("000001.SZ", 50, 500, 50))
    intents = [_make_intent("000001.SZ", "sell", 10.0, 200)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "insufficient shares" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_agy_intent_no_special_treatment() -> None:
    """AGY-approved intent gets same treatment as non-AGY in degraded mode."""
    session = _make_trading_session()
    account = _make_account(cash=5000, total_assets=200000)
    positions = _make_positions()
    # AGY-approved but insufficient cash - should still be rejected
    intents = [_make_intent(price=10.0, quantity=1000, agy_approved=True)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "insufficient cash" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_multiple_intents_order_sensitive() -> None:
    """First buy consumes cash, second may fail due to ordering."""
    session = _make_trading_session()
    account = _make_account(cash=10000, total_assets=200000)
    positions = _make_positions()
    intents = [
        _make_intent("A1.SZ", "buy", 10.0, 600),   # cost 6000, OK
        _make_intent("A2.SZ", "buy", 10.0, 600),   # cost 6000, only 4000 left -> fail
    ]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is True
    assert result["results"][1]["approved"] is False
    assert "insufficient cash" in result["results"][1]["rejection_reason"]


def test_degraded_risk_check_single_position_cap() -> None:
    """Single position exceeds 30% cap."""
    session = _make_trading_session()
    account = _make_account(cash=100000, total_assets=100000)
    positions = _make_positions(("000001.SZ", 3000, 30000, 3000))  # 30% already
    # Adding another 10% -> 40% total, exceeds 30%
    intents = [_make_intent("000001.SZ", "buy", 10.0, 1000)]
    result = degraded_risk_check(intents, positions, account, session)
    assert result["results"][0]["approved"] is False
    assert "single position" in result["results"][0]["rejection_reason"]


def test_degraded_risk_check_empty_intents() -> None:
    """Empty intents list returns empty results."""
    session = _make_trading_session()
    account = _make_account()
    positions = _make_positions()
    result = degraded_risk_check([], positions, account, session)
    assert result["results"] == []
