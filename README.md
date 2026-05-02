# Scared Cats — Telegram Verifier Bot

Production-ready Telegram-бот для закрытой группы коллекции **Scared Cats** (TON).
Верифицирует участников ДВУМЯ способами:

1. **TON Connect 2.0** — пользователь подключает кошелёк, бот проверяет наличие
   NFT из коллекции через [tonapi.io](https://tonapi.io).
2. **Подарки Telegram** — бот вызывает `getUserGifts` (Bot API ≥ 9.3) и ищет
   уникальный подарок с именем модели/коллекции, содержащей `Scared Cat`.

Контракт коллекции по умолчанию:
`EQATuUGdvrjLvTWE5ppVFOVCqU2dlCLUnKTsu0n1JYm9la10`

---

## Возможности

- При входе нового участника — статус `pending`, дедлайн **7 дней**, DM с двумя
  кнопками верификации.
- Команды в ЛС:
  - `/status` — текущий статус
  - `/mywallet` — подключённый кошелёк
  - `/verify` — запустить проверку обоими способами
- Ежедневная задача (00:00 UTC) — APScheduler:
  - проверяет всех `pending` через подключённый кошелёк или подарки;
  - если дедлайн истёк — уведомляет админа в ЛС: «⚠️ Верификация истекла…».
- Постоянное хранилище: SQLite (`aiosqlite`), миграция схемы при старте.
- Логи — stdout + `logs/bot.log` (ротация 5×5 МБ).

---

## Структура проекта

```
.
├── main.py                    # точка входа
├── config.py                  # настройки через .env (pydantic-settings)
├── database.py                # схема + DAO (aiosqlite)
├── scheduler.py               # APScheduler — ежедневная проверка
├── handlers/
│   ├── chat_member.py         # вход в группу
│   ├── private.py             # /start, /status, /mywallet, /verify
│   └── tonconnect.py          # TON Connect callback'и
├── services/
│   ├── ton_api.py             # tonapi.io GET /v2/accounts/{addr}/nfts
│   ├── gifts.py               # bot.get_user_gifts(user_id)
│   └── verification.py        # объединение обоих методов
├── keyboards/inline.py
├── tonconnect-manifest.json   # выложить на публичный HTTPS
├── requirements.txt
└── .env.example
```

---

## Запуск

### 1. Подготовка

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Манифест TON Connect

Файл `tonconnect-manifest.json` **обязательно** должен быть доступен по
публичному HTTPS-URL (по нему кошельки будут показывать иконку и название
твоего бота).

Самый быстрый способ:

1. Создай публичный репозиторий на GitHub.
2. Положи туда `tonconnect-manifest.json` (отредактируй URL/иконку).
3. Включи GitHub Pages (Settings → Pages → Branch: main).
4. Скопируй URL вида
   `https://<username>.github.io/<repo>/tonconnect-manifest.json`
5. Подставь его в `.env` как `MANIFEST_URL`.

### 3. Настройка `.env`

```bash
cp .env.example .env
```

Заполни:
- `BOT_TOKEN` — от @BotFather.
- `ADMIN_ID` — твой Telegram user_id (узнать у @userinfobot).
- `GROUP_ID` — id закрытой группы (отрицательное число `-100…`).
- `MANIFEST_URL` — публичный URL манифеста (см. шаг 2).
- `TONAPI_KEY` — *необязательно*, но при больших нагрузках возьми ключ на
  https://tonconsole.com (API → tonapi).

### 4. Настройка бота в Telegram

В @BotFather:

- `/setprivacy` → **Disable** (иначе бот не видит входы в группу).
- `/setjoingroups` → **Enable**.
- Добавь бота в закрытую группу как **администратор** с правами:
  - читать сообщения, видеть участников, удалять (для будущих версий).

### 5. Запуск

```bash
python main.py
```

Бот начнёт принимать апдейты `chat_member` и DM-команды.

---

## Логика верификации

```
вход в группу
   └─→ DB: status=pending, deadline = now + 7d
   └─→ DM: меню «Подключить TON-кошелёк» / «Проверить подарки»

TON Connect:
   └─→ atc_manager.connect_wallet → callback after_wallet_connect
   └─→ DB.set_wallet, проверка NFT через tonapi.io
       └─→ если есть NFT  → DB.mark_verified(method=wallet)
       └─→ если нет       → пользователю предложить gifts/другой кошелёк

Подарки:
   └─→ bot.get_user_gifts(user_id) → перебираем OwnedGiftUnique
       └─→ матчим по model.name / name / base_name (lowercase, подстроки
           из GIFT_KEYWORDS = "scared cat", "scaredcat")
       └─→ если найдено   → DB.mark_verified(method=gift)

Daily check 00:00 UTC:
   └─→ для всех pending повторяем оба метода
   └─→ если дедлайн истёк и не верифицирован
       └─→ DB.mark_expired + DM админу
```

---

## Замечания

- **getUserGifts** требует, чтобы пользователь хотя бы раз нажал «Start» в ЛС
  с ботом. Иначе придёт ошибка `Forbidden` и проверка через подарки невозможна
  до первого взаимодействия. В коде это отлавливается, и пользователь увидит
  предложение использовать TON Connect.
- **Бот не кикает автоматически.** Запрос на исключение приходит админу в ЛС —
  это безопаснее (исключаешь руками, оценивая ситуацию). Если нужен авто-kick,
  раскомментируй `bot.ban_chat_member` в `scheduler._notify_admin_expired`.
- **Хранилище TON Connect.** В коде используется `ATCMemoryStorage` — для
  одного инстанса этого достаточно. Для нескольких процессов/перезапусков
  замени на `ATCRedisStorage` (требуется `redis`).
- **tonapi rate limits.** Без ключа лимит ~1 RPS. Под нагрузкой используй
  `TONAPI_KEY`.

---

## Полезные ссылки

- TON Connect docs — https://docs.ton.org/develop/dapps/ton-connect/overview
- aiogram-tonconnect — https://github.com/nessshon/aiogram-tonconnect
- tonapi v2 — https://tonapi.io/api-v2
- Bot API Gifts — https://core.telegram.org/bots/api#getusergifts
