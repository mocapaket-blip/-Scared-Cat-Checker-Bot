"""
Проверка владения подарком в профиле Telegram через Bot API getUserGifts (>= 9.3).

ВАЖНО: поле is_saved (виден ли подарок в профиле) полностью игнорируется —
нам важен сам факт владения, даже если подарок скрыт.
"""
import logging
from typing import Iterable, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from config import settings

log = logging.getLogger(__name__)


def _safe_lower(value) -> str:
    return str(value).lower() if value else ""


def _matches_keywords(text: str, keywords: Iterable[str]) -> bool:
    if not text:
        return False
    return any(kw and kw in text for kw in keywords)


def _gift_matches(gift, keywords: Iterable[str]) -> bool:
    """
    Проверяет OwnedGiftUnique (type='unique') и игнорирует RegularGift.
    is_saved НЕ проверяется — подарок валиден даже если скрыт.
    """
    gift_type = getattr(gift, "type", None)
    if gift_type != "unique":
        return False

    inner = getattr(gift, "gift", None)

    candidates = []

    model = getattr(inner, "model", None)
    if model is not None:
        candidates.append(_safe_lower(getattr(model, "name", None)))

    candidates.append(_safe_lower(getattr(inner, "name", None)))
    candidates.append(_safe_lower(getattr(inner, "base_name", None)))
    candidates.append(_safe_lower(getattr(gift, "name", None)))
    candidates.append(_safe_lower(getattr(gift, "base_name", None)))

    return any(_matches_keywords(c, keywords) for c in candidates)


async def user_has_collection_gift(
    bot: Bot,
    user_id: int,
    keywords: Optional[Iterable[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Возвращает (has_gift, matched_name).

    Требования:
      • Пользователь должен начать диалог с ботом — иначе getUserGifts вернёт ошибку.
      • Бот должен использовать Bot API >= 9.3 (aiogram 3.13+).
    """
    keywords = list(keywords or settings.gift_keywords_list)
    if not keywords:
        return False, None

    try:
        owned = await bot.get_user_gifts(user_id=user_id)
    except TelegramBadRequest as e:
        log.warning("get_user_gifts failed for %s: %s", user_id, e)
        return False, None
    except AttributeError:
        log.error(
            "bot.get_user_gifts отсутствует — обнови aiogram до 3.13+ "
            "(Bot API 9.3+)."
        )
        return False, None

    gifts = getattr(owned, "gifts", None) or []
    for g in gifts:
        if _gift_matches(g, keywords):
            inner = getattr(g, "gift", None)
            model = getattr(inner, "model", None)
            name = (
                getattr(model, "name", None)
                or getattr(inner, "name", None)
                or getattr(inner, "base_name", None)
                or "Scared Cat"
            )
            return True, str(name)

    return False, None
