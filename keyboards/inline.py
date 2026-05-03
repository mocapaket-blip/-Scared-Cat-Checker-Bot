from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

# URL мини-приложения (GitHub Pages)
WEBAPP_URL = "https://mocapaket-blip.github.io/-Scared-Cat-Checker-Bot/app.html"

# Callback constants
CB_CHECK_GIFT        = "verify:check_gift"
CB_RECHECK           = "verify:recheck"
CB_DISCONNECT_WALLET = "verify:disconnect_wallet"


def verification_menu() -> InlineKeyboardMarkup:
    """
    Главное меню верификации.
      • Подарок проверяется прямо в боте (без Mini App).
      • Кошелёк подключается через Mini App (TON Connect в браузере).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Проверить подарок Telegram", callback_data=CB_CHECK_GIFT)
    kb.button(
        text="🔗 Подключить TON-кошелёк",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )
    kb.adjust(1)
    return kb.as_markup()


def recheck_menu(has_wallet: bool) -> InlineKeyboardMarkup:
    """Меню повторной проверки после неудачи или при наличии кошелька."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Проверить подарок ещё раз", callback_data=CB_CHECK_GIFT)
    kb.button(
        text="🔗 Подключить кошелёк (другой)",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )
    if has_wallet:
        kb.button(text="🔄 Перепроверить кошелёк", callback_data=CB_RECHECK)
        kb.button(text="❌ Отвязать кошелёк", callback_data=CB_DISCONNECT_WALLET)
    kb.adjust(1)
    return kb.as_markup()


def group_verify_button(bot_username: str) -> InlineKeyboardMarkup:
    """Кнопка в группе — ссылка на deep link бота (web_app работает только в ЛС)."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔑 Верифицироваться сейчас",
        url=f"https://t.me/{bot_username}?start=verify",
    )
    kb.adjust(1)
    return kb.as_markup()


def group_existing_button(bot_username: str) -> InlineKeyboardMarkup:
    """Кнопка в объявлении для существующих участников."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔑 ВЕРИФИЦИРОВАТЬСЯ СЕЙЧАС",
        url=f"https://t.me/{bot_username}?start=verify_existing",
    )
    kb.adjust(1)
    return kb.as_markup()
