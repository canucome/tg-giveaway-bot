from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Giveaway, PrizeClaim, PrizeCode

log = logging.getLogger("bot.db.prize_repo")

#: The winner got their prize.
CLAIM_OK = "ok"
#: This winner already claimed this tier - hand back the same code again.
CLAIM_ALREADY = "already"
#: Nothing left in stock for that tier.
CLAIM_EMPTY = "empty"

#: How many rows a shared-text giveaway consumes.  One row with a huge cap
#: keeps the delivery code identical for both modes.
SHARED_CAP = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """Result of one claim attempt."""

    status: str
    code: str | None = None


@dataclass(frozen=True, slots=True)
class TierStock:
    """Inventory snapshot for one prize tier."""

    tier_name: str
    total: int
    claimed: int

    @property
    def remaining(self) -> int:
        return max(self.total - self.claimed, 0)


@dataclass(frozen=True, slots=True)
class PrizeView:
    """One row of /myprizes."""

    giveaway_id: int
    giveaway_title: str
    tier_name: str
    code: str
    claimed_at: datetime | None


async def add_codes(
    session: AsyncSession,
    giveaway_id: int,
    tier_name: str,
    codes: list[str],
    *,
    max_claims: int = 1,
) -> int:
    """Append codes to the stock of one tier; returns how many were added.

    Blank lines are dropped and duplicates *within this batch* are collapsed,
    but a code already present in the database is kept on purpose: the host
    may legitimately top up with the same shared text.
    """
    tier = tier_name.strip()[:64]
    seen: set[str] = set()
    added = 0
    for raw in codes:
        code = raw.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        session.add(
            PrizeCode(
                giveaway_id=giveaway_id,
                tier_name=tier,
                code=code,
                max_claims=max(int(max_claims), 1),
                claimed_count=0,
            )
        )
        added += 1
    if added:
        await session.flush()
    return added


async def stock_by_tier(session: AsyncSession, giveaway_id: int) -> dict[str, TierStock]:
    """Total / claimed / remaining per tier, for the admin panel."""
    rows = (
        await session.execute(
            select(
                PrizeCode.tier_name,
                func.sum(PrizeCode.max_claims),
                func.sum(PrizeCode.claimed_count),
            )
            .where(PrizeCode.giveaway_id == giveaway_id)
            .group_by(PrizeCode.tier_name)
        )
    ).all()
    return {
        name: TierStock(name, int(total or 0), int(claimed or 0))
        for name, total, claimed in rows
    }


async def has_claim(
    session: AsyncSession, *, giveaway_id: int, user_id: int, tier_name: str
) -> bool:
    found = await session.scalar(
        select(PrizeClaim.id).where(
            PrizeClaim.giveaway_id == giveaway_id,
            PrizeClaim.user_id == user_id,
            PrizeClaim.tier_name == tier_name.strip()[:64],
        )
    )
    return found is not None


async def claim_code(
    session: AsyncSession, *, giveaway_id: int, user_id: int, tier_name: str
) -> ClaimOutcome:
    """Hand one code to one winner, exactly once.

    Order matters: the row is reserved with a conditional UPDATE whose WHERE
    clause re-checks the stock, so two winners pressing the button in the
    same second cannot both be handed the same unique code.  The unique
    constraint on prize_claims is the second line of defence - if it fires,
    the transaction is rolled back so the reservation is undone as well.
    """
    tier = tier_name.strip()[:64]

    if await has_claim(session, giveaway_id=giveaway_id, user_id=user_id, tier_name=tier):
        return ClaimOutcome(CLAIM_ALREADY)

    for _ in range(5):
        row = await session.scalar(
            select(PrizeCode)
            .where(
                PrizeCode.giveaway_id == giveaway_id,
                PrizeCode.tier_name == tier,
                PrizeCode.claimed_count < PrizeCode.max_claims,
            )
            .order_by(PrizeCode.id)
            .limit(1)
        )
        if row is None:
            return ClaimOutcome(CLAIM_EMPTY)

        taken = await session.execute(
            update(PrizeCode)
            .where(
                PrizeCode.id == row.id,
                PrizeCode.claimed_count < PrizeCode.max_claims,
            )
            .values(claimed_count=PrizeCode.claimed_count + 1)
        )
        if taken.rowcount != 1:
            # Another request grabbed that row between our SELECT and UPDATE.
            await session.rollback()
            continue

        session.add(
            PrizeClaim(
                giveaway_id=giveaway_id,
                tier_name=tier,
                user_id=user_id,
                code_id=row.id,
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            # Same winner, same tier, twice: rollback also undoes the counter.
            await session.rollback()
            return ClaimOutcome(CLAIM_ALREADY)
        return ClaimOutcome(CLAIM_OK, row.code)

    return ClaimOutcome(CLAIM_EMPTY)


async def my_prizes(session: AsyncSession, user_id: int) -> list[PrizeView]:
    """Everything this user has already claimed, newest first."""
    rows = (
        await session.execute(
            select(
                PrizeClaim.giveaway_id,
                Giveaway.title,
                PrizeClaim.tier_name,
                PrizeCode.code,
                PrizeClaim.claimed_at,
            )
            .join(PrizeCode, PrizeCode.id == PrizeClaim.code_id)
            .join(Giveaway, Giveaway.id == PrizeClaim.giveaway_id)
            .where(PrizeClaim.user_id == user_id)
            .order_by(PrizeClaim.claimed_at.desc(), PrizeClaim.id.desc())
        )
    ).all()
    return [
        PrizeView(
            giveaway_id=gid,
            giveaway_title=title,
            tier_name=tier,
            code=code,
            claimed_at=claimed_at,
        )
        for gid, title, tier, code, claimed_at in rows
    ]
