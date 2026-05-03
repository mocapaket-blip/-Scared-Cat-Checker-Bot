"""
Обработчики личных сообщений с ботом.

Deep links:
  /start verify           — новые участники после join
  /start verify_existing  — существующие участники
"""
import json
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import settings
from database import db
from keyboards.inline import (
    CB_DISCONNECT_WALLET,
    CB_RECHECK,
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


def _full_name(u) -> str:
    parts = [u.first_name or "", u.last_name or ""]
    return " ".join(p for p in parts if p).strip() or (u.username or str(u.id))


def _format_status(user) -> str:
    if not user:
        return (
            "Ты ещё не зарегистрирован.\n"
            "Войди в группу или нажми кнопку верификации в группе."
        )
    status_map = {
        "pending":  "🟡 ожидание верификации",
        "verified": "🟢 верифицирован",
        "expired":  "🔴 срок верификации истёк",
        "kicked":   "⚫ исключён",
    }
    pretty   = status_map.get(user.status, user.status)
    method   = {"wallet": "TON-кошелёк", "gift": "подарок Telegram"}.get(user.method or "", "—")
    wallet   = user.wallet_address or "—"
    deadline = f"{user.deadline_at:%Y-%m-%d %H:%M %Z}"  if user.deadline_at  else "—"
    verified = f"{user.verified_at:%Y-%m-%d %H:%M %Z}"  if user.verified_at  else "—"
    return (
        f"<b>Статус:</b> {pretty}\n"
        f"<b>Способ:</b> {method}\n"
        f"<b>Кошелёк:</b> <code>{wallet}</code>\n"
        f"<b>Дедлайн:</b> {deadline}\n"
        f"<b>Верифицирован:</b> {verified}"
    )


# ──────────────────────────── /start ─────────────────────────────

@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject) -> None:
    payload = (command.args or "").strip().lower()
    user    = message.from_user

    if payload == "verify_existing":
        await db.upsert_pending_user(
            user_id=user.id, username=user.username,
            full_name=_full_name(user), is_existing=True,
            deadline=settings.existing_deadline,
        )
        await message.answer(
            f"👋 Привет, <b>{_full_name(user)}</b>!\n\n"
            f"Чат <b>Scared Cats</b> теперь только для владельцев NFT/подарков.\n\n"
            f"Дедлайн: <code>{settings.existing_deadline.strftime('%d.%m.%Y %H:%M %Z')}</code>\n\n"
            f"Нажми кнопку — откроется мини-приложение для верификации:",
            reply_markup=verification_menu(),
        )
        return

    # verify или что угодно ещё — стандартный путь
    user_row = await db.get_user(user.id)
    if user_row is None:
        await db.upsert_pending_user(
            user_id=user.id, username=user.username,
            full_name=_full_name(user), is_existing=False,
        )
    await message.answer(
        f"👋 Привет, <b>{_full_name(user)}</b>!\n\n"
        f"Нажми кнопку — откроется мини-приложение для верификации:",
        reply_markup=verification_menu(),
    )


