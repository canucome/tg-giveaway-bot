from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.callbacks.factories import ClaimCb
from bot.db.base import get_sessionmaker
from bot.db.prize_repo import CLAIM_ALREADY, CLAIM_EMPTY, CLAIM_OK
from bot.db.repo import get_giveaway
from bot.filters.admin import IsAdmin
from bot.handlers.common import lang_of
from bot.i18n import t
from bot.services import prize as prize_service

log = logging.getLogger("bot.handlers.prize")


class AddCodesDraft(StatesGroup):
    waiting_codes = State()


# Giveaways whose creator was already warned that a tier ran dry, so a
# hundred disappointed winners do not produce a hundred DMs.
_warned: set[tuple[int, str]] = set()


async def _warn_creator(bot: Bot, giveaway_id: int, creator_id: int, tier: str) -> None:
    key = (giveaway_id, tier)
    if key in _warned:
        return
    _warned.add(key)
    lang = await lang_of(creator_id)
    try:
        await bot.send_message(
            creator_id,
            t("prize.stock_alert", lang, id=giveaway_id, tier=tier),
        )
    except Exception:
        log.warning("could not warn creator %s about empty stock", creator_id)


async def _deliver_code(bot: Bot, user_id: int, lang: str, code: str) -> None:
    await bot.send_message(user_id, t("prize.claimed", lang, code=code))


async def _claim_one(
    bot: Bot, lang: str, *, giveaway_id: int, user_id: int, tier: str, creator_id: int
) -> str:
    """Attempt one claim and message the user; returns the outcome status."""
    outcome = await prize_service.claim(giveaway_id, user_id, tier)
    if outcome.status == CLAIM_OK and outcome.code:
        await _deliver_code(bot, user_id, lang, outcome.code)
    elif outcome.status == CLAIM_EMPTY:
        await bot.send_message(user_id, t("prize.empty", lang))
        await _warn_creator(bot, giveaway_id, creator_id, tier)
    return outcome.status


def build_prize_router() -> Router:
    """Winner-facing routes: the claim button, /claim and /myprizes."""
    router = Router(name="prize")

    @router.callback_query(ClaimCb.filter())
    async def on_claim_button(cq: CallbackQuery, callback_data: ClaimCb, bot: Bot) -> None:
        uid = cq.from_user.id
        lang = await lang_of(uid)
        gid = callback_data.giveaway_id

        sm = get_sessionmaker()
        async with sm() as session:
            gw = await get_giveaway(session, gid)
        if gw is None:
            await cq.answer(t("prize.unknown", lang), show_alert=True)
            return
        if gw.prize_mode == "none":
            await cq.answer(t("prize.none_mode", lang), show_alert=True)
            return

        tier = prize_service.tier_at(gw.prize_tiers or [], callback_data.tier_index)
        if tier is None:
            await cq.answer(t("prize.unknown", lang), show_alert=True)
            return
        tier_name = str(tier.get("name"))

        held = await prize_service.won_tiers(gid, uid, gw.prize_tiers or [])
        if tier_name not in held:
            await cq.answer(t("prize.not_winner", lang), show_alert=True)
            return

        status = await _claim_one(
            bot,
            lang,
            giveaway_id=gid,
            user_id=uid,
            tier=tier_name,
            creator_id=gw.creator_id,
        )
        if status == CLAIM_ALREADY:
            await cq.answer(t("prize.already", lang), show_alert=True)
        else:
            await cq.answer()

    @router.message(Command("claim"))
    async def on_claim_command(message: Message, command: CommandObject, bot: Bot) -> None:
        uid = message.from_user.id
        lang = await lang_of(uid)
        try:
            gid = int((command.args or "").strip().split()[0])
        except (ValueError, IndexError):
            await message.answer(t("prize.claim_usage", lang))
            return

        sm = get_sessionmaker()
        async with sm() as session:
            gw = await get_giveaway(session, gid)
        if gw is None:
            await message.answer(t("prize.unknown", lang))
            return
        if gw.prize_mode == "none":
            await message.answer(t("prize.none_mode", lang))
            return

        held = await prize_service.won_tiers(gid, uid, gw.prize_tiers or [])
        if not held:
            await message.answer(t("prize.not_winner", lang))
            return

        delivered = 0
        for tier_name in held:
            status = await _claim_one(
                bot,
                lang,
                giveaway_id=gid,
                user_id=uid,
                tier=tier_name,
                creator_id=gw.creator_id,
            )
            if status == CLAIM_OK:
                delivered += 1
        if delivered == 0:
            await message.answer(t("prize.already", lang))

    @router.message(Command("myprizes"))
    async def on_myprizes(message: Message) -> None:
        uid = message.from_user.id
        lang = await lang_of(uid)
        rows = await prize_service.claimed_by(uid)
        if not rows:
            await message.answer(t("prize.myprizes_empty", lang))
            return
        lines = [t("prize.myprizes_header", lang, count=len(rows))]
        for row in rows:
            lines.append(
                t(
                    "prize.myprizes_row",
                    lang,
                    id=row.giveaway_id,
                    title=row.giveaway_title,
                    tier=row.tier_name,
                    code=row.code,
                )
            )
        await message.answer("\n\n".join(lines))

    return router


