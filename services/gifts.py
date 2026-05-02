"""
Проверка владения подарком в профиле Telegram через Bot API getUserGifts (>= 9.3).

ВАЖНО: поле is_saved (виден ли подарок в профиле) полностью игнорируется —
нам важен сам факт владения, даже если подарок скрыт.
"""
import logging
from typing import Iterable, List, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from config import settings

log = logging.getLogger(__name__)


def _safe_lower(value) -> str:
    return str(value).lower().strip() if value else ""


def _matches_keywords(text: str, keywords: Iterable[str]) -> bool:
    if not text:
        return False
    return any(kw and kw in text for kw in keywords)


def _extract_names(gift) -> List[str]:
    """Собирает все текстовые поля подарка для сравнения с ключевыми словами."""
    candidates = []

    inner = getattr(gift, "gift", None)

    if inner is not None:
        model = getattr(inner, "model", None)
        if model is not None:
            candidates.append(_safe_lower(getattr(model, "name", None)))

        candidates.append(_safe_lower(getattr(inner, "name", None)))
        candidates.append(_safe_lower(getattr(inner, "base_name", None)))
        candidates.append(_safe_lower(getattr(inner, "title", None)))

    # Поля напрямую на объекте подарка
    candidates.append(_safe_lower(getattr(gift, "name", None)))
    candidates.append(_safe_lower(getattr(gift, "base_name", None)))
    candidates.append(_safe_lower(getattr(gift, "title", None)))

    return [c for c in candidates if c]


def _gift_matches(gift, keywords: Iterable[str]) -> bool:
    """
    Проверяет подарок на совпадение с ключевыми словами.
    Проверяет ОБА типа: unique и regular.
    is_saved НЕ проверяется — подарок валиден даже если скрыт.
    """
    gift_type = getattr(gift, "type", None)

    # Для unique подарков — проверяем все текстовые поля
    if gift_type == "unique":
        names = _extract_names(gift)
        log.debug("Unique gift names: %s", names)
        return any(_matches_keywords(n, keywords) for n in names)

    # Для regular подарков тоже проверяем на случай нестандартных структур
    if gift_type == "regular":
        names = _extract_names(gift)
        if names:
            log.debug("Regular gift names: %s", names)
            return any(_matches_keywords(n, keywords) for n in names)

    return False


def _get_display_name(gift) -> str:
    """Возвращает читаемое имя подарка для отображения пользователю."""
    inner = getattr(gift, "gift", None)
    if inner is not None:
        model = getattr(inner, "model", None)
        if model:
            name = getattr(model, "name", None)
            if name:
                return str(name)
        name = getattr(inner, "name", None) or getattr(inner, "base_name", None)
        if name:
            return str(name)
    return getattr(gift, "name", None) or getattr(gift, "base_name", None) or "Scared Cat"


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
    # Расширенный список ключевых слов для поиска
    base_keywords = list(keywords or settings.gift_keywords_list)
    # Добавляем дополнительные вариации на случай разного написания
    extra = ["scared cats", "scaredcats", "scared_cat", "scared_cats"]
    all_keywords = list(set(base_keywords + extra))

    if not all_keywords:
        return False, None

    log.debug("Checking gifts for user %s, keywords: %s", user_id, all_keywords)

    try:
        owned = await bot.get_user_gifts(user_id=user_id)
    except TelegramBadRequest as e:
        log.warning("get_user_gifts failed for %s: %s", user_id, e)
        return False, None
    except AttributeError:
        log.error(
            "bot.get_user_gifts отсутствует — нужен aiogram >= 3.13 (Bot API 9.3+)."
        )
        return False, None
    except Exception as e:
        log.warning("Unexpected error in get_user_gifts for %s: %s", user_id, e)
        return False, None

    gifts = getattr(owned, "gifts", None) or []
    log.info("User %s has %d gift(s) total", user_id, len(gifts))

    for g in gifts:
        gift_type = getattr(g, "type", "unknown")
        names = _extract_names(g)
        log.debug("Gift type=%s names=%s", gift_type, names)

        if _gift_matches(g, all_keywords):
            display_name = _get_display_name(g)
            log.info("Matched gift for user %s: %s", user_id, display_name)
            return True, display_name

    log.info("No matching gift found for user %s", user_id)
    return False, None
