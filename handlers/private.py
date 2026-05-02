"""
Команды и обработчики в личных сообщениях с ботом.
Поддерживает deep links:
  • /start verify           — для новых участников (после join)
  • /start verify_existing  — для уже состоящих участников
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from config import settings
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
    unrestrict_in_group,
    verify_by_gift,
)

router = Router(name="private")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

log = logging.getLogger(__name__)


def _full_name(u) -> str:
    parts = [u.first_name or "", u.last_name or ""]
    return " ".join(p for p in parts if p).strip() or (u.username or str(u.id))


def _format_status(user) -> str:
    if not user:
        return (
            "Ты ещё не зарегистрирован.\n"
            "Войди в группу или нажми «Верифицироваться сейчас» в группе — "
            "и снова напиши /start."
        )
    status_map = {
        "pending": "🟡 ожидание верификации",
        "verified": "🟢 верифицирован",
        "expired": "🔴 срок верификации истёк",
        "kicked": "⚫ исключён",
    }
    pretty = status_map.get(user.status, user.status)
    method = {"wallet": "TON-кошелёк", "gift": "подарок Telegram"}.get(user.method or "", "—")
    wallet = user.wallet_address or "—"
    deadline = f"{user.deadline_at:%Y-%m-%d %H:%M %Z}" if user.deadline_at else "—"
    verified = f"{user.verified_at:%Y-%m-%d %H:%M %Z}" if user.verified_at else "—"
    return (
        f"<b>Статус:</b> {pretty}\n"
        f"<b>Способ верификации:</b> {method}\n"
        f"<b>Кошелёк:</b> <code>{wallet}</code>\n"
        f"<b>Дедлайн:</b> {deadline}\n"
        f"<b>Верифицирован:</b> {verified}"
    )


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, bot: Bot) -> None:
    payload = (command.args or "").strip().lower()
    user = message.from_user

    if payload == "verify_existing":
        # Регистрируем как existing с фиксированным дедлайном
        await db.upsert_pending_user(
            user_id=user.id,
            username=user.username,
            full_name=_full_name(user),
            is_existing=True,
            deadline=settings.existing_deadline,
        )
        await message.answer(
            f"👋 Привет, <b>{_full_name(user)}</b>!\n\n"
            f"Чат <b>Scared Cats</b> теперь только для владельцев NFT/подарков "
            f"коллекции.\n\n"
            f"Дедлайн верификации: <code>"
            f"{settings.existing_deadline.strftime('%d.%m.%Y %H:%M %Z')}"
            f"</code>\n\n"
            f"Выбери способ верификации:",
            reply_markup=verification_menu(),
        )
        return

    # payload == "verify" или любой другой — стандартный путь для новых участников
    user_row = await db.get_user(user.id)
    if user_row is None:
        # Если deep link verify, но в БД ещё нет — создадим pending
        await db.upsert_pending_user(
            user_id=user.id,
            username=user.username,
            full_name=_full_name(user),
            is_existing=False,
        )

    await message.answer(
        f"👋 Привет, <b>{_full_name(user)}</b>!\n\n"
        f"Выбери способ верификации:",
        reply_markup=verification_menu(),
    )


@router.message(CommandStart())
async def cmd_start_plain(message: Message) -> None:
    user = message.from_user
    user_row = await db.get_user(user.id)

    if user_row is None:
        await message.answer(
            "Привет! Я слежу за участниками закрытой группы Scared Cats.\n\n"
            "Если ты вошёл в группу или есть закреплённое сообщение от меня — "
            "нажми кнопку «Верифицироваться сейчас» в группе."
        )
        return

    await message.answer(
        f"С возвращением!\n\n{_format_status(user_row)}\n\nВыбери действие:",
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
        await unrestrict_in_group(bot, call.from_user.id)
        await call.message.answer(
            f"✅ Найден подарок «{result.detail}». Ты верифицирован!\n"
            f"Права в группе восстановлены."
        )
    else:
        user = await db.get_user(call.from_user.id)
        await call.message.answer(
            "❌ Подарок Scared Cat в профиле не найден.\n"
            "Если он у тебя есть — попробуй снова. "
            "Либо подключи TON-кошелёк.",
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
            f"Права в группе восстановлены.\n\n"
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
