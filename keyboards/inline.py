from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

# URL мини-приложения (GitHub Pages)
WEBAPP_URL = "https://mocapaket-blip.github.io/-Scared-Cat-Checker-Bot/app.html"

CB_RECHECK         = "verify:recheck"
CB_DISCONNECT_WALLET = "verify:disconnect_wallet"


def verification_menu() -> InlineKeyboardMarkup:
    """Главное меню верификации — открывает Mini App."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔐 Верифицироваться",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )
    kb.adjust(1)
    return kb.as_markup()


def recheck_menu(has_wallet: bool) -> InlineKeyboardMarkup:
    """Меню повторной проверки после неудачи или при наличии кошелька."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔄 Открыть верификацию снова",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )
    if has_wallet:
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
