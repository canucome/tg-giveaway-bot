from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from aiogram import Bot

from bot.db.base import get_sessionmaker
from bot.db.models import Giveaway, GiveawayStatus
from bot.db.repo import (
    GiveawayView,
    TierShortfall,
    blacklist_ids,
    claim_giveaway,
    create_giveaway,
    current_winner_ids,
    get_giveaway,
    list_participants,
    list_winners,
    log_winners,
    replace_tier_winners,
    set_giveaway_message,
)
from bot.services.notifier import publish_winners
from bot.utils.antiabuse import draw_indices, make_commit
from bot.utils.rng import sample_winners

log = logging.getLogger("bot.services.giveaway")


async def create(
    *,
    creator_id: int,
    title: str,
    description: str,
    prize_tiers: list[dict],
    required_channels: list[str],
    end_at: datetime,
    turnstile_required: bool,
    prize_mode: str = "none",
) -> Giveaway:
    # Commit before the giveaway exists in public: the hash ships in the post,
    # the seed is only revealed with the winners, so the draw can be replayed.
    seed, commit = make_commit()
    sm = get_sessionmaker()
    async with sm() as session:
        gw = await create_giveaway(
            session,
            creator_id=creator_id,
            title=title,
            description=description,
            prize_tiers=prize_tiers,
            required_channels=required_channels,
            end_at=end_at,
            turnstile_required=turnstile_required,
            prize_mode=prize_mode,
            draw_seed=seed,
            draw_commit=commit,
        )
        await session.commit()
        return gw


