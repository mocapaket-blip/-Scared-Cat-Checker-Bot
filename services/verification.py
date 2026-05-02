"""
Высокоуровневая логика верификации.
Объединяет проверку через TON Connect (NFT) и через подарки Telegram.
После успеха — снимает restrict в группе.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions

from config import settings
from database import db
from services.gifts import user_has_collection_gift
from services.ton_api import TonApiError, user_owns_collection_nft

log = logging.getLogger(__name__)


# Полные права участника группы (снятие restrict)
FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
    can_manage_topics=False,
)


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


async def unrestrict_in_group(bot: Bot, user_id: int) -> bool:
    """Снять ограничения с пользователя в основной группе."""
    try:
        await bot.restrict_chat_member(
            chat_id=settings.GROUP_ID,
            user_id=user_id,
            permissions=FULL_PERMISSIONS,
        )
        await db.set_restricted(user_id, False)
        log.info("Unrestricted user %s in group", user_id)
        return True
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.warning("Cannot unrestrict %s: %s", user_id, e)
        return False


async def run_full_verification(bot: Bot, user_id: int) -> VerifyResult:
    """Пробует оба способа: сначала кошелёк (если есть), затем подарки."""
    user = await db.get_user(user_id)
    if user and user.wallet_address:
        result = await verify_by_wallet(user_id, user.wallet_address)
        if result.ok:
            await db.mark_verified(user_id, "wallet", wallet=user.wallet_address)
            await unrestrict_in_group(bot, user_id)
            return result

    result = await verify_by_gift(bot, user_id)
    if result.ok:
        await db.mark_verified(user_id, "gift")
        await unrestrict_in_group(bot, user_id)
        return result

    await db.touch_checked(user_id)
    return result
