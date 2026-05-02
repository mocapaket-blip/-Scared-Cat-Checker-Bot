"""
Высокоуровневая логика верификации.
Объединяет проверку через TON Connect (NFT) и через подарки Telegram.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot

from database import db
from services.gifts import user_has_collection_gift
from services.ton_api import TonApiError, user_owns_collection_nft

log = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    ok: bool
    method: Optional[str] = None  # 'wallet' | 'gift'
    detail: Optional[str] = None
    error: Optional[str] = None


async def verify_by_wallet(user_id: int, wallet: Optional[str] = None) -> VerifyResult:
    if wallet is None:
        user = await db.get_user(user_id)
        wallet = user.wallet_address if user else None
    if not wallet:
        return VerifyResult(ok=False, error="wallet_not_connected")

    try:
        owns = await user_owns_collection_nft(wallet)
    except TonApiError as e:
        log.warning("tonapi error for %s: %s", wallet, e)
        return VerifyResult(ok=False, error=f"tonapi: {e}")

    if owns:
        return VerifyResult(ok=True, method="wallet", detail=wallet)
    return VerifyResult(ok=False, error="no_nft")


async def verify_by_gift(bot: Bot, user_id: int) -> VerifyResult:
    has, name = await user_has_collection_gift(bot, user_id)
    if has:
        return VerifyResult(ok=True, method="gift", detail=name)
    return VerifyResult(ok=False, error="no_gift")


async def run_full_verification(bot: Bot, user_id: int) -> VerifyResult:
    """Пробует оба способа: сначала кошелёк (если есть), затем подарки."""
    user = await db.get_user(user_id)
    if user and user.wallet_address:
        result = await verify_by_wallet(user_id, user.wallet_address)
        if result.ok:
            await db.mark_verified(user_id, "wallet", wallet=user.wallet_address)
            return result

    result = await verify_by_gift(bot, user_id)
    if result.ok:
        await db.mark_verified(user_id, "gift")
        return result

    await db.touch_checked(user_id)
    return result
