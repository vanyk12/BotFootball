
# ⚽ Football Match Organizer — Telegram Bot + Mini App

Готовый к деплою проект для организации футбольных матчей, регистрации игроков и автоматической балансировки команд.

## 🏗️ Архитектура

- **Бэкенд:** Python — FastAPI (Mini App API + static) + aiogram 3.x (бот, webhook)
- **БД:** Supabase (PostgreSQL) через asyncpg
- **Фронтенд:** Чистый HTML5 + Tailwind CSS (CDN) + Vanilla JS
- **Деплой:** Docker, Railway

Всё запускается в **одном** процессе / контейнере: FastAPI обслуживает и webhook бота, и API Mini App, и статические файлы.

## 📁 Структура

```
.
├── main.py              # FastAPI + aiogram (webhook), API, балансировка, initData валидация
├── static/
│   └── index.html       # Telegram Mini App (3 экрана)
├── schema.sql           # SQL-скрипт для Supabase
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## 🚀 Быстрый старт (Railway)

### 1. Подготовка

1. Создайте бота через [@BotFather](https://t.me/BotFather) — получите `BOT_TOKEN`
2. Создайте проект на [Supabase](https://supabase.com), скопируйте connection string (Settings → Database → Connection string)
3. Выполните `schema.sql` в SQL Editor Supabase

### 2. Локальный запуск

```bash
cp .env.example .env
# Заполните BOT_TOKEN, DATABASE_URL, WEBAPP_BASE_URL

pip install -r requirements.txt
python main.py
```

### 3. Деплой на Railway

1. Создайте GitHub репозиторий и запушьте код
2. На Railway → New Project → Deploy from GitHub repo
3. В Variables добавьте:
   - `BOT_TOKEN` — токен бота
   - `DATABASE_URL` — connection string Supabase
   - `WEBAPP_BASE_URL` — `https://<your-app>.up.railway.app`
   - `MINIAPP_URL` — `https://<your-app>.up.railway.app/miniapp`
   - `ADMIN_IDS` — (опционально) список ID через запятую, например `123456,789012`
4. Railway автоматически соберёт Docker-образ и запустит его
5. Бот автоматически установит webhook при старте

### 4. Настройка Mini App в BotFather

```
/mybots → выбрать бота → Mini App → Configure Mini App
```

Укажите URL: `https://<your-app>.up.railway.app/miniapp`

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + кнопка запуска Mini App |
| `/top` | ТОП-10 игроков по скиллу |
| `/match` | Текущий счёт и составы активного матча |

## 🎮 Mini App — 3 экрана

1. **Профиль** — регистрация (ползунок скилла) или статистика игрока
2. **Матч** — выбор игроков из списка + формирование сбалансированных команд
3. **Игра** — две команды, ввод голов (+/−), завершение матча

## 🧮 Алгоритм балансировки

Жадный алгоритм: игроки сортируются по `skill_level` по убыванию, затем каждый отправляется в команду с меньшей суммой скилла (при равенстве — в команду с меньшим числом игроков).

## 📊 Пересчёт скилла после матча

- Победа: `+2.0%` + `+1.0%` за каждый гол
- Ничья: `+1.0%` за каждый гол
- Поражение: `-1.0%` + `+1.0%` за каждый гол
- Жёсткое ограничение: `0.0 … 100.0`

## 🔐 Безопасность

- Каждый запрос к API валидирует `initData` по официальному алгоритму Telegram (HMAC-SHA256)
- Невозможно подменить ID пользователя или накрутить статистику
- Поле username заблокировано для ручного ввода
