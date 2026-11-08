from __future__ import annotations

from hardening.checks import (
    IpRateLimiter,
    account_age_gate,
    draw_indices,
    make_commit,
    reveal_ok,
)


def test_age_gate():
    assert account_age_gate(7_500_000_000, 5_000_000_000)
    assert not account_age_gate(5_000_000_000 - 1, 5_000_000_000)


def test_rate_limiter_window():
    lim = IpRateLimiter(per_minute=3)
    assert [lim.allow("1.2.3.4", now=t) for t in (0.0, 1.0, 2.0)] == [True] * 3
    assert lim.allow("1.2.3.4", now=3.0) is False
    assert lim.allow("5.6.7.8", now=3.0) is True
    assert lim.allow("1.2.3.4", now=61.0) is True


def test_commit_reveal():
    seed, commit = make_commit()
    assert reveal_ok(seed, commit)
    assert not reveal_ok(seed + "x", commit)


def test_draw_is_reproducible_and_unique():
    seed, _ = make_commit()
    a = draw_indices(seed, 1000, 5)
    assert a == draw_indices(seed, 1000, 5)
    assert len(set(a)) == 5
    assert all(0 <= i < 1000 for i in a)
    other, _ = make_commit()
    assert draw_indices(other, 1000, 5) != a


def test_draw_edge_cases():
    seed, _ = make_commit()
    assert draw_indices(seed, 0, 3) == []
    assert sorted(draw_indices(seed, 2, 5)) == [0, 1]
    assert len(draw_indices(seed, 2, 5)) == 2
