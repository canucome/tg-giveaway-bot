"""Anti-abuse primitives used by the live bot.

The three checks here are all *enabled by default* and wired into the request
path; `hardening/checks.py` re-exports them for the standalone test suite.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field


# --------------------------------------------------------------- account age
def account_age_gate(user_id: int, min_user_id: int) -> bool:
    """True when the account is old enough to take part.

    Telegram allocates user IDs in ascending order, so user_id >= min_user_id is
    a cheap proxy for "registered after date X" that a bot farm cannot fake.
    min_user_id <= 0 disables the numeric part of the filter.
    """
    if min_user_id <= 0:
        return True
    return int(user_id) >= int(min_user_id)


# ------------------------------------------------------------------ rate limit
@dataclass
class IpRateLimiter:
    """Sliding-window budget per client address (in-process, reset on restart).

    Good enough to stop a script hammering the verification page; a multi-worker
    deployment would need a shared store instead.
    """

    per_minute: int = 10
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, ip: str, now: float | None = None) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic() if now is None else now
        window = [t for t in self._hits.get(ip, []) if now - t < 60.0]
        if len(window) >= self.per_minute:
            self._hits[ip] = window
            return False
        window.append(now)
        self._hits[ip] = window
        if len(self._hits) > 4096:  # bound memory on a busy box
            self._hits = {k: v for k, v in self._hits.items() if v}
        return True


# --------------------------------------------------------------- commit-reveal
def make_commit() -> tuple[str, str]:
    """Return (seed, sha256(seed)): publish the hash, keep the seed secret."""
    seed = secrets.token_hex(32)
    return seed, hashlib.sha256(seed.encode()).hexdigest()


def reveal_ok(seed: str, commit: str) -> bool:
    """Check that a revealed seed matches the previously published commit."""
    return hmac.compare_digest(hashlib.sha256(seed.encode()).hexdigest(), commit)


def _keystream(seed: str, counter: int) -> bytes:
    return hashlib.sha256(f"{seed}:{counter}".encode()).digest()


def draw_indices(seed: str, n: int, k: int) -> list[int]:
    """Pick k distinct indices out of n, deterministically.

    Same seed and n always produce the same result, which is what makes a draw
    auditable: publish the seed afterwards and anybody can recompute it.
    """
    if n <= 0 or k <= 0:
        return []
    idx = list(range(n))
    counter = 0
    for i in range(min(k, n)):
        counter += 1
        r = int.from_bytes(_keystream(seed, counter), "big")
        j = i + r % (n - i)
        idx[i], idx[j] = idx[j], idx[i]
    return idx[: min(k, n)]