async def attach_message(giveaway_id: int, chat_id: int, message_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        await set_giveaway_message(session, giveaway_id, chat_id, message_id)
        await session.commit()


async def cancel(giveaway_id: int) -> bool:
    sm = get_sessionmaker()
    async with sm() as session:
        gw = await claim_giveaway(
            session,
            giveaway_id,
            GiveawayStatus.running,
            new_status=GiveawayStatus.canceled,
        )
        if gw is None:
            return False
        await session.commit()
        return True


def _tier_count(prize_tiers: list[dict] | None, tier_name: str) -> int:
    for tier in prize_tiers or []:
        if str(tier.get("name")) == tier_name:
            return int(tier.get("count", 0) or 0)
    return 0


class RerollError(RuntimeError):
    """Why a reroll was refused.  The handler turns this into user text."""


def _pool_digest(participants) -> str:
    """Fingerprint of the eligible pool, so the draw can be replayed later.

    Sorted by user_id, so the digest does not depend on join order.
    """
    ids = ",".join(str(p.user_id) for p in sorted(participants, key=lambda p: p.user_id))
    return hashlib.sha256(ids.encode()).hexdigest()


def _pick_tier(
    participants,
    tier_name: str,
    count: int,
    already: set[int],
    banned: set[int],
    *,
    seed: str | None = None,
    salt_suffix: str = "",
) -> tuple[list, TierShortfall | None]:
    """Draw ``count`` winners, honouring both exclusion sets.

    ``already`` = winners from other tiers of this giveaway; ``banned`` =
    accounts blacklisted after they entered.  Both were ignored before, so
    one person could collect every tier and a banned user could still win.

    A tier that cannot be filled in full returns a :class:`TierShortfall`
    instead of quietly handing out fewer prizes (P1-5).
    """
    pool = [p for p in participants if p.user_id not in already and p.user_id not in banned]
    if seed:
        # Deterministic by construction: the same seed, tier and pool always
        # produce the same winners, which is what makes the public commit
        # meaningful.  Falling back to SystemRandom is only for giveaways
        # created before commit-reveal existed.
        ordered = sorted(pool, key=lambda p: p.user_id)
        indices = draw_indices(f"{seed}|{tier_name}{salt_suffix}", len(ordered), count)
        picked = [ordered[i] for i in indices]
    else:
        picked = sample_winners(pool, count)
    if len(picked) < count:
        return picked, TierShortfall(tier=tier_name, requested=count, granted=len(picked))
    return picked, None


async def reroll_tier(
    giveaway_id: int, tier_name: str, bot: Bot
) -> tuple[list[tuple[int, str]], TierShortfall | None]:
    """Re-draw one tier of a **finished** giveaway.

    The old implementation happily re-ran on a running giveaway, which
    published winners early and then let the timer draw again - and it drew
    from the full pool with no memory of previous winners, so one user could
    win every tier and the same tier could be "rerolled" into itself.  Now:

    * only a finished giveaway may be rerolled;
    * the previous draw is stamped ``replaced_at`` (audit trail kept);
    * current winners of other tiers are excluded;
    * blacklisted users are excluded.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        gw = await claim_giveaway(session, giveaway_id, GiveawayStatus.finished)
        if gw is None:
            existing = await get_giveaway(session, giveaway_id)
            if existing is None:
                return [], None
            raise RerollError(existing.status.value)

        count = _tier_count(gw.prize_tiers, tier_name)
        if count <= 0:
            raise RerollError("no_such_tier")

        participants = await list_participants(session, giveaway_id, verified_only=True)
        if not participants:
            return [], TierShortfall(tier=tier_name, requested=count, granted=0)

        # Everyone already holding a live win, *including* the tier being
        # rerolled (its rows are about to be superseded).
        winners_elsewhere = await current_winner_ids(session, giveaway_id)
        banned = await blacklist_ids(session, [p.user_id for p in participants])
        # A reroll must not replay the first draw, so the salt carries the round
        # number - and that number is published with the new winners.
        prior = await list_winners(session, giveaway_id, include_replaced=True)
        round_no = sum(1 for w in prior if w.tier_name == tier_name) + 1
        digest = _pool_digest(participants)
        picked, shortfall = _pick_tier(
            participants,
            tier_name,
            count,
            winners_elsewhere,
            banned,
            seed=gw.draw_seed,
            salt_suffix=f"|r{round_no}",
        )

        await replace_tier_winners(session, giveaway_id, tier_name)
        picks = [(p.user_id, tier_name) for p in picked]
        await log_winners(session, giveaway_id, picks)
        view = GiveawayView.of(gw)
        await session.commit()

    await publish_winners(
        bot,
        view,
        winners=picks,
        reason="reroll",
        shortfalls=[shortfall] if shortfall is not None else [],
        reveal_round=round_no,
        pool_digest=digest,
    )
    return picks, shortfall


async def finalize_and_publish(giveaway_id: int, bot: Bot) -> None:
    """Draw every tier, mark the giveaway finished, announce the result."""
    sm = get_sessionmaker()
    async with sm() as session:
        gw = await claim_giveaway(
            session,
            giveaway_id,
            GiveawayStatus.running,
            new_status=GiveawayStatus.finished,
        )
        if gw is None:
            log.info("finalize: giveaway %d already closed or missing", giveaway_id)
            return
        participants = await list_participants(session, giveaway_id, verified_only=True)
        banned = await blacklist_ids(session, [p.user_id for p in participants])
        view = GiveawayView.of(gw)
        digest = _pool_digest(participants)

        picks: list[tuple[int, str]] = []
        shortfalls: list[TierShortfall] = []
        for tier in gw.prize_tiers or []:
            name = str(tier.get("name", "")) or "?"
            count = int(tier.get("count", 0) or 0)
            if count <= 0:
                continue
            already = {u for u, _ in picks}
            picked, shortfall = _pick_tier(
                participants, name, count, already, banned, seed=gw.draw_seed
            )
            picks.extend((p.user_id, name) for p in picked)
            if shortfall is not None:
                # P1-5: sample_winners() clamps k to the pool size, so a
                # tier used to shrink in silence and the post announced a
                # prize nobody received.  The shortfall is now reported.
                shortfalls.append(shortfall)

        await log_winners(session, giveaway_id, picks)
        await session.commit()

    # ``view`` is a frozen dataclass, not the live ORM row: the old code
    # passed a session-scoped Giveaway across the session boundary and only
    # survived because expire_on_commit=False happened to be set.
    await publish_winners(bot, view, winners=picks, shortfalls=shortfalls, pool_digest=digest)
