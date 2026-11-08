from __future__ import annotations

import logging
from typing import Any, Sequence

from bot.db.base import get_sessionmaker
from bot.db.prize_repo import (
    CLAIM_OK,
    SHARED_CAP,
    ClaimOutcome,
    PrizeView,
    TierStock,
    add_codes as repo_add_codes,
    claim_code,
    my_prizes as repo_my_prizes,
    stock_by_tier,
)
from bot.db.repo import list_winners

log = logging.getLogger("bot.services.prize")


def tier_at(prize_tiers: Sequence[dict[str, Any]], index: int) -> dict[str, Any] | None:
    """Resolve a tier by position, tolerating a stale button."""
    if 0 <= index < len(prize_tiers):
        return dict(prize_tiers[index])
    return None


def max_claims_for(mode: str) -> int:
    """A shared text is one row every winner may consume; a code is one row."""
    return SHARED_CAP if mode == "shared" else 1


async def add_codes(
    giveaway_id: int, tier_name: str, codes: list[str], *, max_claims: int = 1
) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        added = await repo_add_codes(
            session, giveaway_id, tier_name, codes, max_claims=max_claims
        )
        await session.commit()
        return added


async def claim(giveaway_id: int, user_id: int, tier_name: str) -> ClaimOutcome:
    """Claim one prize; the session is committed only on success.

    ``claim_code()`` rolls back on the paths where it changed nothing, so a
    failed attempt never leaves a counter incremented.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        outcome = await claim_code(
            session, giveaway_id=giveaway_id, user_id=user_id, tier_name=tier_name
        )
        if outcome.status == CLAIM_OK:
            await session.commit()
        else:
            await session.rollback()
        return outcome


async def stock(giveaway_id: int) -> dict[str, TierStock]:
    sm = get_sessionmaker()
    async with sm() as session:
        return await stock_by_tier(session, giveaway_id)


async def claimed_by(user_id: int) -> list[PrizeView]:
    sm = get_sessionmaker()
    async with sm() as session:
        return await repo_my_prizes(session, user_id)


async def won_tiers(giveaway_id: int, user_id: int, prize_tiers: Sequence[dict[str, Any]]) -> list[str]:
    """Tier names this user currently holds for one giveaway, in tier order."""
    sm = get_sessionmaker()
    async with sm() as session:
        winners = await list_winners(session, giveaway_id)
    held = {w.tier_name for w in winners if w.user_id == user_id}
    return [str(tier.get("name")) for tier in prize_tiers if str(tier.get("name")) in held]
