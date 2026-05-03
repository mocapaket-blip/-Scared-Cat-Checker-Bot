"""
Админ-команды (доступ только ADMIN_ID).

Команды:
  /start_verification_existing — публикует и закрепляет видео-объявление
                                 для уже состоящих участников
  /fullverify                  — немедленный запуск полной проверки всех pending
  /verify @username            — точечная проверка одного пользователя
  /admin_stats                 — статистика
  /admin_help                  — список команд
"""
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

from config import BASE_DIR, settings
from database import db
from keyboards.inline import group_existing_button
from services.gifts import get_user_gifts_debug
from services.verification import run_full_verification, unrestrict_in_group

router = Router(name="admin")
router.message.filter(F.from_user.id == settings.ADMIN_ID)

log = logging.getLogger(__name__)


EXISTING_TEXT = (
    "⚠️ <b>ВНИМАНИЕ, СУЩЕСТВУЮЩИМ УЧАСТНИКАМ!</b>\n\n"
    "С сегодняшнего дня чат — только для владельцев Scared Cat. "
    "У вас есть ровно <b>7 дней</b> на верификацию (до <b>09.05.2026</b>). "
    "Кто не пройдёт — потеряет своё место в чате. "
    "Нажмите кнопку ниже и подтвердите владение NFT.\n\n"
    "Спасибо за понимание!"
)

VIDEO_FILENAME = "scared_cat_checker_video.mp4"


# ─────────────────────── /start_verification_existing ───────────────────────

