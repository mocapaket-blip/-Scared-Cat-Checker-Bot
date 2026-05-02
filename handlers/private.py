"""
Команды и обработчики в личных сообщениях с ботом.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from database import db
from keyboards.inline import (
    CB_CHECK_GIFTS,
    CB_DISCONNECT_WALLET,
    CB_RECHECK,
    recheck_menu,
    verification_menu,
)
from services.verification import (
    run_full_verification,
    verify_by_gift,
    verify_by_wallet,
)

router = Router(name="private")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

log = logging.getLogger(__name__)


def _format_status(user) -> str:
    if not user:
        return "Ты ещё не зарегистрирован. Войди в группу — бот добавит тебя."
    status_map = {
        "pending": "🟡 ожидание верификации",
        "verified": "🟢 верифицирован",
        "expired": "🔴 срок верификации истёк",
        "kicked": "⚫ исключён",
    }
    pretty = status_map.get(user.status, user.status)
    method = {"wallet": "TON-кошелёк", "gift": "подарок Telegram"}.get(user.method or "", "—")
    wallet = user.wallet_address or "—"
    deadline = f"{user.deadline_at:%Y-%m-%d %H:%M UTC}" if user.deadline_at else "—"
    verified = f"{user.verified_at:%Y-%m-%d %H:%M UTC}" if user.verified_at else "—"
    return (
        f"<b>Статус:</b> {pretty}\n"
        f"<b>Способ верификации:</b> {method}\n"
        f"<b>Кошелёк:</b> <code>{wallet}</code>\n"
        f"<b>Дедлайн:</b> {deadline}\n"
        f"<b>Верифицирован:</b> {verified}"
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if user is None:
        await message.answer(
            "Привет! Я слежу за участниками закрытой группы Scared Cats.\n"
            "Когда ты войдёшь в группу — здесь появится меню верификации."
        )
        return

    await message.answer(
        "Выбери способ верификации:",
        reply_markup=verification_menu(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    await message.answer(_format_status(user))


@router.message(Command("mywallet"))
async def cmd_mywallet(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user.wallet_address:
        await message.answer(
            "Кошелёк не подключён.",
            reply_markup=verification_menu(),
        )
        return
    await message.answer(
        f"Подключённый кошелёк:\n<code>{user.wallet_address}</code>\n\n"
        f"{_format_status(user)}",
        reply_markup=recheck_menu(has_wallet=True),
    )


@router.message(Command("verify"))
async def cmd_verify(message: Message, bot: Bot) -> None:
    await _do_full_check(bot, message)


@router.callback_query(F.data == CB_RECHECK)
async def cb_recheck(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Запускаю проверку…")
    await _do_full_check(bot, call.message, target_user_id=call.from_user.id)


@router.callback_query(F.data == CB_CHECK_GIFTS)
async def cb_check_gifts(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Проверяю подарки…")
    result = await verify_by_gift(bot, call.from_user.id)
    if result.ok:
        await db.mark_verified(call.from_user.id, "gift")
        await call.message.answer(
            f"✅ Найден подарок «{result.detail}». Ты верифицирован!"
        )
    else:
        user = await db.get_user(call.from_user.id)
        await call.message.answer(
            "❌ Подарок Scared Cat в профиле не найден.\n"
            "Если он у тебя есть — убедись, что подарок не скрыт, "
            "и попробуй снова. Либо подключи TON-кошелёк.",
            reply_markup=recheck_menu(has_wallet=bool(user and user.wallet_address)),
        )


@router.callback_query(F.data == CB_DISCONNECT_WALLET)
async def cb_disconnect(call: CallbackQuery) -> None:
    await db.set_wallet(call.from_user.id, "")
    await call.answer("Кошелёк отвязан", show_alert=True)
    await call.message.answer(
        "Кошелёк отвязан. Можешь подключить новый.",
        reply_markup=verification_menu(),
    )


async def _do_full_check(bot: Bot, message: Message, target_user_id: int | None = None) -> None:
    user_id = target_user_id or message.from_user.id
    result = await run_full_verification(bot, user_id)
    user = await db.get_user(user_id)

    if result.ok:
        method_text = "TON-кошелёк" if result.method == "wallet" else "подарок Telegram"
        await message.answer(
            f"✅ Верификация пройдена через <b>{method_text}</b>.\n"
            f"{_format_status(user)}"
        )
        return

    if result.error == "wallet_not_connected":
        await message.answer(
            "Кошелёк не подключён, и подарок Scared Cat в профиле не найден.\n"
            "Подключи кошелёк или попробуй ещё раз.",
            reply_markup=verification_menu(),
        )
    elif result.error == "no_nft":
        await message.answer(
            "На подключённом кошельке нет NFT из коллекции Scared Cats. "
            "Можно попробовать другой кошелёк или подарок в профиле.",
            reply_markup=recheck_menu(has_wallet=bool(user and user.wallet_address)),
        )
    elif result.error == "no_gift":
        await message.answer(
            "Подарок не найден и NFT не подтверждены. Попробуй другой способ.",
            reply_markup=recheck_menu(has_wallet=bool(user and user.wallet_address)),
        )
    else:
        await message.answer(
            f"❌ Не удалось завершить проверку: <code>{result.error}</code>",
            reply_markup=recheck_menu(has_wallet=bool(user and user.wallet_address)),
        )
