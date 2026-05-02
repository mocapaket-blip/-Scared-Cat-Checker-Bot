"""
Ежедневная задача проверки всех pending-пользователей.
"""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from database import db, now_utc
from services.verification import run_full_verification

log = logging.getLogger(__name__)


async def daily_check(bot: Bot) -> None:
    log.info("Daily check started")
    pending = await db.list_pending()
    log.info("Pending users: %d", len(pending))

    for user in pending:
        try:
            result = await run_full_verification(bot, user.user_id)
        except Exception as e:
            log.exception("verification crashed for %s: %s", user.user_id, e)
            continue

        if result.ok:
            log.info("User %s verified via %s", user.user_id, result.method)
            try:
                await bot.send_message(
                    chat_id=user.user_id,
                    text=(
                        "🎉 Ежедневная проверка прошла успешно — ты подтверждён "
                        f"через {('TON-кошелёк' if result.method == 'wallet' else 'подарок Telegram')}."
                    ),
                )
            except Exception as e:
                log.debug("DM after verify failed for %s: %s", user.user_id, e)
            continue

        if user.deadline_at and now_utc() >= user.deadline_at:
            await db.mark_expired(user.user_id)
            await _notify_admin_expired(bot, user)
            log.info("User %s marked expired and admin notified", user.user_id)

    log.info("Daily check finished")


async def _notify_admin_expired(bot: Bot, user) -> None:
    username = f"@{user.username}" if user.username else (user.full_name or "(без имени)")
    wallet_line = f"\nКошелёк: <code>{user.wallet_address}</code>" if user.wallet_address else ""
    text = (
        "⚠️ <b>Верификация истекла</b>\n"
        f"{username} (ID: <code>{user.user_id}</code>){wallet_line}\n"
        "Пожалуйста, исключите из чата."
    )
    try:
        await bot.send_message(chat_id=settings.ADMIN_ID, text=text)
    except Exception as e:
        log.error("Cannot notify admin about %s: %s", user.user_id, e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        daily_check,
        CronTrigger(
            hour=settings.DAILY_CHECK_HOUR_UTC,
            minute=settings.DAILY_CHECK_MINUTE_UTC,
            timezone="UTC",
        ),
        kwargs={"bot": bot},
        id="daily_check",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info(
        "Scheduler configured: daily check at %02d:%02d UTC",
        settings.DAILY_CHECK_HOUR_UTC,
        settings.DAILY_CHECK_MINUTE_UTC,
    )
    return scheduler