@router.message(Command("start_verification_existing"))
async def cmd_start_verification_existing(message: Message, bot: Bot) -> None:
    """Публикует и закрепляет видео-объявление в группе."""
    me = await bot.get_me()
    kb = group_existing_button(me.username)

    video_path = BASE_DIR / VIDEO_FILENAME
    sent = None

    if video_path.exists():
        try:
            sent = await bot.send_video(
                chat_id=settings.GROUP_ID,
                video=FSInputFile(str(video_path)),
                caption=EXISTING_TEXT,
                reply_markup=kb,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            await message.answer(
                f"❌ Не удалось отправить видео в группу:\n<code>{e}</code>\n\n"
                f"Проверь, что бот добавлен в группу <code>{settings.GROUP_ID}</code> "
                f"как админ."
            )
            return
    else:
        log.warning("Video file not found: %s — sending text-only message", video_path)
        await message.answer(
            f"⚠️ Файл <code>{VIDEO_FILENAME}</code> не найден в папке бота.\n"
            f"Отправляю сообщение без видео."
        )
        try:
            sent = await bot.send_message(
                chat_id=settings.GROUP_ID,
                text=EXISTING_TEXT,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            await message.answer(
                f"❌ Не удалось отправить сообщение в группу:\n<code>{e}</code>"
            )
            return

    pinned_ok = False
    try:
        await bot.pin_chat_message(
            chat_id=settings.GROUP_ID,
            message_id=sent.message_id,
            disable_notification=False,
        )
        pinned_ok = True
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.warning("Cannot pin message: %s", e)

    deadline_str = settings.existing_deadline.strftime("%d.%m.%Y %H:%M %Z")
    pinned_status = (
        "📌 закреплено" if pinned_ok
        else "⚠️ <b>НЕ закреплено</b> (нет прав can_pin_messages)"
    )

    await message.answer(
        f"✅ Сообщение для существующих участников опубликовано.\n"
        f"{pinned_status}\n\n"
        f"<b>Дедлайн:</b> <code>{deadline_str}</code>\n\n"
        f"Все, кто нажмёт кнопку, появятся в БД со статусом pending."
    )


# ───────────────────────────── /fullverify ─────────────────────────────────

@router.message(Command("fullverify"))
async def cmd_fullverify(message: Message, bot: Bot) -> None:
    """Немедленный запуск полной проверки всех pending пользователей."""
    pending = await db.list_pending()
    total = len(pending)

    if total == 0:
        await message.answer("📭 Нет пользователей в статусе <b>pending</b>.")
        return

    progress = await message.answer(
        f"🔄 Запускаю полную проверку <b>{total}</b> pending-пользователей…"
    )

    verified = 0
    failed = 0
    crashed = 0

    for u in pending:
        try:
            result = await run_full_verification(bot, u.user_id)
        except Exception as e:
            log.exception("verification crashed for %s: %s", u.user_id, e)
            crashed += 1
            continue

        if result.ok:
            verified += 1
            method_text = (
                "TON-кошелёк" if result.method == "wallet"
                else "подарок Telegram"
            )
            try:
                await bot.send_message(
                    chat_id=u.user_id,
                    text=(
                        f"🎉 Админ запустил проверку — ты подтверждён "
                        f"через {method_text}.\n"
                        f"Права в группе восстановлены."
                    ),
                )
            except Exception as e:
                log.debug("DM after verify failed for %s: %s", u.user_id, e)
        else:
            failed += 1

    await progress.edit_text(
        f"✅ <b>Полная проверка завершена</b>\n\n"
        f"Всего проверено: <b>{total}</b>\n"
        f"  • верифицировано: <b>{verified}</b>\n"
        f"  • не подтверждены: <b>{failed}</b>\n"
        f"  • с ошибками: <b>{crashed}</b>"
    )


# ───────────────────────── /verify @username ───────────────────────────────

@router.message(Command("verify"))
async def cmd_admin_verify(
    message: Message, command: CommandObject, bot: Bot
) -> None:
    """Точечная проверка одного пользователя по @username."""
    arg = (command.args or "").strip()

    if not arg:
        await message.answer(
            "Использование:\n<code>/verify @username</code>\n\n"
            "Бот найдёт пользователя в БД по username и запустит "
            "полную проверку (TON + подарки)."
        )
        return

    user_row = await db.get_user_by_username(arg)
    if not user_row:
        await message.answer(
            f"❌ Пользователь <code>{arg}</code> не найден в БД.\n\n"
            f"Возможные причины:\n"
            f"• username указан с опечаткой\n"
            f"• пользователь ни разу не нажимал кнопку верификации\n"
            f"• пользователь сменил username (бот хранит старый)"
        )
        return

    progress = await message.answer(
        f"🔄 Проверяю <b>@{user_row.username or '—'}</b> "
        f"(ID: <code>{user_row.user_id}</code>)…"
    )

    try:
        result = await run_full_verification(bot, user_row.user_id)
    except Exception as e:
        log.exception("admin /verify crashed for %s: %s", user_row.user_id, e)
        await progress.edit_text(
            f"💥 Проверка упала с ошибкой:\n<code>{e}</code>"
        )
        return

    fresh = await db.get_user(user_row.user_id)

    if result.ok:
        method_text = (
            "TON-кошелёк" if result.method == "wallet"
            else "подарок Telegram"
        )
        wallet_line = (
            f"\nКошелёк: <code>{fresh.wallet_address}</code>"
            if fresh and fresh.wallet_address else ""
        )
        await progress.edit_text(
            f"✅ <b>Верификация пройдена</b>\n\n"
            f"@{user_row.username or '—'} (ID: <code>{user_row.user_id}</code>)\n"
            f"Способ: {method_text}\n"
            f"Права в группе восстановлены.{wallet_line}"
        )
        try:
            await bot.send_message(
                chat_id=user_row.user_id,
                text=(
                    f"🎉 Админ подтвердил твою верификацию через {method_text}.\n"
                    f"Права в группе восстановлены."
                ),
            )
        except Exception as e:
            log.debug("DM after admin verify failed for %s: %s", user_row.user_id, e)
        return

    error_map = {
        "wallet_not_connected": "кошелёк не подключён, подарок не найден",
        "no_nft": "на подключённом кошельке нет NFT из коллекции",
        "no_gift": "подарок Scared Cat в профиле не найден",
    }
    error_text = error_map.get(result.error or "", result.error or "неизвестная ошибка")

    await progress.edit_text(
        f"❌ <b>Верификация НЕ пройдена</b>\n\n"
        f"@{user_row.username or '—'} (ID: <code>{user_row.user_id}</code>)\n"
        f"Причина: {error_text}\n"
        f"Статус в БД: <b>{fresh.status if fresh else 'unknown'}</b>"
    )


# ──────────────────────────── /admin_help ──────────────────────────────────

@router.message(Command("debug_gifts"))
async def cmd_debug_gifts(message: Message, command: CommandObject, bot: Bot) -> None:
    """Диагностика: показывает все подарки пользователя из Bot API."""
    arg = (command.args or "").strip()
    if not arg:
        await message.answer(
            "Использование:\n"
            "<code>/debug_gifts @username</code> или <code>/debug_gifts 123456789</code>"
        )
        return

    # Определяем user_id
    if arg.lstrip("@").isdigit():
        user_id = int(arg.lstrip("@"))
        user_row = await db.get_user(user_id)
    else:
        user_row = await db.get_user_by_username(arg)
        user_id = user_row.user_id if user_row else None

    if not user_id:
        await message.answer(f"❌ Пользователь <code>{arg}</code> не найден в БД.")
        return

    await message.answer(f"🔍 Запрашиваю подарки для user_id=<code>{user_id}</code>…")

    try:
        result = await get_user_gifts_debug(bot, user_id)
    except Exception as e:
        result = f"💥 Ошибка: <code>{e}</code>"

    db_info = ""
    if user_row:
        db_info = (
            f"\n\n<b>БД:</b> status={user_row.status} "
            f"wallet=<code>{user_row.wallet_address or '—'}</code>"
        )

    await message.answer(f"{result}{db_info}")


@router.message(Command("debug_wallet"))
async def cmd_debug_wallet(message: Message, command: CommandObject, bot: Bot) -> None:
    """Диагностика: проверяет NFT на кошельке пользователя."""
    from services.ton_api import user_owns_collection_nft, TonApiError

    arg = (command.args or "").strip()
    if not arg:
        await message.answer(
            "Использование:\n"
            "<code>/debug_wallet @username</code> или <code>/debug_wallet EQ...</code>"
        )
        return

    # Если передан адрес кошелька напрямую
    if arg.startswith("EQ") or arg.startswith("UQ") or arg.startswith("0:"):
        wallet = arg
    else:
        user_row = await db.get_user_by_username(arg)
        if not user_row or not user_row.wallet_address:
            await message.answer(
                f"❌ Кошелёк не найден для <code>{arg}</code>.\n"
                f"Передай адрес кошелька напрямую: <code>/debug_wallet EQ...</code>"
            )
            return
        wallet = user_row.wallet_address

    await message.answer(f"🔍 Проверяю NFT для кошелька:\n<code>{wallet}</code>")

    try:
        owns = await user_owns_collection_nft(wallet)
        if owns:
            await message.answer("✅ NFT из коллекции Scared Cats <b>НАЙДЕНЫ</b> на кошельке.")
        else:
            await message.answer("❌ NFT из коллекции Scared Cats <b>НЕ найдены</b> на кошельке.")
    except TonApiError as e:
        await message.answer(f"💥 Ошибка tonapi: <code>{e}</code>")


@router.message(Command("admin_help"))
async def cmd_admin_help(message: Message) -> None:
    await message.answer(
        "<b>👑 Админ-команды:</b>\n\n"
        "/start_verification_existing — опубликовать и закрепить "
        "видео-объявление для существующих участников\n\n"
        "/fullverify — немедленно запустить полную проверку "
        "всех pending пользователей\n\n"
        "/verify @username — точечная проверка одного пользователя\n\n"
        "/admin_stats — статистика по БД\n\n"
        "<b>🔧 Диагностика:</b>\n\n"
        "/debug_gifts @username — показывает все подарки пользователя из Bot API\n\n"
        "/debug_wallet @username — проверяет NFT на кошельке пользователя\n\n"
        "/admin_help — эта справка"
    )


# ──────────────────────────── /admin_stats ─────────────────────────────────

@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    pending = await db.list_pending()
    total_pending = len(pending)
    existing = sum(1 for u in pending if u.is_existing)
    new_users = total_pending - existing

    await message.answer(
        "<b>📊 Статистика</b>\n"
        f"⏳ Pending всего: <b>{total_pending}</b>\n"
        f"  • из них existing: {existing}\n"
        f"  • из них новых: {new_users}"
    )