@router.message(CommandStart())
async def cmd_start_plain(message: Message, state: FSMContext) -> None:
    await state.clear()
    user     = message.from_user
    user_row = await db.get_user(user.id)

    if user_row is None:
        await message.answer(
            f"👋 Привет, <b>{_full_name(user)}</b>!\n\n"
            f"Нажми кнопку, чтобы пройти верификацию:",
            reply_markup=verification_menu(),
        )
        return

    await message.answer(
        f"С возвращением, <b>{_full_name(user)}</b>!\n\n{_format_status(user_row)}\n\n"
        f"Нажми кнопку для верификации:",
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
        await message.answer("Кошелёк не подключён.", reply_markup=verification_menu())
        return
    await message.answer(
        f"Подключённый кошелёк:\n<code>{user.wallet_address}</code>\n\n"
        f"{_format_status(user)}",
        reply_markup=recheck_menu(has_wallet=True),
    )


# ─────────────────── web_app_data (Mini App) ─────────────────────

@router.message(F.web_app_data)
async def on_web_app_data(message: Message, bot: Bot) -> None:
    """Получаем данные из Mini App и запускаем верификацию."""
    user_id = message.from_user.id

    try:
        data   = json.loads(message.web_app_data.data)
        action = data.get("action", "")
    except Exception as e:
        log.warning("Bad web_app_data from %s: %s", user_id, e)
        await message.answer("❌ Получены некорректные данные. Попробуй снова.", reply_markup=verification_menu())
        return

    log.info("web_app_data from %s: action=%s", user_id, action)

    # ── Проверка подарка ──────────────────────────────────────────
    if action == "check_gift":
        msg = await message.answer("🔍 Проверяю подарки в твоём профиле…")
        try:
            result = await verify_by_gift(bot, user_id)
        except Exception as e:
            log.exception("verify_by_gift error for %s: %s", user_id, e)
            await msg.edit_text(
                f"💥 Ошибка при проверке подарков: <code>{e}</code>\n\n"
                "Попробуй снова или подключи кошелёк.",
                reply_markup=verification_menu(),
            )
            return

        if result.ok:
            await db.mark_verified(user_id, "gift")
            await unrestrict_in_group(bot, user_id)
            await msg.edit_text(
                f"✅ <b>Верификация пройдена!</b>\n\n"
                f"Найден подарок «{result.detail}».\n"
                f"Права в группе восстановлены — можешь писать! 🎉"
            )
        else:
            user = await db.get_user(user_id)
            await msg.edit_text(
                "❌ <b>Подарок Scared Cat не найден.</b>\n\n"
                "Возможные причины:\n"
                "• У тебя нет подарка Scared Cat в этом аккаунте\n"
                "• Настройки приватности скрывают подарки от ботов:\n"
                "  <i>Настройки → Конфиденциальность → Подарки и Stars\n"
                "  → «Кто видит мои подарки» = Все</i>\n\n"
                "Попробуй подключить TON-кошелёк.",
                reply_markup=recheck_menu(has_wallet=bool(user and user.wallet_address)),
            )
        return

    # ── Верификация по кошельку ───────────────────────────────────
    if action == "wallet":
        raw_address = (data.get("address") or "").strip()
        if not raw_address:
            await message.answer(
                "❌ Адрес кошелька не получен. Попробуй снова.",
                reply_markup=verification_menu(),
            )
            return

        log.info("Wallet address from mini app for %s: %s", user_id, raw_address)

        # Сохраняем адрес
        await db.set_wallet(user_id, raw_address)

        msg = await message.answer(
            f"🔍 Проверяю кошелёк:\n<code>{raw_address}</code>\n\nПодожди…"
        )

        # Адрес из TON Connect может быть в raw-формате (0:hex).
        # quote() нужен чтобы не сломать URL tonapi.
        try:
            encoded = quote(raw_address, safe="")
            owns    = await user_owns_collection_nft(raw_address, encoded_address=encoded)
        except TonApiError as e:
            await msg.edit_text(
                f"💥 Ошибка запроса к tonapi:\n<code>{e}</code>\n\n"
                "Попробуй снова позже.",
                reply_markup=recheck_menu(has_wallet=True),
            )
            return

        if owns:
            await db.mark_verified(user_id, "wallet", wallet=raw_address)
            await unrestrict_in_group(bot, user_id)
            await msg.edit_text(
                "✅ <b>Верификация пройдена!</b>\n\n"
                f"Кошелёк: <code>{raw_address}</code>\n\n"
                "NFT из коллекции Scared Cats найдены.\n"
                "Права в группе восстановлены — можешь писать! 🎉"
            )
        else:
            user = await db.get_user(user_id)
            await msg.edit_text(
                f"⚠️ Кошелёк <code>{raw_address}</code>\n\n"
                "NFT из коллекции Scared Cats на нём <b>не найдены</b>.\n\n"
                "Попробуй другой кошелёк или проверь подарок.",
                reply_markup=recheck_menu(has_wallet=True),
            )
        return

    # Неизвестный action
    log.warning("Unknown web_app action=%s from %s", action, user_id)
    await message.answer("Неизвестное действие. Попробуй снова.", reply_markup=verification_menu())


# ────────────────────── callback buttons ─────────────────────────

@router.callback_query(F.data == CB_RECHECK)
async def cb_recheck(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Запускаю проверку…")
    await _do_full_check(bot, call.message, target_user_id=call.from_user.id)


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
    result  = await run_full_verification(bot, user_id)
    user    = await db.get_user(user_id)

    if result.ok:
        method_text = "TON-кошелёк" if result.method == "wallet" else "подарок Telegram"
        await message.answer(
            f"✅ Верификация пройдена через <b>{method_text}</b>.\n"
            f"Права в группе восстановлены.\n\n{_format_status(user)}"
        )
        return

    has_wallet = bool(user and user.wallet_address)
    msgs = {
        "wallet_not_connected": ("Кошелёк не подключён, и подарок не найден.", verification_menu()),
        "no_nft": ("На кошельке нет NFT Scared Cats.", recheck_menu(has_wallet)),
        "no_gift": ("Подарок не найден. Попробуй другой способ.", recheck_menu(has_wallet)),
    }
    text, markup = msgs.get(result.error or "", (f"Ошибка: <code>{result.error}</code>", recheck_menu(has_wallet)))
    await message.answer(text, reply_markup=markup)
