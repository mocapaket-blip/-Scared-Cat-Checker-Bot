"""
TON Connect 2.0 — обработчики подключения кошелька.
API: aiogram-tonconnect 0.15.0 + tonutils 0.4.x

bot хранится как модульная переменная (init_bot вызывается из main.py),
потому что aiogram-tonconnect callbacks вызываются вне стандартного
middleware-контекста и bot не попадает в **data.
"""
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram_tonconnect import ATCManager
from aiogram_tonconnect.tonconnect.models import ConnectWalletCallbacks

from database import db
from keyboards.inline import CB_CONNECT_WALLET, CB_DISCONNECT_WALLET, recheck_menu
from services.verification import unrestrict_in_group, verify_by_wallet

router = Router(name="tonconnect")
log = logging.getLogger(__name__)

# Глобальная ссылка на bot — задаётся из main.py через init_bot()
_bot: Optional[Bot] = None


def init_bot(bot: Bot) -> None:
    """Вызывается из main.py сразу после создания Bot."""
    global _bot
    _bot = bot
    log.info("tonconnect: bot reference initialized (id=%s)", bot.id)


def _get_bot(data: dict) -> Optional[Bot]:
    """Возвращает bot из data или из глобальной переменной."""
    return (
        data.get("bot")
        or getattr(data.get("atc_manager"), "bot", None)
        or getattr(data.get("atc_manager"), "_bot", None)
        or _bot
    )


# ─────────────────────────── callback handlers ──────────────────────────────

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


# ──────────────────────────── TC callbacks ───────────────────────────────────

async def before_wallet_connect(**data) -> None:
    pass


async def after_wallet_connect(**data) -> None:
    """
    Вызывается aiogram-tonconnect после успешного подключения кошелька.
    Всё оборачиваем в try/except — ошибка здесь убивает update без трейсбека.
    """
    try:
        await _after_wallet_connect_impl(**data)
    except Exception as e:
        log.exception("after_wallet_connect CRASHED: %s", e)


async def _after_wallet_connect_impl(**data) -> None:
    atc_manager: ATCManager = data["atc_manager"]
    bot = _get_bot(data)
    user_id = atc_manager.user.id

    log.info(
        "after_wallet_connect: user=%s, bot_available=%s",
        user_id, bot is not None,
    )

    # Адрес кошелька
    wallet_address_obj = atc_manager.user.wallet_address
    if wallet_address_obj is None:
        log.error("Wallet address is None for user %s", user_id)
        if bot:
            await bot.send_message(
                user_id,
                "⚠️ Кошелёк подключился, но адрес не получен. Попробуй ещё раз.",
                reply_markup=recheck_menu(has_wallet=False),
            )
        return

    try:
        address_str = wallet_address_obj.to_str(is_user_friendly=True, is_bounceable=False)
    except Exception:
        address_str = str(wallet_address_obj)

    log.info("Wallet address for user %s: %s", user_id, address_str)

    # Сохраняем в БД
    await db.set_wallet(user_id, address_str)

    # Проверяем NFT
    result = await verify_by_wallet(user_id, address_str)
    log.info("verify_by_wallet result for %s: ok=%s error=%s", user_id, result.ok, result.error)

    if result.ok:
        await db.mark_verified(user_id, "wallet", wallet=address_str)
        if bot:
            await unrestrict_in_group(bot, user_id)
        text = (
            "✅ <b>Верификация пройдена!</b>\n\n"
            f"Кошелёк: <code>{address_str}</code>\n\n"
            "NFT из коллекции Scared Cats найдены. "
            "Ты верифицирован — теперь можешь писать в группе! 🎉"
        )
        markup = recheck_menu(has_wallet=True)

    elif result.error == "no_nft":
        text = (
            "⚠️ <b>Кошелёк подключён:</b>\n"
            f"<code>{address_str}</code>\n\n"
            "NFT из коллекции Scared Cats на этом кошельке <b>не найдены</b>.\n\n"
            "Что можно сделать:\n"
            "• Отключить кошелёк и подключить другой\n"
            "• Проверить подарки Telegram"
        )
        markup = recheck_menu(has_wallet=True)

    else:
        text = (
            "⚠️ <b>Кошелёк подключён:</b>\n"
            f"<code>{address_str}</code>\n\n"
            f"Не удалось проверить NFT: <code>{result.error}</code>\n"
            "Попробуй нажать «Запустить проверку» ещё раз."
        )
        markup = recheck_menu(has_wallet=True)

    if bot:
        try:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
        except Exception as e:
            log.warning("Cannot DM user %s after connect: %s", user_id, e)
    else:
        log.error(
            "bot is None in after_wallet_connect for user %s — "
            "call init_bot(bot) from main.py!", user_id,
        )
