"""
Реакция на вход нового участника в закрытую группу.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import ChatMemberUpdated

from config import settings
from database import db
from keyboards.inline import verification_menu

router = Router(name="chat_member")
log = logging.getLogger(__name__)


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

    user_row = await db.upsert_pending_user(
        user_id=user.id,
        username=user.username,
        full_name=_full_name(user),
    )

    if user_row.status == "verified":
        log.info("User %s is already verified, skipping DM.", user.id)
        return

    text = (
        f"Привет, <b>{_full_name(user)}</b>!\n\n"
        f"Чтобы остаться в группе <b>Scared Cats</b>, нужно подтвердить, "
        f"что ты владеешь NFT из коллекции, либо имеешь подарок Scared Cat в профиле.\n\n"
        f"Доступно <b>два способа</b> верификации:\n"
        f"1) <b>TON Connect</b> — подключи кошелёк, бот проверит NFT.\n"
        f"2) <b>Подарки Telegram</b> — бот сам найдёт Scared Cat в твоём профиле.\n\n"
        f"⏳ На верификацию даётся <b>{settings.VERIFICATION_DEADLINE_DAYS} дней</b>. "
        f"Дедлайн: <code>{user_row.deadline_at:%Y-%m-%d %H:%M UTC}</code>"
    )

    try:
        await bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=verification_menu(),
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.warning("Cannot DM user %s: %s", user.id, e)
        try:
            me = await bot.get_me()
            link = f"https://t.me/{me.username}?start=verify"
            await bot.send_message(
                chat_id=settings.GROUP_ID,
                text=(
                    f'<a href="tg://user?id={user.id}">{_full_name(user)}</a>, '
                    f"открой ЛС с ботом и нажми Start, чтобы пройти верификацию: "
                    f"{link}"
                ),
            )
        except Exception as e2:
            log.error("Also failed to notify in group: %s", e2)
