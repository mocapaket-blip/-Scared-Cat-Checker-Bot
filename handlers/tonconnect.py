"""
TON Connect 2.0 поверх aiogram-tonconnect.

ATCManager инжектится middleware'ом из main.py. Мы лишь
вызываем connect_wallet с двумя callback'ами и обрабатываем
успешное подключение: сохраняем адрес и запускаем проверку NFT.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import (
    AccountWallet,
    AppWallet,
    ConnectWalletCallbacks,
)

from database import db
from keyboards.inline import (
    CB_CONNECT_WALLET,
    CB_DISCONNECT_WALLET,
    recheck_menu,
)
from services.verification import verify_by_wallet

router = Router(name="tonconnect")
log = logging.getLogger(__name__)


@router.callback_query(F.data == CB_CONNECT_WALLET)
async def cb_connect_wallet(call: CallbackQuery, atc_manager: ATCManager) -> None:
    await call.answer()
    callbacks = ConnectWalletCallbacks(
        before_callback=before_wallet_connect,
        after_callback=after_wallet_connect,
    )
    await atc_manager.connect_wallet(callbacks)


@router.callback_query(F.data == CB_DISCONNECT_WALLET)
async def cb_disconnect_wallet(call: CallbackQuery, atc_manager: ATCManager) -> None:
    try:
        await atc_manager.disconnect_wallet()
    except Exception as e:
        log.warning("disconnect_wallet error: %s", e)
    await db.set_wallet(call.from_user.id, "")
    await call.answer("Кошелёк отвязан", show_alert=True)


async def before_wallet_connect(**data) -> None:
    """Вызывается до показа QR / списка кошельков."""
    log.info("before_wallet_connect: user=%s", _user_id(data))


async def after_wallet_connect(**data) -> None:
    """
    Вызывается после успешного подключения кошелька.
    aiogram-tonconnect передаёт сюда: atc_manager, app_wallet, account_wallet,
    event_from_user и пр. Принимаем **data, чтобы быть устойчивыми к
    возможным изменениям сигнатуры между версиями библиотеки.
    """
    atc_manager: ATCManager = data["atc_manager"]
    account_wallet: AccountWallet = data.get("account_wallet") or atc_manager.user.account_wallet
    app_wallet: AppWallet | None = data.get("app_wallet") or atc_manager.user.app_wallet

    user_id = _user_id(data) or atc_manager.user.id
    address = account_wallet.address

    log.info("Wallet connected: user=%s wallet=%s app=%s",
             user_id, address, getattr(app_wallet, "name", "?"))

    await db.set_wallet(user_id, address)

    result = await verify_by_wallet(user_id, address)
    if result.ok:
        await db.mark_verified(user_id, "wallet", wallet=address)
        text = (
            f"✅ Кошелёк подключён: <code>{address}</code>\n"
            f"NFT из коллекции Scared Cats найдены.\n"
            f"<b>Ты верифицирован!</b>"
        )
    elif result.error == "no_nft":
        text = (
            f"⚠️ Кошелёк подключён: <code>{address}</code>\n"
            f"Но NFT из коллекции Scared Cats на нём не найдены.\n"
            f"Можно подключить другой кошелёк или попробовать "
            f"проверку через подарок Telegram."
        )
    else:
        text = (
            f"⚠️ Кошелёк подключён: <code>{address}</code>\n"
            f"Не удалось проверить NFT: <code>{result.error}</code>\n"
            f"Попробуй позже командой /verify."
        )

    bot: Bot = data.get("bot") or atc_manager.bot
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=recheck_menu(has_wallet=True),
        )
    except Exception as e:
        log.warning("Cannot send post-connect message: %s", e)


def _user_id(data: dict) -> int | None:
    user = data.get("event_from_user") or data.get("from_user")
    return user.id if user else None
