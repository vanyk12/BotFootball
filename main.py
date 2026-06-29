
"""
Football Match Organizer — Telegram Bot + Mini App (FastAPI + aiogram 3.x)
Single asyncio loop, webhook mode. Ready for Railway.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram import types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))
MINIAPP_URL = os.getenv("MINIAPP_URL", f"{WEBAPP_BASE_URL}/miniapp")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: set[int] = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()}

# ---------------------------------------------------------------------------
# Database pool
# ---------------------------------------------------------------------------
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=2,
            max_size=10,
        )
    return _pool


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            BIGINT PRIMARY KEY,
                username      TEXT,
                name          TEXT,
                photo_url     TEXT,
                skill_level   DOUBLE PRECISION NOT NULL DEFAULT 50.0 CHECK (skill_level >= 0 AND skill_level <= 100),
                goals         INTEGER NOT NULL DEFAULT 0,
                matches_played INTEGER NOT NULL DEFAULT 0,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished')),
                team_a      JSONB NOT NULL DEFAULT '[]'::jsonb,
                team_b      JSONB NOT NULL DEFAULT '[]'::jsonb,
                score_a     INTEGER NOT NULL DEFAULT 0,
                score_b     INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            );
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_skill_level ON users (skill_level DESC);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches (status);"
        )


# ---------------------------------------------------------------------------
# Telegram initData validation
# ---------------------------------------------------------------------------
def validate_init_data(init_data: str, bot_token: str) -> dict[str, str] | None:
    """
    Validate Telegram WebApp initData using the official algorithm.
    Returns parsed dict if valid, None otherwise.
    """
    try:
        parsed: dict[str, str] = {}
        for chunk in init_data.split("&"):
            key, _, value = chunk.partition("=")
            parsed[key] = urllib.parse.unquote(value)

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()

        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if computed_hash != received_hash:
            return None

        # Check auth_date freshness (optional: 1 hour)
        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date and (time.time() - auth_date > 86400):
            return None

        return parsed
    except Exception:
        return None


def extract_user_from_init_data(parsed: dict[str, str]) -> dict | None:
    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        return json.loads(user_json)
    except Exception:
        return None


async def get_current_user_id(authorization: str | None) -> int:
    """Extract and validate Telegram user from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.replace("Bearer ", "").strip()
    parsed = validate_init_data(token, BOT_TOKEN)
    if parsed is None:
        raise HTTPException(status_code=403, detail="Invalid initData")
    user = extract_user_from_init_data(parsed)
    if not user or "id" not in user:
        raise HTTPException(status_code=403, detail="Invalid user data")
    return int(user["id"])


# ---------------------------------------------------------------------------
# Balancing algorithm (greedy)
# ---------------------------------------------------------------------------
def balance_teams(player_ids: list[int], users_map: dict[int, dict]) -> tuple[list[int], list[int]]:
    """
    Greedy algorithm:
    - sort players by skill_level desc
    - assign each to the team with lower total skill (if equal — fewer players)
    """
    sorted_ids = sorted(
        player_ids,
        key=lambda pid: users_map[pid]["skill_level"],
        reverse=True,
    )
    team_a: list[int] = []
    team_b: list[int] = []
    sum_a = 0.0
    sum_b = 0.0
    for pid in sorted_ids:
        if sum_a < sum_b or (sum_a == sum_b and len(team_a) <= len(team_b)):
            team_a.append(pid)
            sum_a += users_map[pid]["skill_level"]
        else:
            team_b.append(pid)
            sum_b += users_map[pid]["skill_level"]
    return team_a, team_b


# ---------------------------------------------------------------------------
# Bot (aiogram 3.x)
# ---------------------------------------------------------------------------
bot: Bot | None = None
dp = Dispatcher()


def get_bot() -> Bot:
    global bot
    if bot is None:
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return bot


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "⚽ <b>Football Match Organizer</b>\n\n"
        "Добро пожаловать! Этот бот помогает организовывать футбольные матчи, "
        "формировать сбалансированные команды и вести статистику игроков.\n\n"
        "Нажмите кнопку ниже, чтобы открыть Mini App 👇"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚽ Открыть Mini App",
            web_app=WebAppInfo(url=MINIAPP_URL),
        )
    ]])
    await message.answer(text, reply_markup=kb)


