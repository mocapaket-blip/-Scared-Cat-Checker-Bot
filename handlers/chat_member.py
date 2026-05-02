"""
Реакция на вход нового участника в закрытую группу.
1) Сразу restrict_chat_member (can_send_messages=False).
2) Публикует сообщение в группе с кнопкой "Верифицироваться сейчас".
3) Создаёт запись pending в БД с дедлайном +7 дней.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import (
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from config import settings
from database import db

router = Router(name="chat_member")
log = logging.getLogger(__name__)


# Полностью лишаем права писать
RESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_topics=False,
)


def _full_name(u) -> str:
    parts = [u.first_name or "", u.last_name or ""]
    return " ".join(p for p in parts if p).strip() or (u.username or str(u.id))


@router.chat_member(
    F.chat.id == settings.GROUP_ID,
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION),
)
async def on_user_joined(event: ChatMemberUpdated, bot: Bot) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return

    # 1) Записать в БД
    user_row = await db.upsert_pending_user(
        user_id=user.id,
        username=user.username,
        full_name=_full_name(user),
        is_existing=False,
    )

    if user_row.status == "verified":
        log.info("User %s is already verified, skipping restrict.", user.id)
        return

    # 2) Restrict в группе
    restricted_ok = False
    try:
        await bot.restrict_chat_member(
            chat_id=settings.GROUP_ID,
            user_id=user.id,
            permissions=RESTRICTED_PERMISSIONS,
        )
        await db.set_restricted(user.id, True)
        restricted_ok = True
        log.info("Restricted new user %s", user.id)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.error("Cannot restrict user %s: %s", user.id, e)

    # 3) Сообщение в группу с кнопкой
    me = await bot.get_me()
    deep_link = f"https://t.me/{me.username}?start=verify"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔑 Верифицироваться сейчас", url=deep_link)
    ]])

    mention = f'<a href="tg://user?id={user.id}">{_full_name(user)}</a>'
    note = "" if restricted_ok else (
        "\n\n<i>(У бота недостаточно прав для ограничения. "
        "Назначьте его админом с правом can_restrict_members.)</i>"
    )
    text = (
        f"👋 {mention}, добро пожаловать в <b>Scared Cats</b>!\n\n"
        f"Чат — только для владельцев NFT/подарков Scared Cat.\n"
        f"У тебя есть <b>{settings.VERIFICATION_DEADLINE_DAYS} дней</b> на верификацию.\n"
        f"До неё ты не можешь писать сообщения.{note}"
    )

    try:
        await bot.send_message(
            chat_id=settings.GROUP_ID,
            text=text,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error("Cannot send welcome message: %s", e)
