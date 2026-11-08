"""Compatibility shim for the anti-abuse primitives.

The real implementations live in :mod:`bot.utils.antiabuse` because the bot now
calls them on every join, every verification request and every draw.  They are
re-exported here so the standalone checks (and anyone who copied this folder
earlier) keep working.
"""
from __future__ import annotations

from bot.utils.antiabuse import (
    IpRateLimiter,
    account_age_gate,
    draw_indices,
    make_commit,
    reveal_ok,
)

__all__ = [
    "account_age_gate",
    "IpRateLimiter",
    "make_commit",
    "reveal_ok",
    "draw_indices",
]
