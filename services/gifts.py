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

# Все варианты написания названия коллекции
_EXTRA_KEYWORDS = ["scared cats", "scaredcats", "scared_cat", "scared_cats"]


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

    candidates.append(_safe_lower(getattr(gift, "name", None)))
    candidates.append(_safe_lower(getattr(gift, "base_name", None)))
    candidates.append(_safe_lower(getattr(gift, "title", None)))

    return [c for c in candidates if c]


def _gift_type(gift) -> str:
    return getattr(gift, "type", "unknown")


def _gift_matches(gift, keywords: Iterable[str]) -> bool:
    """
    Проверяет unique и regular подарки.
    is_saved НЕ проверяется — подарок валиден даже если скрыт.
    """
    names = _extract_names(gift)
    return any(_matches_keywords(n, keywords) for n in names)


def _get_display_name(gift) -> str:
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


async def _fetch_all_gifts(bot: Bot, user_id: int) -> List:
    """Забирает ВСЕ подарки пользователя с пагинацией."""
    all_gifts = []
    offset: Optional[str] = None

    while True:
        kwargs = {"user_id": user_id, "limit": 100}
        if offset:
            kwargs["offset"] = offset

        try:
            owned = await bot.get_user_gifts(**kwargs)
        except TelegramBadRequest as e:
            log.warning("get_user_gifts failed for %s (offset=%s): %s", user_id, offset, e)
            break
        except AttributeError:
            log.error("bot.get_user_gifts отсутствует — нужен aiogram >= 3.13 (Bot API 9.3+)")
            break
        except Exception as e:
            log.warning("Unexpected error in get_user_gifts for %s: %s", user_id, e)
            break

        batch = getattr(owned, "gifts", None) or []
        all_gifts.extend(batch)
        log.debug("Fetched %d gifts (batch), total so far: %d", len(batch), len(all_gifts))

        # Пагинация
        next_offset = getattr(owned, "next_offset", None)
        if not next_offset or not batch:
            break
        offset = next_offset

    return all_gifts


async def user_has_collection_gift(
    bot: Bot,
    user_id: int,
    keywords: Optional[Iterable[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Возвращает (has_gift, matched_name)."""
    base_keywords = list(keywords or settings.gift_keywords_list)
    all_keywords = list(set(base_keywords + _EXTRA_KEYWORDS))

    if not all_keywords:
        return False, None

    log.info("Checking gifts for user %s, keywords: %s", user_id, all_keywords)

    gifts = await _fetch_all_gifts(bot, user_id)
    log.info("User %s total gifts: %d", user_id, len(gifts))

    for g in gifts:
        gtype = _gift_type(g)
        names = _extract_names(g)
        log.info("  Gift type=%s names=%s", gtype, names)
        if _gift_matches(g, all_keywords):
            display = _get_display_name(g)
            log.info("  MATCHED: %s", display)
            return True, display

    log.info("No matching gift found for user %s", user_id)
    return False, None


async def get_user_gifts_debug(bot: Bot, user_id: int) -> str:
    """
    Возвращает человекочитаемый список всех подарков пользователя.
    Используется в /debug_gifts для диагностики.
    """
    gifts = await _fetch_all_gifts(bot, user_id)
    if not gifts:
        return "Подарков нет (или API вернул пустой список)"

    lines = [f"Всего подарков: <b>{len(gifts)}</b>\n"]
    for i, g in enumerate(gifts, 1):
        gtype = _gift_type(g)
        names = _extract_names(g)
        lines.append(f"{i}. type=<code>{gtype}</code> names=<code>{names}</code>")

    return "\n".join(lines)
