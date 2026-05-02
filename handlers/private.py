"""
Команды и обработчики в личных сообщениях с ботом.
Поддерживает deep links:
  • /start verify           — для новых участников (после join)
  • /start verify_existing  — для уже состоящих участников
"""
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import settings
from database import db
from keyboards.inline import (
    CB_CANCEL,
    CB_CHECK_GIFTS,
    CB_DISCONNECT_WALLET,
    CB_MANUAL_WALLET,
    CB_RECHECK,
    cancel_menu,
    recheck_menu,
    verification_menu,
)
from services.ton_api import TonApiError, user_owns_collection_nft
from services.verification import (
    run_full_verification,
    unrestrict_in_group,
    verify_by_gift,
)

router = Router(name="private")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

log = logging.getLogger(__name__)


class WalletInput(StatesGroup):
    """FSM-state для ручного ввода адреса кошелька."""
    waiting_address = State()


# Базовая валидация TON-адреса:
# • EQ... / UQ... — user-friendly base64 (48 символов)
# • 0:... — raw hex
TON_ADDRESS_RE = re.compile(
    r"^("
    r"(?:EQ|UQ|kQ|0Q)[A-Za-z0-9_\-]{46}"   # user-friendly
    r"|"
    r"-?\d:[A-Fa-f0-9]{64}"                 # raw
    r")$"
)


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


# ──────────────────────────── /start ─────────────────────────────────────────

@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, bot: Bot) -> None:
    payload = (command.args or "").strip().lower()
    user = message.from_user

    if payload == "verify_existing":
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

    user_row = await db.get_user(user.id)
    if user_row is None:
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
async def cmd_start_plain(message: Message, state: FSMContext) -> None:
    await state.clear()  # Сбрасываем любые висящие FSM-состояния
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


# ─────────────────────── ручной ввод кошелька ────────────────────────────────

@router.callback_query(F.data == CB_MANUAL_WALLET)
async def cb_manual_wallet(call: CallbackQuery, state: FSMContext) -> None:
    """Запускает FSM-flow для ручного ввода адреса кошелька."""
    await call.answer()
    await state.set_state(WalletInput.waiting_address)
    await call.message.answer(
        "✍️ <b>Введи адрес TON-кошелька</b>\n\n"
        "Отправь сообщением адрес в формате:\n"
        "<code>EQ...</code> или <code>UQ...</code>\n\n"
        "Пример:\n"
        "<code>EQAbC1d2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3aB4cD5</code>\n\n"
        "Адрес можно скопировать из своего TON-кошелька (Tonkeeper, MyTonWallet и др.).",
        reply_markup=cancel_menu(),
    )


@router.callback_query(F.data == CB_CANCEL)
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer("Отменено")
    await call.message.answer(
        "Отменено. Выбери способ верификации:",
        reply_markup=verification_menu(),
    )


@router.message(WalletInput.waiting_address)
async def on_wallet_address(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обработчик ручного ввода адреса кошелька."""
    raw = (message.text or "").strip()

    if not TON_ADDRESS_RE.match(raw):
        await message.answer(
            "❌ Это не похоже на TON-адрес.\n\n"
            "Адрес должен начинаться с <code>EQ</code>, <code>UQ</code>, "
            "<code>kQ</code> или <code>0Q</code> и быть длиной 48 символов.\n\n"
            "Попробуй ещё раз или нажми отмену.",
            reply_markup=cancel_menu(),
        )
        return

    await state.clear()

    # Сохраняем адрес и проверяем NFT
    user_id = message.from_user.id
    await db.set_wallet(user_id, raw)

    progress = await message.answer(
        f"🔍 Проверяю кошелёк:\n<code>{raw}</code>\n\nПодожди…"
    )

    try:
        owns = await user_owns_collection_nft(raw)
    except TonApiError as e:
        await progress.edit_text(
            f"💥 Ошибка проверки через tonapi:\n<code>{e}</code>\n\n"
            f"Попробуй позже.",
            reply_markup=recheck_menu(has_wallet=True),
        )
        return

    if owns:
        await db.mark_verified(user_id, "wallet", wallet=raw)
        await unrestrict_in_group(bot, user_id)
        await progress.edit_text(
            f"✅ <b>Верификация пройдена!</b>\n\n"
            f"Кошелёк: <code>{raw}</code>\n\n"
            f"NFT из коллекции Scared Cats найдены. "
            f"Права в группе восстановлены — можешь писать! 🎉"
        )
    else:
        user = await db.get_user(user_id)
        await progress.edit_text(
            f"⚠️ Кошелёк сохранён:\n<code>{raw}</code>\n\n"
            f"Но NFT из коллекции Scared Cats на нём <b>не найдены</b>.\n\n"
            f"Можно ввести другой адрес или проверить подарки.",
            reply_markup=recheck_menu(has_wallet=True),
        )


# ──────────────────────────── callbacks ──────────────────────────────────────

@router.callback_query(F.data == CB_RECHECK)
async def cb_recheck(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Запускаю проверку…")
    await _do_full_check(bot, call.message, target_user_id=call.from_user.id)


@router.callback_query(F.data == CB_CHECK_GIFTS)
async def cb_check_gifts(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Проверяю подарки…")
    try:
        result = await verify_by_gift(bot, call.from_user.id)
    except Exception as e:
        log.exception("verify_by_gift crashed for %s: %s", call.from_user.id, e)
        await call.message.answer(
            f"💥 Ошибка при проверке подарков: <code>{e}</code>\n\n"
            f"Попробуй позже или подключи кошелёк.",
            reply_markup=verification_menu(),
        )
        return

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
            "❌ Подарок Scared Cat в профиле не найден.\n\n"
            "Возможные причины:\n"
            "• У тебя действительно нет такого подарка\n"
            "• Подарок есть в другом аккаунте\n"
            "• В настройках Telegram запрещён доступ к подаркам "
            "(Настройки → Конфиденциальность → Подарки и Stars → "
            "«Кто видит мои подарки» = «Все»)\n\n"
            "Попробуй ещё раз или подключи TON-кошелёк.",
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
