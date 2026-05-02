"""
Точка входа для Scared Cats verifier bot.
"""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram_tonconnect import (
    AiogramTonConnectHandlers,
    AiogramTonConnectMiddleware,
)
from aiogram_tonconnect.tonconnect.storage import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRUrlProvider

from config import BASE_DIR, settings
from database import db
from handlers import chat_member, private, tonconnect as tc_handlers
from scheduler import setup_scheduler


def configure_logging() -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

    handlers = [
        logging.StreamHandler(stream=sys.stdout),
        RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def main() -> None:
    configure_logging()
    log = logging.getLogger("main")

    await db.init()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    atc_middleware = AiogramTonConnectMiddleware(
        manifest_url=settings.MANIFEST_URL,
        qrcode_provider=QRUrlProvider(),
        storage=ATCMemoryStorage(),
    )
    dp.update.middleware(atc_middleware)
    AiogramTonConnectHandlers().register(dp)

    dp.include_router(tc_handlers.router)
    dp.include_router(chat_member.router)
    dp.include_router(private.router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    me = await bot.get_me()
    log.info("Bot @%s (id=%s) is up", me.username, me.id)
    log.info("Group: %s | Admin: %s | Collection: %s",
             settings.GROUP_ID, settings.ADMIN_ID, settings.NFT_COLLECTION_ADDRESS)

    allowed = list(set(dp.resolve_used_update_types() + ["chat_member", "my_chat_member"]))
    try:
        await dp.start_polling(bot, allowed_updates=allowed)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