@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username, name, skill_level, goals
            FROM users
            ORDER BY skill_level DESC, goals DESC
            LIMIT 10;
        """)
    if not rows:
        await message.answer("🏆 Пока нет зарегистрированных игроков.")
        return
    lines = ["🏆 <b>ТОП-10 игроков</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = f"@{r['username']}" if r["username"] else (r["name"] or "Игрок")
        lines.append(
            f"{medal} {name} — <b>{r['skill_level']:.1f}%</b> | ⚽ {r['goals']}"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("match"))
async def cmd_match(message: types.Message):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM matches WHERE status = 'active'
            ORDER BY created_at DESC LIMIT 1;
        """)
        if not row:
            await message.answer("Нет активного матча.")
            return

        team_a_ids = json.loads(row["team_a"]) if row["team_a"] else []
        team_b_ids = json.loads(row["team_b"]) if row["team_b"] else []
        all_ids = team_a_ids + team_b_ids
        if all_ids:
            placeholders = ",".join(f"${i+2}" for i in range(len(all_ids)))
            user_rows = await conn.fetch(
                f"SELECT id, username, name FROM users WHERE id IN ({placeholders})",
                row["id"], *all_ids,
            )
        else:
            user_rows = []
        users_map = {r["id"]: r for r in user_rows}

    def fmt_team(ids: list[int]) -> str:
        if not ids:
            return "—"
        return "\n".join(
            f"  • {users_map.get(uid, {}).get('username') or users_map.get(uid, {}).get('name') or 'Игрок'}"
            for uid in ids
        )

    text = (
        "⚽ <b>Активный матч</b>\n\n"
        f"<b>Команда A</b> ({row['score_a']})\n{fmt_team(team_a_ids)}\n\n"
        f"<b>Команда B</b> ({row['score_b']})\n{fmt_team(team_b_ids)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚽ Открыть Mini App",
            web_app=WebAppInfo(url=MINIAPP_URL),
        )
    ]])
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    await init_db()
    bot = get_bot()
    webhook_url = f"{WEBAPP_BASE_URL}/bot/webhook"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    print(f"Webhook set to {webhook_url}")
    yield
    await bot.delete_webhook()
    if _pool:
        await _pool.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/miniapp", response_class=HTMLResponse)
async def miniapp():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/bot/webhook")
async def bot_webhook(request: Request):
    data = await request.json()
    update = types.Update.model_validate(data, context={"bot": get_bot()})
    await dp.feed_update(get_bot(), update)
    return JSONResponse({"ok": True})


# ------------------- API endpoints for Mini App -------------------

@app.get("/api/me")
async def api_me(authorization: str | None = Header(None)):
    uid = await get_current_user_id(authorization)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, name, photo_url, skill_level, goals, matches_played FROM users WHERE id = $1",
            uid,
        )
    if row:
        return {"registered": True, "user": dict(row)}
    # Return minimal info from initData
    token = authorization.replace("Bearer ", "").strip()
    parsed = validate_init_data(token, BOT_TOKEN)
    user = extract_user_from_init_data(parsed) if parsed else {}
    return {
        "registered": False,
        "user": {
            "id": uid,
            "username": user.get("username", ""),
            "name": user.get("first_name", ""),
            "photo_url": user.get("photo_url", ""),
        },
    }


@app.post("/api/register")
async def api_register(request: Request, authorization: str | None = Header(None)):
    uid = await get_current_user_id(authorization)
    body = await request.json()
    skill = float(body.get("skill_level", 50.0))
    skill = max(0.0, min(100.0, skill))

    token = authorization.replace("Bearer ", "").strip()
    parsed = validate_init_data(token, BOT_TOKEN)
    user = extract_user_from_init_data(parsed) if parsed else {}

    username = user.get("username", "")
    name = user.get("first_name", "")
    photo_url = user.get("photo_url", "")

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE id = $1", uid)
        if existing:
            await conn.execute(
                "UPDATE users SET username=$1, name=$2, photo_url=$3, skill_level=$4 WHERE id=$5",
                username, name, photo_url, skill, uid,
            )
        else:
            await conn.execute(
                """INSERT INTO users (id, username, name, photo_url, skill_level)
                   VALUES ($1, $2, $3, $4, $5)""",
                uid, username, name, photo_url, skill,
            )
        row = await conn.fetchrow(
            "SELECT id, username, name, photo_url, skill_level, goals, matches_played FROM users WHERE id = $1",
            uid,
        )
    return {"registered": True, "user": dict(row)}


@app.get("/api/users")
async def api_users(authorization: str | None = Header(None)):
    await get_current_user_id(authorization)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, username, name, photo_url, skill_level, goals, matches_played FROM users ORDER BY skill_level DESC"
        )
    return {"users": [dict(r) for r in rows]}


def is_admin(uid: int) -> bool:
    if not ADMIN_IDS:
        return True  # everyone can create matches
    return uid in ADMIN_IDS


