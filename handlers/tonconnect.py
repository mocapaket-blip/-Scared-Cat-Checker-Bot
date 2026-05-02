"""
TON Connect 2.0 — обработчики подключения кошелька.
API: aiogram-tonconnect 0.15.0 + tonutils 0.4.x
"""
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import ConnectWalletCallbacks

from database import db
from keyboards.inline import CB_CONNECT_WALLET, CB_DISCONNECT_WALLET, recheck_menu
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
        if atc_manager.connector.connected:
            await atc_manager.connector.disconnect_wallet()
    except Exception as e:
        log.warning("disconnect error: %s", e)
    await db.set_wallet(call.from_user.id, "")
    await call.answer("Кошелёк отвязан", show_alert=True)
    await call.message.answer("Кошелёк отвязан. Подключи новый через меню.")


async def before_wallet_connect(**data) -> None:
    log.info("before_wallet_connect: user=%s", data.get("atc_manager", {}) and
             getattr(data.get("atc_manager"), "user", {}) and
             getattr(getattr(data.get("atc_manager"), "user", None), "id", "?"))


async def after_wallet_connect(**data) -> None:
    """
    Вызывается после успешного подключения кошелька.
    atc_manager.user.wallet_address — объект Address из pytoniq_core.
    """
    atc_manager: ATCManager = data["atc_manager"]
    bot: Bot = data.get("bot")

    user_id = atc_manager.user.id

    # Получаем адрес кошелька в удобочитаемом виде
    wallet_address_obj = atc_manager.user.wallet_address
    if wallet_address_obj is None:
        log.error("Wallet connected but address is None for user %s", user_id)
        return

    # Конвертируем Address в строку (bounceable формат)
    try:
        address_str = wallet_address_obj.to_str(is_user_friendly=True, is_bounceable=False)
    except Exception:
        address_str = str(wallet_address_obj)

    log.info("Wallet connected: user=%s wallet=%s", user_id, address_str)

    # Сохраняем в БД
    await db.set_wallet(user_id, address_str)

    # Проверяем NFT
    result = await verify_by_wallet(user_id, address_str)

    if result.ok:
        await db.mark_verified(user_id, "wallet", wallet=address_str)
        text = (
            f"✅ Кошелёк подключён!\n"
            f"<code>{address_str}</code>\n\n"
            f"NFT из коллекции Scared Cats найдены.\n"
            f"<b>Ты верифицирован!</b> 🎉"
        )
    elif result.error == "no_nft":
        text = (
            f"⚠️ Кошелёк подключён:\n<code>{address_str}</code>\n\n"
            f"Но NFT из коллекции Scared Cats на нём не найдены.\n"
            f"Можно подключить другой кошелёк или проверить подарки."
        )
    else:
        text = (
            f"⚠️ Кошелёк подключён:\n<code>{address_str}</code>\n\n"
            f"Не удалось проверить NFT: <code>{result.error}</code>\n"
            f"Попробуй позже — /verify"
        )

    if bot:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=recheck_menu(has_wallet=True),
            )
        except Exception as e:
            log.warning("Cannot DM user %s after connect: %s", user_id, e)
