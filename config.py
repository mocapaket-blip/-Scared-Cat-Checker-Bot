from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str
    ADMIN_ID: int
    GROUP_ID: int

    NFT_COLLECTION_ADDRESS: str = "EQATuUGdvrjLvTWE5ppVFOVCqU2dlCLUnKTsu0n1JYm9la10"
    TONAPI_KEY: str = ""
    TONAPI_BASE_URL: str = "https://tonapi.io"

    MANIFEST_URL: str

    VERIFICATION_DEADLINE_DAYS: int = 7

    GIFT_KEYWORDS: str = "scared cat,scaredcat"

    DB_PATH: str = "data/bot.db"

    DAILY_CHECK_HOUR_UTC: int = 0
    DAILY_CHECK_MINUTE_UTC: int = 0

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