@app.post("/api/match/create")
async def api_create_match(request: Request, authorization: str | None = Header(None)):
    uid = await get_current_user_id(authorization)
    if not is_admin(uid):
        raise HTTPException(status_code=403, detail="Only admin can create matches")
    body = await request.json()
    player_ids: list[int] = [int(x) for x in body.get("player_ids", [])]
    if len(player_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 players required")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Fetch skill levels
        rows = await conn.fetch(
            "SELECT id, username, name, photo_url, skill_level FROM users WHERE id = ANY($1::bigint[])",
            player_ids,
        )
        users_map = {r["id"]: dict(r) for r in rows}
        if len(users_map) != len(player_ids):
            missing = set(player_ids) - set(users_map.keys())
            raise HTTPException(status_code=400, detail=f"Users not found: {missing}")

        team_a, team_b = balance_teams(player_ids, users_map)

        # Deactivate old active matches
        await conn.execute("UPDATE matches SET status='finished' WHERE status='active'")

        row = await conn.fetchrow(
            """INSERT INTO matches (status, team_a, team_b)
               VALUES ('active', $1, $2) RETURNING id, status, team_a, team_b, score_a, score_b""",
            json.dumps(team_a), json.dumps(team_b),
        )
    return {"match": dict(row)}


@app.get("/api/match/active")
async def api_active_match(authorization: str | None = Header(None)):
    await get_current_user_id(authorization)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM matches WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        )
    if not row:
        return {"match": None}
    return {"match": dict(row)}


@app.post("/api/match/score")
async def api_update_score(request: Request, authorization: str | None = Header(None)):
    uid = await get_current_user_id(authorization)
    if not is_admin(uid):
        raise HTTPException(status_code=403, detail="Only admin can update score")
    body = await request.json()
    match_id = body["match_id"]
    team = body["team"]  # 'a' or 'b'
    delta = int(body["delta"])  # +1 or -1

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM matches WHERE id=$1 AND status='active'", UUID(match_id))
        if not row:
            raise HTTPException(status_code=404, detail="Active match not found")

        col = "score_a" if team == "a" else "score_b"
        new_val = max(0, row[col] + delta)
        await conn.execute(f"UPDATE matches SET {col}=$1 WHERE id=$2", new_val, UUID(match_id))
        row = await conn.fetchrow("SELECT * FROM matches WHERE id=$1", UUID(match_id))
    return {"match": dict(row)}


@app.post("/api/match/finish")
async def api_finish_match(request: Request, authorization: str | None = Header(None)):
    uid = await get_current_user_id(authorization)
    if not is_admin(uid):
        raise HTTPException(status_code=403, detail="Only admin can finish matches")
    body = await request.json()
    match_id = body["match_id"]
    score_a = int(body.get("score_a", 0))
    score_b = int(body.get("score_b", 0))

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM matches WHERE id=$1 AND status='active'", UUID(match_id))
        if not row:
            raise HTTPException(status_code=404, detail="Active match not found")

        team_a_ids: list[int] = json.loads(row["team_a"]) if row["team_a"] else []
        team_b_ids: list[int] = json.loads(row["team_b"]) if row["team_b"] else []

        # Determine winner
        if score_a > score_b:
            winner = "a"
        elif score_b > score_a:
            winner = "b"
        else:
            winner = "draw"

        # Parse goals per player from request body (optional)
        goals_input: dict[str, int] = body.get("goals", {})

        await conn.execute(
            "UPDATE matches SET status='finished', score_a=$1, score_b=$2, finished_at=now() WHERE id=$3",
            score_a, score_b, UUID(match_id),
        )

        # Process each player
        async def process_player(pid: int, team: str):
            goals = int(goals_input.get(str(pid), 0))
            if team == winner:
                skill_delta = 2.0 + goals * 1.0
            elif winner == "draw":
                skill_delta = goals * 1.0
            else:
                skill_delta = -1.0 + goals * 1.0

            await conn.execute("""
                UPDATE users
                SET skill_level = LEAST(100.0, GREATEST(0.0, skill_level + $1)),
                    goals = goals + $2,
                    matches_played = matches_played + 1
                WHERE id = $3
            """, skill_delta, goals, pid)

        for pid in team_a_ids:
            await process_player(pid, "a")
        for pid in team_b_ids:
            await process_player(pid, "b")

        # Return updated users
        all_ids = team_a_ids + team_b_ids
        if all_ids:
            rows = await conn.fetch(
                "SELECT id, username, name, photo_url, skill_level, goals, matches_played FROM users WHERE id = ANY($1::bigint[])",
                all_ids,
            )
        else:
            rows = []
        users = [dict(r) for r in rows]

    return {"finished": True, "score_a": score_a, "score_b": score_b, "winner": winner, "users": users}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entrypoint — run uvicorn + bot in one event loop
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
