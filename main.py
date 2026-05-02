"""
Точка входа — Scared Cats verifier bot.
"""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from aiogram_tonconnect.middleware import AiogramTonConnectMiddleware
from aiogram_tonconnect.handlers import AiogramTonConnectHandlers
from aiogram_tonconnect.tonconnect.storage import ATCMemoryStorage
from aiogram_tonconnect.utils.qrcode import QRImageProvider
from tonutils.tonconnect import TonConnect

from config import BASE_DIR, settings
from database import db
from handlers import admin, chat_member, private, tonconnect as tc_handlers
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


async def setup_bot_commands(bot: Bot) -> None:
    """Регистрирует команды для меню в ЛС."""
    user_commands = [
        BotCommand(command="start", description="🚀 Начать"),
        BotCommand(command="status", description="📊 Мой статус"),
        BotCommand(command="mywallet", description="👛 Мой кошелёк"),
        BotCommand(command="verify", description="🔄 Перепроверить"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    admin_commands = user_commands + [
        BotCommand(command="start_verification_existing",
                   description="🔔 Запустить верификацию существующих"),
        BotCommand(command="admin_stats", description="📈 Статистика"),
        BotCommand(command="admin_help", description="❓ Помощь админа"),
    ]
    try:
        await bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=settings.ADMIN_ID),
        )
    except Exception as e:
        logging.getLogger("main").warning("Cannot set admin commands: %s", e)


async def main() -> None:
    configure_logging()
    log = logging.getLogger("main")

    await db.init()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # TON Connect
    storage = ATCMemoryStorage()
    tonconnect = TonConnect(manifest_url=settings.MANIFEST_URL, storage=storage)

    atc_middleware = AiogramTonConnectMiddleware(
        tonconnect=tonconnect,
        qrcode_provider=QRImageProvider(),
    )
    dp.update.middleware(atc_middleware)
    AiogramTonConnectHandlers().register(dp)

    # Наши роутеры. admin ДО private, иначе /start_verification_existing
    # перехватится фильтром private-роутера.
    dp.include_router(tc_handlers.router)
    dp.include_router(admin.router)
    dp.include_router(chat_member.router)
    dp.include_router(private.router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    await setup_bot_commands(bot)

    me = await bot.get_me()
    log.info("Bot @%s (id=%s) is up", me.username, me.id)
    log.info(
        "Group: %s | Admin: %s | Collection: %s | Existing deadline: %s",
        settings.GROUP_ID, settings.ADMIN_ID,
        settings.NFT_COLLECTION_ADDRESS,
        settings.existing_deadline.isoformat(),
    )

    allowed = list(set(
        dp.resolve_used_update_types() + ["chat_member", "my_chat_member"]
    ))
    try:
        await dp.start_polling(bot, allowed_updates=allowed)
    finally:
        scheduler.shutdown(wait=False)
        try:
            await tonconnect.close_all_connections()
        except Exception:
            pass
        await bot.session.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
