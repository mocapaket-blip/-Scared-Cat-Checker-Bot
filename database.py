import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import aiosqlite

from config import settings

log = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT,
    full_name      TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | verified | expired | kicked
    method         TEXT,                              -- wallet | gift
    wallet_address TEXT,
    is_existing    INTEGER NOT NULL DEFAULT 0,       -- 1 = был участником на момент включения проверки
    is_restricted  INTEGER NOT NULL DEFAULT 0,       -- 1 = бот ограничил права в чате
    joined_at      TEXT NOT NULL,
    deadline_at    TEXT NOT NULL,
    verified_at    TEXT,
    last_checked   TEXT,
    notified_admin INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_users_status   ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_deadline ON users(deadline_at);
"""


# Миграции: добавляем колонки, если их нет (для обновления старой БД).
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN is_existing INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN is_restricted INTEGER NOT NULL DEFAULT 0",
]


@dataclass
class UserRow:
    user_id: int
    username: Optional[str]
    full_name: Optional[str]
    status: str
    method: Optional[str]
    wallet_address: Optional[str]
    is_existing: bool
    is_restricted: bool
    joined_at: datetime
    deadline_at: datetime
    verified_at: Optional[datetime]
    last_checked: Optional[datetime]
    notified_admin: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "UserRow":
        def _dt(s): return datetime.fromisoformat(s) if s else None
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            full_name=row["full_name"],
            status=row["status"],
            method=row["method"],
            wallet_address=row["wallet_address"],
            is_existing=bool(row["is_existing"]) if "is_existing" in row.keys() else False,
            is_restricted=bool(row["is_restricted"]) if "is_restricted" in row.keys() else False,
            joined_at=_dt(row["joined_at"]),
            deadline_at=_dt(row["deadline_at"]),
            verified_at=_dt(row["verified_at"]),
            last_checked=_dt(row["last_checked"]),
            notified_admin=bool(row["notified_admin"]),
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(SCHEMA)
            for m in MIGRATIONS:
                try:
                    await conn.execute(m)
                except Exception:
                    pass  # колонка уже есть
            await conn.commit()
        log.info("Database initialised at %s", self.path)

    async def _conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def upsert_pending_user(
        self,
        user_id: int,
        username: Optional[str],
        full_name: Optional[str],
        is_existing: bool = False,
        deadline: Optional[datetime] = None,
        is_restricted: bool = False,
    ) -> UserRow:
        joined = now_utc()
        if deadline is None:
            deadline = joined + timedelta(days=settings.VERIFICATION_DEADLINE_DAYS)
        async with await self._conn() as conn:
            cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            existing = await cur.fetchone()
            if existing is None:
                await conn.execute(
                    """
                    INSERT INTO users
                        (user_id, username, full_name, status,
                         is_existing, is_restricted, joined_at, deadline_at)
                    VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        user_id, username, full_name,
                        int(is_existing), int(is_restricted),
                        joined.isoformat(), deadline.isoformat(),
                    ),
                )
            else:
                # сохраняем verified, иначе — обновляем
                await conn.execute(
                    """
                    UPDATE users
                       SET username = ?,
                           full_name = ?,
                           status = CASE WHEN status = 'verified' THEN 'verified' ELSE 'pending' END,
                           is_existing = CASE WHEN ?=1 THEN 1 ELSE is_existing END,
                           is_restricted = CASE WHEN status = 'verified' THEN is_restricted ELSE ? END,
                           deadline_at = CASE WHEN status = 'verified' THEN deadline_at ELSE ? END,
                           notified_admin = CASE WHEN status = 'verified' THEN notified_admin ELSE 0 END
                     WHERE user_id = ?
                    """,
                    (
                        username, full_name,
                        int(is_existing),
                        int(is_restricted),
                        deadline.isoformat(),
                        user_id,
                    ),
                )
            await conn.commit()
            cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return UserRow.from_row(row)

    async def get_user(self, user_id: int) -> Optional[UserRow]:
        async with await self._conn() as conn:
            cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return UserRow.from_row(row) if row else None

    async def set_wallet(self, user_id: int, wallet: str) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "UPDATE users SET wallet_address = ? WHERE user_id = ?",
                (wallet, user_id),
            )
            await conn.commit()

    async def set_restricted(self, user_id: int, value: bool) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "UPDATE users SET is_restricted = ? WHERE user_id = ?",
                (int(value), user_id),
            )
            await conn.commit()

    async def mark_verified(self, user_id: int, method: str, wallet: Optional[str] = None) -> None:
        async with await self._conn() as conn:
            if wallet:
                await conn.execute(
                    """
                    UPDATE users
                       SET status='verified', method=?, wallet_address=?,
                           verified_at=?, last_checked=?, is_restricted=0
                     WHERE user_id=?
                    """,
                    (method, wallet, now_utc().isoformat(), now_utc().isoformat(), user_id),
                )
            else:
                await conn.execute(
                    """
                    UPDATE users
                       SET status='verified', method=?,
                           verified_at=?, last_checked=?, is_restricted=0
                     WHERE user_id=?
                    """,
                    (method, now_utc().isoformat(), now_utc().isoformat(), user_id),
                )
            await conn.commit()

    async def touch_checked(self, user_id: int) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "UPDATE users SET last_checked=? WHERE user_id=?",
                (now_utc().isoformat(), user_id),
            )
            await conn.commit()

    async def mark_expired(self, user_id: int) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "UPDATE users SET status='expired', notified_admin=1 WHERE user_id=?",
                (user_id,),
            )
            await conn.commit()

    async def mark_kicked(self, user_id: int) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "UPDATE users SET status='kicked' WHERE user_id=?",
                (user_id,),
            )
            await conn.commit()

    async def list_pending(self) -> List[UserRow]:
        async with await self._conn() as conn:
            cur = await conn.execute(
                "SELECT * FROM users WHERE status='pending' ORDER BY deadline_at ASC"
            )
            rows = await cur.fetchall()
            return [UserRow.from_row(r) for r in rows]


db = Database(str(settings.db_full_path))