def build_prize_admin_router() -> Router:
    """Admin stock routes: /addcodes and /prizestatus."""
    router = Router(name="prize_admin")
    router.message.filter(IsAdmin())

    @router.message(Command("prizestatus"))
    async def on_prizestatus(message: Message, command: CommandObject) -> None:
        lang = await lang_of(message.from_user.id)
        try:
            gid = int((command.args or "").strip().split()[0])
        except (ValueError, IndexError):
            await message.answer(t("prize.status_usage", lang))
            return

        stock = await prize_service.stock(gid)
        if not stock:
            await message.answer(t("prize.stock_empty", lang, id=gid))
            return
        lines = [t("prize.stock_header", lang, id=gid)]
        for tier in stock.values():
            lines.append(
                t(
                    "prize.stock_row",
                    lang,
                    tier=tier.tier_name,
                    total=tier.total,
                    claimed=tier.claimed,
                    remaining=tier.remaining,
                )
            )
        await message.answer("\n".join(lines))

    @router.message(Command("addcodes"))
    async def on_addcodes(message: Message, command: CommandObject, state: FSMContext) -> None:
        lang = await lang_of(message.from_user.id)
        parts = (command.args or "").split(None, 1)
        if len(parts) < 2:
            await message.answer(t("prize.addcodes_usage", lang))
            return
        try:
            gid = int(parts[0])
        except ValueError:
            await message.answer(t("prize.addcodes_usage", lang))
            return
        tier_name = parts[1].strip()

        sm = get_sessionmaker()
        async with sm() as session:
            gw = await get_giveaway(session, gid)
        if gw is None:
            await message.answer(t("prize.unknown", lang))
            return
        known = [str(tier.get("name")) for tier in (gw.prize_tiers or [])]
        if tier_name not in known:
            await message.answer(
                t("prize.addcodes_unknown_tier", lang, id=gid, tier=tier_name, tiers=", ".join(known) or "-")
            )
            return

        await state.set_state(AddCodesDraft.waiting_codes)
        await state.update_data(gid=gid, tier=tier_name)
        await message.answer(t("prize.addcodes_prompt", lang, tier=tier_name))

    @router.message(Command("cancel"), StateFilter(AddCodesDraft))
    async def on_cancel_codes(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(t("common.cancel", await lang_of(message.from_user.id)))

    @router.message(AddCodesDraft.waiting_codes)
    async def step_codes(message: Message, state: FSMContext) -> None:
        lang = await lang_of(message.from_user.id)
        text = message.text or ""
        if text.strip() == "-":
            await state.clear()
            await message.answer(t("common.cancel", lang))
            return
        code_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not code_lines:
            await message.answer(t("prize.addcodes_empty", lang))
            return

        data = await state.get_data()
        gid = int(data["gid"])
        tier_name = str(data["tier"])

        sm = get_sessionmaker()
        async with sm() as session:
            gw = await get_giveaway(session, gid)
        mode = gw.prize_mode if gw else "unique"
        added = await prize_service.add_codes(
            gid, tier_name, code_lines, max_claims=prize_service.max_claims_for(mode)
        )
        await state.clear()
        await message.answer(t("prize.addcodes_ok", lang, id=gid, tier=tier_name, count=added))


    return router
