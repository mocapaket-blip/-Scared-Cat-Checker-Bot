from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


CB_CONNECT_WALLET = "verify:connect_wallet"
CB_CHECK_GIFTS = "verify:check_gifts"
CB_DISCONNECT_WALLET = "verify:disconnect_wallet"
CB_RECHECK = "verify:recheck"


def verification_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Подключить TON-кошелёк", callback_data=CB_CONNECT_WALLET)
    kb.button(text="Проверить подарки в профиле", callback_data=CB_CHECK_GIFTS)
    kb.adjust(1)
    return kb.as_markup()


def recheck_menu(has_wallet: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Запустить проверку", callback_data=CB_RECHECK)
    if has_wallet:
        kb.button(text="Отключить кошелёк", callback_data=CB_DISCONNECT_WALLET)
    else:
        kb.button(text="Подключить TON-кошелёк", callback_data=CB_CONNECT_WALLET)
    kb.button(text="Проверить подарки", callback_data=CB_CHECK_GIFTS)
    kb.adjust(1)
    return kb.as_markup()
