from __future__ import annotations

import pytest

from bot.callbacks.factories import ClaimCb
from bot.db.models import GiveawayStatus
from bot.db.prize_repo import CLAIM_ALREADY, CLAIM_EMPTY, CLAIM_OK, SHARED_CAP
from bot.db.repo import GiveawayView, log_winners
from bot.handlers import prize as prize_handlers
from bot.services import prize as prize_service
from bot.services.notifier import _claim_keyboard

ADMIN_ID = 424242
TIER = "Steam card"


@pytest.mark.asyncio
async def test_unique_codes_are_handed_out_exactly_once(sessionmaker, new_giveaway) -> None:
    gid = await new_giveaway(prize_mode="unique")
    assert await prize_service.add_codes(gid, TIER, ["AAA-1", "BBB-2"]) == 2

    first = await prize_service.claim(gid, 1001, TIER)
    second = await prize_service.claim(gid, 1002, TIER)
    third = await prize_service.claim(gid, 1003, TIER)

    assert first.status == CLAIM_OK
    assert second.status == CLAIM_OK
    assert {first.code, second.code} == {"AAA-1", "BBB-2"}
    assert third.status == CLAIM_EMPTY

    stock = await prize_service.stock(gid)
    assert stock[TIER].total == 2
    assert stock[TIER].claimed == 2
    assert stock[TIER].remaining == 0


@pytest.mark.asyncio
async def test_second_claim_by_the_same_winner_is_idempotent(sessionmaker, new_giveaway) -> None:
    gid = await new_giveaway(prize_mode="unique")
    await prize_service.add_codes(gid, TIER, ["ONLY-ONE"])

    first = await prize_service.claim(gid, 1001, TIER)
    again = await prize_service.claim(gid, 1001, TIER)

    assert first.status == CLAIM_OK
    assert again.status == CLAIM_ALREADY
    prizes = await prize_service.claimed_by(1001)
    assert [p.code for p in prizes] == ["ONLY-ONE"]

    # The counter must not move on a rejected claim.
    stock = await prize_service.stock(gid)
    assert stock[TIER].claimed == 1


@pytest.mark.asyncio
async def test_shared_text_is_readable_by_every_winner(sessionmaker, new_giveaway) -> None:
    gid = await new_giveaway(prize_mode="shared")
    await prize_service.add_codes(
        gid, TIER, ["USE-THIS-CODE"], max_claims=prize_service.max_claims_for("shared")
    )

    first = await prize_service.claim(gid, 1001, TIER)
    second = await prize_service.claim(gid, 2002, TIER)

    assert first.code == second.code == "USE-THIS-CODE"
    stock = await prize_service.stock(gid)
    assert stock[TIER].total == SHARED_CAP
    assert stock[TIER].claimed == 2


@pytest.mark.asyncio
async def test_add_codes_skips_blanks_and_duplicates_in_one_batch(sessionmaker, new_giveaway) -> None:
    gid = await new_giveaway(prize_mode="unique")
    added = await prize_service.add_codes(gid, TIER, ["  A  ", "A", "", "   ", "B"])
    assert added == 2


@pytest.mark.asyncio
async def test_only_current_winners_hold_a_tier(sessionmaker, new_giveaway) -> None:
    gid = await new_giveaway(prize_mode="unique")
    async with sessionmaker() as session:
        await log_winners(session, gid, [(1001, TIER)])
        await session.commit()

    tiers = [{"name": TIER, "count": 1}]
    assert await prize_service.won_tiers(gid, 1001, tiers) == [TIER]
    assert await prize_service.won_tiers(gid, 9999, tiers) == []


def _view(gid: int, mode: str) -> GiveawayView:
    return GiveawayView(
        id=gid,
        creator_id=ADMIN_ID,
        title="R&D key",
        status=GiveawayStatus.finished,
        chat_id=None,
        message_id=None,
        turnstile_required=False,
        prize_mode=mode,
        prize_tiers=({"name": TIER, "count": 1},),
    )


def test_claim_keyboard_only_exists_for_self_service_giveaways() -> None:
    assert _claim_keyboard(_view(7, "none"), TIER, "en") is None

    keyboard = _claim_keyboard(_view(7, "unique"), TIER, "en")
    assert keyboard is not None
    packed = keyboard.inline_keyboard[0][0].callback_data
    parsed = ClaimCb.unpack(packed)
    assert parsed.giveaway_id == 7
    assert parsed.tier_index == 0

    # A tier that no longer exists yields no button instead of a broken one.
    assert _claim_keyboard(_view(7, "unique"), "gone", "en") is None


@pytest.mark.asyncio
async def test_claim_one_sends_the_code_and_warns_the_host_once(
    bot, sessionmaker, new_giveaway
) -> None:
    prize_handlers._warned.clear()
    gid = await new_giveaway(prize_mode="unique")
    await prize_service.add_codes(gid, TIER, ["CODE-9"])

    status = await prize_handlers._claim_one(
        bot, "en", giveaway_id=gid, user_id=1001, tier=TIER, creator_id=ADMIN_ID
    )
    assert status == CLAIM_OK
    assert bot.sent[0][0] == 1001
    assert "CODE-9" in bot.sent[0][1]

    # Stock is gone: the next winner is told, and the host is warned once.
    bot.sent.clear()
    assert (
        await prize_handlers._claim_one(
            bot, "en", giveaway_id=gid, user_id=1002, tier=TIER, creator_id=ADMIN_ID
        )
        == CLAIM_EMPTY
    )
    assert bot.sent[0][0] == 1002

    assert (
        await prize_handlers._claim_one(
            bot, "en", giveaway_id=gid, user_id=1003, tier=TIER, creator_id=ADMIN_ID
        )
        == CLAIM_EMPTY
    )
    host_warnings = [text for chat, text, _kw in bot.sent if chat == ADMIN_ID]
    assert len(host_warnings) == 1
