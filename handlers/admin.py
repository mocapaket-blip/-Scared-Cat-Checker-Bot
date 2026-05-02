"""
Админ-команды (доступ только ADMIN_ID).
Главная: /start_verification_existing — закрепить сообщение в группе для уже
существующих участников. Кто нажмёт кнопку — попадает в БД с дедлайном
из EXISTING_DEADLINE_ISO.
"""
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import BASE_DIR, settings

router = Router(name="admin")
router.message.filter(F.from_user.id == settings.ADMIN_ID)

log = logging.getLogger(__name__)


EXISTING_TEXT = (
    "⚠️ <b>ВНИМАНИЕ, СУЩЕСТВУЮЩИМ УЧАСТНИКАМ!</b>\n\n"
    "С сегодняшнего дня чат — только для владельцев Scared Cat.\n"
    "У вас есть время на верификацию до <b>09.05.2026</b>.\n"
    "Кто не пройдёт — потеряет своё место в чате.\n\n"
    "Нажмите кнопку ниже и подтвердите владение NFT."
)

VIDEO_FILENAME = "scared_cat_checker_video.mp4"


@router.message(Command("start_verification_existing"))
async def cmd_start_verification_existing(message: Message, bot: Bot) -> None:
    """
    Публикует и закрепляет сообщение (с видео) в группе для уже состоящих участников.
    """
    me = await bot.get_me()
    deep_link = f"https://t.me/{me.username}?start=verify_existing"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🔑 ВЕРИФИЦИРОВАТЬСЯ СЕЙЧАС",
            url=deep_link,
        )
    ]])

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
        # Видео не найдено — отправляем текстом и предупреждаем
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
                f"❌ Не удалось отправить сообщение в группу:\n<code>{e}</code>\n\n"
                f"Проверь, что бот добавлен в группу <code>{settings.GROUP_ID}</code> "
                f"как админ."
            )
            return

    # Закрепить сообщение
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
    pinned_status = "📌 закреплено" if pinned_ok else "⚠️ <b>НЕ закреплено</b> (нет прав can_pin_messages)"

    await message.answer(
        f"✅ Сообщение для существующих участников опубликовано.\n"
        f"{pinned_status}\n\n"
        f"<b>Дедлайн:</b> <code>{deadline_str}</code>\n\n"
        f"Все, кто нажмёт кнопку, появятся в БД со статусом pending."
    )


@router.message(Command("admin_help"))
async def cmd_admin_help(message: Message) -> None:
    await message.answer(
        "<b>Админ-команды:</b>\n"
        "/start_verification_existing — опубликовать и закрепить сообщение для "
        "уже состоящих участников\n"
        "/admin_stats — статистика по БД\n"
        "/admin_help — эта справка"
    )


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    from database import db
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
