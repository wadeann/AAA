#!/usr/bin/env python3
"""
A-stock real transaction cost model.
Real costs:
  - Buy:  券商佣金 0.025% (min 5 RMB) + 过户费 0.002% (SH only)
  - Sell: 券商佣金 0.025% (min 5 RMB) + 印花税 0.1% + 过户费 0.002% (SH only)
SH codes: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx
SZ codes: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx, 301xxx
"""
from __future__ import annotations

# Rate constants
BROKERAGE_RATE = 0.00025   # 券商佣金 0.025% (万2.5)
STAMP_DUTY_RATE = 0.001    # 印花税 0.1% (sell only)
TRANSFER_FEE_RATE = 0.00002  # 过户费 0.002% (SH only)
MIN_BROKERAGE = 5.0        # 最低佣金 5 RMB


def is_sh(symbol: str) -> bool:
    """Check if symbol is Shanghai exchange (.SH suffix)."""
    return symbol.endswith(".SH")


def buy_cost(amount: float, symbol: str = "") -> float:
    """
    Total buy-side transaction cost in RMB.
    = brokerage (min 5) + transfer fee (SH only)
    """
    brokerage = max(amount * BROKERAGE_RATE, MIN_BROKERAGE)
    transfer = amount * TRANSFER_FEE_RATE if is_sh(symbol) else 0.0
    return brokerage + transfer


def sell_cost(amount: float, symbol: str = "") -> float:
    """
    Total sell-side transaction cost in RMB.
    = brokerage (min 5) + stamp duty + transfer fee (SH only)
    """
    brokerage = max(amount * BROKERAGE_RATE, MIN_BROKERAGE)
    stamp = amount * STAMP_DUTY_RATE
    transfer = amount * TRANSFER_FEE_RATE if is_sh(symbol) else 0.0
    return brokerage + stamp + transfer


def round_trip_cost(amount: float, symbol: str = "") -> float:
    """Total buy + sell cost for a round trip."""
    return buy_cost(amount, symbol) + sell_cost(amount, symbol)
