from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class LangCb(CallbackData, prefix="lang"):
    code: str


class JoinCb(CallbackData, prefix="join"):
    giveaway_id: int


class AdminGwCb(CallbackData, prefix="agw"):
    action: str
    giveaway_id: int


class ClaimCb(CallbackData, prefix="claim"):
    """Claim button on the winner DM.

    The tier travels as an index, not as its name: tier names are free text
    and would blow past Telegram's 64-byte callback_data limit.
    """

    giveaway_id: int
    tier_index: int
