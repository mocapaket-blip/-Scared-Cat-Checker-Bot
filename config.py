from datetime import datetime
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    BOT_TOKEN: str
    ADMIN_ID: int
    GROUP_ID: int

    # TON
    NFT_COLLECTION_ADDRESS: str = "EQATuUGdvrjLvTWE5ppVFOVCqU2dlCLUnKTsu0n1JYm9la10"
    TONAPI_KEY: str = ""
    TONAPI_BASE_URL: str = "https://tonapi.io"

    # TON Connect
    MANIFEST_URL: str

    # Verification
    VERIFICATION_DEADLINE_DAYS: int = 7
    # Дедлайн для уже существующих участников: 09.05.2026 00:00 UTC+3
    EXISTING_DEADLINE_ISO: str = "2026-05-09T00:00:00+03:00"

    # Gifts
    GIFT_KEYWORDS: str = "scared cat,scaredcat"

    # DB
    DB_PATH: str = "data/bot.db"

    # Scheduler — каждый день в 00:00 по Москве (UTC+3)
    DAILY_CHECK_HOUR: int = 0
    DAILY_CHECK_MINUTE: int = 0

    @field_validator("EXISTING_DEADLINE_ISO")
    @classmethod
    def _validate_deadline(cls, v: str) -> str:
        # проверяем парсится
        datetime.fromisoformat(v)
        return v

    @property
    def existing_deadline(self) -> datetime:
        return datetime.fromisoformat(self.EXISTING_DEADLINE_ISO)

    @property
    def gift_keywords_list(self) -> List[str]:
        return [s.strip().lower() for s in self.GIFT_KEYWORDS.split(",") if s.strip()]

    @property
    def db_full_path(self) -> Path:
        p = Path(self.DB_PATH)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
