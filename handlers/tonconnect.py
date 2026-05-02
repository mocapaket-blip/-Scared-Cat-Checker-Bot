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
from services.verification import unrestrict_in_group, verify_by_wallet

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
    pass


async def after_wallet_connect(**data) -> None:
    """
    Вызывается после успешного подключения кошелька.
    Сохраняет адрес, проверяет NFT, снимает restrict если верифицирован.
    """
    atc_manager: ATCManager = data["atc_manager"]

    # Получаем bot из data или из atc_manager
    bot: Bot = data.get("bot") or getattr(atc_manager, "bot", None)

    user_id = atc_manager.user.id

    # Получаем адрес кошелька
    wallet_address_obj = atc_manager.user.wallet_address
    if wallet_address_obj is None:
        log.error("Wallet connected but address is None for user %s", user_id)
        return

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

        # ✅ СНИМАЕМ RESTRICT В ГРУППЕ
        if bot:
            await unrestrict_in_group(bot, user_id)

        text = (
            f"✅ <b>Кошелёк подключён и верификация пройдена!</b>\n\n"
            f"<code>{address_str}</code>\n\n"
            f"NFT из коллекции Scared Cats найдены. "
            f"Ты верифицирован — теперь можешь писать в группе! 🎉"
        )

    elif result.error == "no_nft":
        text = (
            f"⚠️ <b>Кошелёк подключён:</b>\n"
            f"<code>{address_str}</code>\n\n"
            f"Но NFT из коллекции Scared Cats на нём <b>не найдены</b>.\n\n"
            f"Что можно сделать:\n"
            f"• Подключить другой кошелёк\n"
            f"• Проверить подарки Telegram"
        )

    else:
        text = (
            f"⚠️ <b>Кошелёк подключён:</b>\n"
            f"<code>{address_str}</code>\n\n"
            f"Не удалось проверить NFT: <code>{result.error}</code>\n"
            f"Попробуй нажать «Запустить проверку» ещё раз."
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
    else:
        log.error("bot is None in after_wallet_connect for user %s — cannot send DM", user_id)
