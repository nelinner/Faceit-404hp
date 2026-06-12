import asyncio
import logging
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
import random

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ChatMemberStatus

# ---------- КОНФИГУРАЦИЯ ----------
TOKEN = "8254209430:AAEGZGjdnzSXFUudGjF9MOydkU7s8QyDR28"
PROJECT_NAME = "404hp FACEIT"
GAME_NAME = "Standoff 2"
CHANNEL_ID = "@hp404faceit"
HEAD_ADMIN_USERNAME = "nelinner"

DB_PATH = "/storage/emulated/0/404hp_faceit.db"

MAIN_MENU_IMAGE = "https://ibb.co/yczGh1yQ"          # Главное меню
REGISTRATION_IMAGE = "https://ibb.co/SD6Sz7Tf"     # Регистрация
LEADERBOARD_IMAGE = "https://ibb.co/spHJL8t7"       # Рейтинг
LOBBY_CREATE_IMAGE = "https://ibb.co/FLk3W6KR"     # Создание лобби

class UserRole:
    PLAYER = "player"
    PREMIUM = "premium"
    ADMIN = "admin"
    HEAD_ADMIN = "head_admin"
    DIRECTOR = "director"

ROLE_NAMES = {
    UserRole.PLAYER: "🎮 Обычный игрок",
    UserRole.PREMIUM: "⭐ Premium",
    UserRole.ADMIN: "🛡 Админ",
    UserRole.HEAD_ADMIN: "👑 Главный админ",
    UserRole.DIRECTOR: "⚡ Руководитель"
}

MAPS = {
    "sandstone": "🏝 Sandstone", "dune": "🏜 Dune", "province": "🏘 Province",
    "rust": "🏗 Rust", "breeze": "🌴 Breeze", "hanami": "🌸 Hanami", "prison": "🔒 Prison"
}

RANKS = {
    1:  {"name": "🎯 Уровень 1",  "min_elo": 0,    "max_elo": 199},
    2:  {"name": "🎯 Уровень 2",  "min_elo": 200,  "max_elo": 399},
    3:  {"name": "🎯 Уровень 3",  "min_elo": 400,  "max_elo": 599},
    4:  {"name": "🎯 Уровень 4",  "min_elo": 600,  "max_elo": 799},
    5:  {"name": "🎯 Уровень 5",  "min_elo": 800,  "max_elo": 999},
    6:  {"name": "🎯 Уровень 6",  "min_elo": 1000, "max_elo": 1199},
    7:  {"name": "💎 Уровень 7",  "min_elo": 1200, "max_elo": 1399},
    8:  {"name": "👑 Уровень 8",  "min_elo": 1400, "max_elo": 1599},
    9:  {"name": "🌟 Уровень 9",  "min_elo": 1600, "max_elo": 1799},
    10: {"name": "⚡ Уровень 10", "min_elo": 1800, "max_elo": 9999}
}

# ---------- ИНИЦИАЛИЗАЦИЯ ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, nickname TEXT UNIQUE,
        password_hash TEXT, salt TEXT, elo INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1, rank TEXT DEFAULT "🎯 Уровень 1",
        role TEXT DEFAULT "player", matches_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0, winrate REAL DEFAULT 0.0,
        kd_ratio REAL DEFAULT 0.0, total_kills INTEGER DEFAULT 0,
        total_deaths INTEGER DEFAULT 0, headshots INTEGER DEFAULT 0,
        mvps INTEGER DEFAULT 0, registration_date TEXT,
        last_match_date TEXT, is_banned INTEGER DEFAULT 0,
        ban_reason TEXT
    )''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN premium_expiry TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS lobbies (
        lobby_id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER,
        lobby_code TEXT UNIQUE, map_name TEXT, max_players INTEGER DEFAULT 10,
        current_players INTEGER DEFAULT 1, status TEXT DEFAULT 'open',
        created_at TEXT, message_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS lobby_players (
        lobby_id INTEGER, user_id INTEGER, nickname TEXT, role TEXT,
        join_order INTEGER, joined_at TEXT,
        PRIMARY KEY (lobby_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS match_teams (
        team_id INTEGER PRIMARY KEY AUTOINCREMENT, lobby_id INTEGER,
        team_side TEXT, created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS team_players (
        team_id INTEGER, user_id INTEGER, nickname TEXT, position INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT
    )''')
    conn.commit()
    conn.close()

def one_time_elo_reset():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='elo_reset_done'")
    if not c.fetchone():
        c.execute("UPDATE users SET elo=0, rank='🎯 Уровень 1', level=1")
        c.execute("INSERT INTO settings (key, value) VALUES ('elo_reset_done', '1')")
        conn.commit()
        logger.info("✅ Все игроки получили 0 ELO (однократный сброс)")
    conn.close()

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def hash_password(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    h = hashlib.sha256((password + salt).encode()).hexdigest()
    return h, salt

def verify_password(password, salt, stored_hash):
    return hashlib.sha256((password + salt).encode()).hexdigest() == stored_hash

def escape_html(text):
    if not text: return ""
    for char, esc in [('&','&amp;'),('<','&lt;'),('>','&gt;')]:
        text = text.replace(char, esc)
    return text

async def check_sub(user_id):
    try:
        ch = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return ch.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return False

def get_rank(elo):
    for r in RANKS.values():
        if r["min_elo"] <= elo <= r["max_elo"]: return r
    return RANKS[10]

def gen_lobby_code(): return secrets.token_hex(4).upper()

def is_player_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_match_date, ban_reason FROM users WHERE user_id=? AND is_banned=1", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            ban_until = datetime.fromisoformat(row[0])
            if ban_until > datetime.now():
                return True, ban_until, row[1]
        except:
            pass
    return False, None, None

def ban_player(user_id, duration_minutes, reason="Нарушение правил"):
    ban_until = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1, ban_reason=?, last_match_date=? WHERE user_id=?", 
              (reason, ban_until, user_id))
    conn.commit()
    conn.close()
    return ban_until

def unban_player(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0, ban_reason=NULL, last_match_date=NULL WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_lobby_players_text(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT nickname, role FROM lobby_players WHERE lobby_id=? ORDER BY join_order", (lobby_id,))
    players = c.fetchall()
    c.execute("SELECT current_players, max_players FROM lobbies WHERE lobby_id=?", (lobby_id,))
    cur, maxp = c.fetchone()
    conn.close()
    txt = f"👥 <b>Игроки ({cur}/{maxp})</b>\n"
    for nick, role in players:
        em = {"director":"⚡","head_admin":"👑","admin":"🛡","premium":"⭐"}.get(role,"🎮")
        txt += f"• {em} {nick}\n"
    if cur < maxp: txt += f"\n🟢 Ожидаем ещё {maxp-cur} игроков"
    return txt

def get_lobby_players_list(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT team_id, team_side FROM match_teams WHERE lobby_id=?", (lobby_id,))
    teams = c.fetchall()
    if len(teams) != 2:
        conn.close()
        return None, None, None, None
    ct_team_id = t_team_id = None
    for team in teams:
        if team[1] == 'CT': ct_team_id = team[0]
        else: t_team_id = team[0]
    c.execute("""SELECT tp.user_id, tp.nickname, u.elo 
                 FROM team_players tp JOIN users u ON tp.user_id=u.user_id 
                 WHERE tp.team_id=? ORDER BY tp.position""", (ct_team_id,))
    ct_players = c.fetchall()
    c.execute("""SELECT tp.user_id, tp.nickname, u.elo 
                 FROM team_players tp JOIN users u ON tp.user_id=u.user_id 
                 WHERE tp.team_id=? ORDER BY tp.position""", (t_team_id,))
    t_players = c.fetchall()
    conn.close()
    return ct_players, t_players, ct_team_id, t_team_id

async def update_lobby_post(lobby_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT l.message_id, l.map_name, l.lobby_code, l.status, l.current_players,
                 u.nickname, u.elo, u.rank
                 FROM lobbies l JOIN users u ON l.creator_id=u.user_id
                 WHERE l.lobby_id=?""", (lobby_id,))
    lobby = c.fetchone()
    conn.close()
    if not lobby or not lobby[0]: return
    players = get_lobby_players_text(lobby_id)
    text = (
        f"🔰 <b>ЛОББИ #{lobby_id}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Создатель:</b> {escape_html(lobby[5])}\n"
        f"🏅 Ранг: {escape_html(lobby[7])} | ELO: {lobby[6]}\n\n"
        f"🗺 <b>Карта:</b> {MAPS[lobby[1]]}\n"
        f"🔑 <b>Код:</b> <code>{lobby[2]}</code>\n\n{players}\n"
    )
    if lobby[4] < 10:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔰 ПРИСОЕДИНИТЬСЯ", callback_data=f"join_lobby_{lobby_id}")]
        ])
    else:
        text += "\n🎯 Все собраны! Жеребьёвка доступна."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 ЖЕРЕБЬЁВКА", callback_data=f"draw_teams_{lobby_id}")]
        ])
    try:
        await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=lobby[0], text=text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error(f"Ошибка обновления поста лобби: {e}")

def update_stats(user_id, winner):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT elo, matches_played, wins, losses, winrate FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    if not u: conn.close(); return
    change = random.randint(15,35) if winner else random.randint(10,30)
    new_elo = max(0, u[0] + change if winner else u[0] - change)
    new_rank = get_rank(new_elo)["name"]
    m, w, l = u[1]+1, u[2]+(1 if winner else 0), u[3]+(0 if winner else 1)
    wr = round(w/m*100,1)
    c.execute("UPDATE users SET elo=?, rank=?, matches_played=?, wins=?, losses=?, winrate=?, last_match_date=? WHERE user_id=?",
              (new_elo, new_rank, m, w, l, wr, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()
    asyncio.create_task(bot.send_message(user_id,
        f"📊 Статистика обновлена!\n{'✅ Победа' if winner else '❌ Поражение'}\nELO: {u[0]} → {new_elo} ({'+' if winner else '-'}{change})\nРанг: {new_rank}\nWinrate: {wr}%",
        parse_mode="Markdown"))

def is_premium_active(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT premium_expiry FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            expiry = datetime.fromisoformat(row[0])
            return expiry > datetime.now()
        except:
            return False
    return False

def has_permission(user_id, permission):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, premium_expiry FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    if not user: return False
    role, expiry = user
    if role == UserRole.DIRECTOR: return True
    if permission == "create_lobby":
        if role in [UserRole.PREMIUM, UserRole.ADMIN, UserRole.HEAD_ADMIN]: return True
        if expiry:
            try:
                if datetime.fromisoformat(expiry) > datetime.now(): return True
            except: pass
        return False
    permissions = {
        UserRole.PLAYER: [],
        UserRole.PREMIUM: ["create_lobby", "priority_match"],
        UserRole.ADMIN: ["ban_users", "manage_tournaments", "create_lobby"],
        UserRole.HEAD_ADMIN: ["ban_users", "manage_tournaments", "manage_admins", "create_lobby", "edit_ranks"],
        UserRole.DIRECTOR: ["*"]
    }
    allowed = permissions.get(role, [])
    return permission in allowed or "*" in allowed

def main_menu(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    role = row[0] if row else UserRole.PLAYER
    kb = [
        [InlineKeyboardButton(text="🎮 НАЙТИ МАТЧ", callback_data="find_match")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ]
    if has_permission(user_id, "create_lobby"):
        kb.insert(1, [InlineKeyboardButton(text="🔰 СОЗДАТЬ ЛОББИ", callback_data="create_lobby")])
    if role in [UserRole.ADMIN, UserRole.HEAD_ADMIN, UserRole.DIRECTOR]:
        kb.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    kb.append([InlineKeyboardButton(text="ℹ️ Правила", callback_data="rules")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🚫 Бан-лист", callback_data="admin_bans")],
        [InlineKeyboardButton(text="🔄 Заменить игрока", callback_data="replace_player")],
        [InlineKeyboardButton(text="🔨 Забанить игрока", callback_data="ban_leaver")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="unban_player")],
        [InlineKeyboardButton(text="👑 Назначить админа", callback_data="admin_assign")],
        [InlineKeyboardButton(text="⭐ Premium: выдать", callback_data="premium_give")],
        [InlineKeyboardButton(text="❌ Premium: забрать", callback_data="premium_revoke")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_main")]
    ])

# ---------- FSM ----------
class Reg(StatesGroup):
    nick = State(); pw = State(); pw2 = State(); confirm = State()

class LobbyFSM(StatesGroup):
    map = State(); confirm = State()

class MatchResFSM(StatesGroup):
    photo = State(); score = State(); swap_sides = State()

class AdminFSM(StatesGroup):
    assign = State(); premium_user = State(); premium_duration = State()

class PremiumRevoke(StatesGroup):
    user = State()

class BanFSM(StatesGroup):
    waiting_user = State(); waiting_reason = State(); waiting_duration = State()

class ReplacePlayerFSM(StatesGroup):
    waiting_lobby = State(); waiting_old_player = State()
    waiting_new_player = State(); confirm_replace = State()

# ---------- /start ----------
@dp.message(Command("start"))
async def start(msg: types.Message, state: FSMContext):
    if not await check_sub(msg.from_user.id):
        await msg.answer_photo(MAIN_MENU_IMAGE,
            caption=f"🔒 Подпишитесь на {CHANNEL_ID}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_ID[1:]}")],
                [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
            ]))
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,))
    u = c.fetchone()
    conn.close()
    if not u:
        await msg.answer_photo(REGISTRATION_IMAGE, caption="Введите игровой никнейм:")
        await state.set_state(Reg.nick)
    else:
        is_banned, ban_until, ban_reason = is_player_banned(msg.from_user.id)
        if is_banned:
            await msg.answer_photo(MAIN_MENU_IMAGE,
                caption=f"⛔ **Временная блокировка**\n\nПричина: {ban_reason or 'Не указана'}\nРазблокировка: {ban_until.strftime('%d.%m.%Y %H:%M')}")
            return
        if len(u) > 21 and u[21]:
            await msg.answer_photo(MAIN_MENU_IMAGE, caption="⛔ Забанен навсегда")
        else:
            await msg.answer_photo(MAIN_MENU_IMAGE,
                caption=f"👋 {u[2]}\n🎭 {ROLE_NAMES.get(u[8], 'Игрок')}\n🏅 {u[7]} | ELO: {u[4]} | Матчей: {u[9]}\nВыберите действие:",
                reply_markup=main_menu(msg.from_user.id))

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_btn(cb: types.CallbackQuery):
    if await check_sub(cb.from_user.id):
        await cb.message.delete()
        await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption="✅ Подписка подтверждена! Используйте /start")
    else:
        await cb.answer("❌ Не подписаны", show_alert=True)

# ---------- РЕГИСТРАЦИЯ ----------
@dp.message(Reg.nick)
async def reg_nick(msg: types.Message, state: FSMContext):
    nick = msg.text.strip()
    if len(nick)<3 or len(nick)>24 or not nick.replace('_','').replace('-','').isalnum():
        await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Некорректный ник"); return
    conn = sqlite3.connect(DB_PATH)
    if conn.execute("SELECT 1 FROM users WHERE nickname=?", (nick,)).fetchone():
        await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Занят"); conn.close(); return
    conn.close()
    await state.update_data(nick=nick)
    await msg.answer_photo(REGISTRATION_IMAGE, caption="🔐 Придумайте пароль (мин. 6 символов):")
    await state.set_state(Reg.pw)

@dp.message(Reg.pw)
async def reg_pw(msg: types.Message, state: FSMContext):
    pw = msg.text.strip()
    if len(pw)<6: await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Минимум 6"); return
    await state.update_data(pw=pw)
    await msg.answer_photo(REGISTRATION_IMAGE, caption="🔐 Повторите пароль:")
    await state.set_state(Reg.pw2)

@dp.message(Reg.pw2)
async def reg_pw2(msg: types.Message, state: FSMContext):
    if msg.text.strip() != (await state.get_data())['pw']:
        await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Не совпадают. Введите заново:")
        await state.set_state(Reg.pw); return
    data = await state.get_data()
    nick, pw = data['nick'], data['pw']
    user_id = msg.from_user.id
    uname = msg.from_user.username or msg.from_user.full_name
    is_dir = (msg.from_user.username == HEAD_ADMIN_USERNAME)
    role = UserRole.DIRECTOR if is_dir else UserRole.PLAYER
    h, s = hash_password(pw)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO users (user_id,username,nickname,password_hash,salt,role,registration_date) VALUES (?,?,?,?,?,?,?)",
                 (user_id, uname, nick, h, s, role, datetime.now().isoformat()))
    conn.commit(); conn.close()
    await msg.answer_photo(REGISTRATION_IMAGE,
        caption=f"✅ Регистрация завершена!\nДобро пожаловать, {nick}!\nРоль: {ROLE_NAMES[role]}\nНачальный ELO: 0\nДля входа: /login {nick} ваш_пароль",
        reply_markup=main_menu(msg.from_user.id))
    await state.clear()

# ---------- ЛОГИН ----------
@dp.message(Command("login"))
async def login(msg: types.Message):
    parts = msg.text.split()
    if len(parts)!=3: await msg.answer_photo(MAIN_MENU_IMAGE, caption="/login ник пароль"); return
    nick, pw = parts[1], parts[2]
    conn = sqlite3.connect(DB_PATH)
    u = conn.execute("SELECT user_id, password_hash, salt, role FROM users WHERE nickname=?", (nick,)).fetchone()
    conn.close()
    if not u: await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Не найден"); return
    if verify_password(pw, u[2], u[1]):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE users SET user_id=? WHERE nickname=?", (msg.from_user.id, nick))
        conn.commit(); conn.close()
        await msg.answer_photo(MAIN_MENU_IMAGE, caption=f"✅ Вход выполнен!\nРоль: {ROLE_NAMES[u[3]]}")
    else: await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Неверный пароль")

# ---------- СОЗДАНИЕ ЛОББИ ----------
@dp.callback_query(lambda c: c.data == "create_lobby")
async def lobby_start(cb: types.CallbackQuery, state: FSMContext):
    if not has_permission(cb.from_user.id, "create_lobby"):
        await cb.answer("❌ Нет прав", show_alert=True); return
    kb = [[InlineKeyboardButton(text=v, callback_data=f"lobby_map_{k}")] for k,v in MAPS.items()]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, LOBBY_CREATE_IMAGE,
        caption="🗺 Выберите карту для лобби:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(LobbyFSM.map)

@dp.callback_query(lambda c: c.data.startswith("lobby_map_"), LobbyFSM.map)
async def lobby_map(cb: types.CallbackQuery, state: FSMContext):
    map_id = cb.data.split("_")[2]
    code = gen_lobby_code()
    await state.update_data(map=map_id, code=code)
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, LOBBY_CREATE_IMAGE,
        caption=f"🔰 Создание лобби\n🗺 {MAPS[map_id]}\n🔑 Код: {code}\n\nПодтвердите:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="publish_lobby"),
             InlineKeyboardButton(text="🔄 Сменить", callback_data="create_lobby")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")]
        ]))
    await state.set_state(LobbyFSM.confirm)

@dp.callback_query(lambda c: c.data == "publish_lobby", LobbyFSM.confirm)
async def publish_lobby(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    map_id, code = data['map'], data['code']
    user_id = cb.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT nickname, elo, rank, role FROM users WHERE user_id=?", (user_id,))
    creator = c.fetchone()
    c.execute("INSERT INTO lobbies (creator_id, lobby_code, map_name, created_at) VALUES (?,?,?,?)",
              (user_id, code, map_id, datetime.now().isoformat()))
    lobby_id = c.lastrowid
    c.execute("INSERT INTO lobby_players (lobby_id, user_id, nickname, role, join_order, joined_at) VALUES (?,?,?,?,1,?)",
              (lobby_id, user_id, creator[0], creator[3], datetime.now().isoformat()))
    conn.commit()
    players = get_lobby_players_text(lobby_id)
    post_text = (f"🔰 <b>ЛОББИ #{lobby_id}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                 f"👤 <b>Создатель:</b> {escape_html(creator[0])}\n"
                 f"🏅 {escape_html(creator[2])} | ELO: {creator[1]}\n\n"
                 f"🗺 <b>Карта:</b> {MAPS[map_id]}\n"
                 f"🔑 <b>Код:</b> <code>{code}</code>\n\n{players}\n\n"
                 f"⚡ Нажмите кнопку, чтобы присоединиться 👇")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔰 ПРИСОЕДИНИТЬСЯ", callback_data=f"join_lobby_{lobby_id}")]
    ])
    try:
        msg_sent = await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML", reply_markup=kb)
        c.execute("UPDATE lobbies SET message_id=? WHERE lobby_id=?", (msg_sent.message_id, lobby_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Публикация лобби: {e}")
        await cb.message.answer(f"❌ Ошибка публикации: {e}")
        conn.close(); await state.clear(); return
    conn.close()
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, LOBBY_CREATE_IMAGE,
        caption=f"✅ Лобби создано!\n🔑 Код: {code}\n🗺 {MAPS[map_id]}\n👥 1/10\nОпубликовано в {CHANNEL_ID}")
    await state.clear()

# ---------- ПРИСОЕДИНЕНИЕ К ЛОББИ ----------
@dp.callback_query(lambda c: c.data.startswith("join_lobby_"))
async def join_lobby_btn(cb: types.CallbackQuery):
    lobby_id = int(cb.data.split("_")[2])
    user_id = cb.from_user.id
    is_banned, ban_until, _ = is_player_banned(user_id)
    if is_banned:
        await cb.answer(f"⛔ Вы заблокированы до {ban_until.strftime('%H:%M %d.%m')}", show_alert=True)
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT creator_id, current_players, max_players, status FROM lobbies WHERE lobby_id=? AND status='open'", (lobby_id,))
    lobby = c.fetchone()
    if not lobby: await cb.answer("Лобби не найдено или закрыто", show_alert=True); conn.close(); return
    if lobby[1] >= lobby[2]: await cb.answer("Лобби заполнено", show_alert=True); conn.close(); return
    if c.execute("SELECT 1 FROM lobby_players WHERE lobby_id=? AND user_id=?", (lobby_id, user_id)).fetchone():
        await cb.answer("Вы уже в лобби", show_alert=True); conn.close(); return
    c.execute("SELECT nickname, role FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user: await cb.answer("Вы не зарегистрированы", show_alert=True); conn.close(); return
    new_cnt = lobby[1] + 1
    c.execute("INSERT INTO lobby_players (lobby_id, user_id, nickname, role, join_order, joined_at) VALUES (?,?,?,?,?,?)",
              (lobby_id, user_id, user[0], user[1], new_cnt, datetime.now().isoformat()))
    c.execute("UPDATE lobbies SET current_players=? WHERE lobby_id=?", (new_cnt, lobby_id))
    conn.commit(); conn.close()
    await update_lobby_post(lobby_id)
    if new_cnt >= lobby[2]:
        await bot.send_message(lobby[0], f"🎯 Лобби #{lobby_id} заполнено! Нажмите кнопку в канале для жеребьёвки.")
    await cb.answer(f"✅ Вы присоединились ({new_cnt}/10)", show_alert=True)

# ---------- ЖЕРЕБЬЁВКА ----------
@dp.callback_query(lambda c: c.data.startswith("draw_teams_"))
async def draw_teams(cb: types.CallbackQuery):
    lobby_id = int(cb.data.split("_")[2])
    user_id = cb.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT creator_id, current_players FROM lobbies WHERE lobby_id=?", (lobby_id,))
    lobby = c.fetchone()
    if not lobby or lobby[1] < 10: await cb.answer("Недостаточно игроков", show_alert=True); conn.close(); return
    c.execute("SELECT role FROM users WHERE user_id=?", (user_id,))
    role = c.fetchone()
    if user_id != lobby[0] and (not role or role[0] not in [UserRole.ADMIN, UserRole.HEAD_ADMIN, UserRole.DIRECTOR]):
        await cb.answer("Только создатель/админ", show_alert=True); conn.close(); return
    c.execute("SELECT lp.user_id, lp.nickname, lp.role, u.elo FROM lobby_players lp JOIN users u ON lp.user_id=u.user_id WHERE lp.lobby_id=? ORDER BY lp.join_order", (lobby_id,))
    players = c.fetchall()
    random.shuffle(players)
    ct, t = players[:5], players[5:10]
    c.execute("INSERT INTO match_teams (lobby_id, team_side, created_at) VALUES (?, 'CT', ?)", (lobby_id, datetime.now().isoformat()))
    ct_id = c.lastrowid
    for i,p in enumerate(ct): c.execute("INSERT INTO team_players (team_id, user_id, nickname, position) VALUES (?,?,?,?)", (ct_id, p[0], p[1], i+1))
    c.execute("INSERT INTO match_teams (lobby_id, team_side, created_at) VALUES (?, 'T', ?)", (lobby_id, datetime.now().isoformat()))
    t_id = c.lastrowid
    for i,p in enumerate(t): c.execute("INSERT INTO team_players (team_id, user_id, nickname, position) VALUES (?,?,?,?)", (t_id, p[0], p[1], i+1))
    c.execute("UPDATE lobbies SET status='closed' WHERE lobby_id=?", (lobby_id,))
    conn.commit(); conn.close()
    text = f"🎲 <b>ЖЕРЕБЬЁВКА</b>\nЛобби #{lobby_id}\n━━━━━━━━━━━━━━━━━━━━━━\n\n🔵 <b>CT:</b>\n"
    for i,p in enumerate(ct): text += f"{i+1}. {p[1]} (ELO: {p[3]})\n"
    text += "\n🔴 <b>T:</b>\n"
    for i,p in enumerate(t): text += f"{i+1}. {p[1]} (ELO: {p[3]})\n"
    text += "\n🎯 Удачной игры!\nПосле матча: /match_result"
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    for p in players:
        try: await bot.send_message(p[0], f"Жеребьёвка лобби #{lobby_id}\nВаша команда: {'CT' if p in ct else 'T'}")
        except: pass
    await cb.answer("✅ Жеребьёвка завершена", show_alert=True)

# ---------- РЕГИСТРАЦИЯ РЕЗУЛЬТАТА ----------
@dp.message(Command("match_result"))
async def match_result_start(msg: types.Message, state: FSMContext):
    if not await is_admin(msg.from_user.id): await msg.answer("❌ Только админ"); return
    await msg.answer_photo(MAIN_MENU_IMAGE, caption="📸 Отправьте скриншот результата:")
    await state.set_state(MatchResFSM.photo)

async def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    role = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return role and role[0] in [UserRole.ADMIN, UserRole.HEAD_ADMIN, UserRole.DIRECTOR]

@dp.message(MatchResFSM.photo, F.photo)
async def match_result_photo(msg: types.Message, state: FSMContext):
    await state.update_data(photo=msg.photo[-1].file_id)
    await msg.answer_photo(MAIN_MENU_IMAGE, caption="📊 Введите счёт: CT T номер_лобби\nПример: 16 14 5")
    await state.set_state(MatchResFSM.score)

@dp.message(MatchResFSM.score)
async def match_result_score(msg: types.Message, state: FSMContext):
    try:
        ct, t, lid = map(int, msg.text.split())
        data = await state.get_data()
        photo = data['photo']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        teams = c.execute("SELECT team_id, team_side FROM match_teams WHERE lobby_id=?", (lid,)).fetchall()
        if len(teams)!=2: await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Лобби не найдено"); conn.close(); return
        conn.close()
        await state.update_data(ct_score=ct, t_score=t, lobby_id=lid)
        await msg.answer_photo(MAIN_MENU_IMAGE,
            caption="🔄 Менялись ли команды сторонами?\n\n✅ Да — нажмите, если CT и T поменялись\n❌ Нет — если играли как в жеребьёвке",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, поменялись", callback_data="swap_yes"),
                 InlineKeyboardButton(text="❌ Нет, как в жеребьёвке", callback_data="swap_no")]
            ]))
        await state.set_state(MatchResFSM.swap_sides)
    except ValueError:
        await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Неверный формат. Пример: 16 14 5")
    except Exception as e:
        logger.error(f"Ошибка в match_result_score: {e}")
        await msg.answer_photo(MAIN_MENU_IMAGE, caption=f"❌ Ошибка: {e}")
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith("swap_"), MatchResFSM.swap_sides)
async def process_swap_sides(cb: types.CallbackQuery, state: FSMContext):
    swap = cb.data == "swap_yes"
    data = await state.get_data()
    photo = data['photo']; ct_score = data['ct_score']; t_score = data['t_score']; lobby_id = data['lobby_id']
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    teams = c.execute("SELECT team_id, team_side FROM match_teams WHERE lobby_id=?", (lobby_id,)).fetchall()
    ct_team_id = t_team_id = None
    for team in teams:
        if team[1] == 'CT': ct_team_id = team[0]
        else: t_team_id = team[0]
    ct_players = c.execute("SELECT tp.user_id, tp.nickname, u.elo FROM team_players tp JOIN users u ON tp.user_id=u.user_id WHERE tp.team_id=? ORDER BY tp.position", (ct_team_id,)).fetchall()
    t_players = c.execute("SELECT tp.user_id, tp.nickname, u.elo FROM team_players tp JOIN users u ON tp.user_id=u.user_id WHERE tp.team_id=? ORDER BY tp.position", (t_team_id,)).fetchall()
    if swap:
        display_ct, display_t = t_players, ct_players
        ct_won = ct_score > t_score
        for p in t_players: update_stats(p[0], ct_won)
        for p in ct_players: update_stats(p[0], not ct_won)
        swap_text = "🔄 Команды поменялись сторонами"
    else:
        display_ct, display_t = ct_players, t_players
        ct_won = ct_score > t_score
        for p in ct_players: update_stats(p[0], ct_won)
        for p in t_players: update_stats(p[0], not ct_won)
        swap_text = "✅ Команды играли как в жеребьёвке"
    map_name = c.execute("SELECT map_name FROM lobbies WHERE lobby_id=?", (lobby_id,)).fetchone()
    map_name = map_name[0] if map_name else "Неизвестно"
    conn.commit(); conn.close()
    txt = (f"📊 <b>РЕЗУЛЬТАТ МАТЧА</b>\nЛобби #{lobby_id}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
           f"🗺 {MAPS.get(map_name, map_name)}\n\n{swap_text}\n\n🔵 <b>CT (в игре):</b> {ct_score}\n")
    for i,p in enumerate(display_ct): txt += f"{i+1}. {p[1]} (ELO: {p[2]})\n"
    txt += f"\n🔴 <b>T (в игре):</b> {t_score}\n"
    for i,p in enumerate(display_t): txt += f"{i+1}. {p[1]} (ELO: {p[2]})\n"
    txt += f"\n🏆 <b>Победитель:</b> {'CT' if ct_won else 'T'}\n📈 ELO обновлён\n📸 Скриншот прилагается"
    try:
        await bot.send_photo(CHANNEL_ID, photo=photo, caption=txt, parse_mode="HTML")
        await cb.message.delete()
        await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption="✅ Результаты опубликованы!")
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
    await state.clear()

# ---------- ПРОФИЛЬ ----------
@dp.callback_query(lambda c: c.data == "profile")
async def profile(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    conn = sqlite3.connect(DB_PATH)
    u = conn.execute("SELECT nickname, role, elo, rank, matches_played, wins, losses, draws, winrate, kd_ratio, total_kills, total_deaths, headshots, mvps, registration_date, last_match_date, premium_expiry FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not u: await cb.answer("Профиль не найден", show_alert=True); return
    nick, role, elo, rank, m, w, l, d, wr, kd, kills, deaths, hs, mvp, reg, last, prem_exp = u
    rank_data = get_rank(elo)
    prog = ((elo - rank_data['min_elo']) / (rank_data['max_elo'] - rank_data['min_elo']) * 100) if rank_data['max_elo']<9999 else 100
    premium_status = "Не активен"
    if prem_exp:
        try:
            exp_date = datetime.fromisoformat(prem_exp)
            if exp_date > datetime.now(): premium_status = f"⭐ Активен до {exp_date.strftime('%d.%m.%Y')}"
            else: premium_status = "Истёк"
        except: premium_status = "Ошибка даты"
    txt = (f"👤 **ПРОФИЛЬ**\n{'='*30}\n\n"
           f"🎮 Ник: **{nick}**\n🎭 Роль: **{ROLE_NAMES.get(role, 'Игрок')}**\n"
           f"💎 Premium: {premium_status}\n"
           f"🏅 Ранг: {rank}\n📊 ELO: {elo}\n\n"
           f"📈 Статистика:\n🎯 Матчей: {m}\n✅ Побед: {w} | ❌ Поражений: {l} | 🤝 Ничьих: {d}\n"
           f"📊 Winrate: {wr}%\n⚔️ K/D: {kd}\n💀 Убийств: {kills} | ☠️ Смертей: {deaths}\n"
           f"🎯 Хедшотов: {hs} | ⭐ MVP: {mvp}\n\n"
           f"📅 Регистрация: {reg[:10] if reg else '—'}\n🕐 Последний матч: {last[:10] if last else '—'}\n\n"
           f"Прогресс уровня:\n[{'█'*int(prog/10)}{'░'*(10-int(prog/10))}] {prog:.1f}%")
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=txt, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_main")]
        ]))

# ---------- РЕЙТИНГ ----------
@dp.callback_query(lambda c: c.data == "leaderboard")
async def leaderboard(cb: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    top = conn.execute("SELECT nickname, elo, rank, wins, losses, winrate, kd_ratio, role, premium_expiry FROM users WHERE is_banned=0 ORDER BY elo DESC LIMIT 15").fetchall()
    conn.close()
    txt = "🏆 **ТОП-15**\n" + "="*30 + "\n\n"
    medals = ["🥇","🥈","🥉"] + ["👤"]*12
    for i,p in enumerate(top):
        role_emoji = {"director":"⚡","head_admin":"👑","admin":"🛡"}.get(p[7],"")
        if p[8] and is_premium_active(p[0]): role_emoji = "⭐"
        txt += f"{medals[i]} **#{i+1}** {role_emoji} {p[0]}\n   🏅 {p[2]} | ELO: {p[1]} | W/L: {p[3]}/{p[4]} | WR: {p[5]}% | K/D: {p[6]}\n\n"
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, LEADERBOARD_IMAGE, caption=txt, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="leaderboard")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_main")]
        ]))

# ---------- СТАТИСТИКА ----------
@dp.callback_query(lambda c: c.data == "stats")
async def stats(cb: types.CallbackQuery):
    await cb.answer("📊 Статистика пока в профиле", show_alert=True)

# ---------- ПРАВИЛА ----------
@dp.callback_query(lambda c: c.data == "rules")
async def rules(cb: types.CallbackQuery):
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE,
        caption="📜 Правила:\n1. Честная игра\n2. Уважение\n3. Обязательно играть\n4. Бан за нарушения",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ознакомлен", callback_data="back_to_main")]
        ]))

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.callback_query(lambda c: c.data == "admin_panel")
async def admin_panel(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): await cb.answer("❌ Нет доступа", show_alert=True); return
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption="⚙️ Админ-панель", reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("SELECT nickname, role, elo, is_banned FROM users LIMIT 20").fetchall()
    conn.close()
    txt = "👥 Пользователи:\n" + "\n".join(f"{u[0]} | {ROLE_NAMES.get(u[1],'?')} | ELO: {u[2]} | {'🚫 Бан' if u[3] else '✅'}" for u in users)
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=txt, reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_bans")
async def admin_bans(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect(DB_PATH)
    bans = conn.execute("SELECT nickname, ban_reason FROM users WHERE is_banned=1").fetchall()
    conn.close()
    txt = "🚫 Бан-лист:\n" + ("\n".join(f"{b[0]}: {b[1]}" for b in bans) if bans else "Пусто")
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=txt, reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_assign")
async def admin_assign(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username для назначения админом:")
    await state.set_state(AdminFSM.assign)

@dp.message(AdminFSM.assign)
async def assign_admin(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    user = c.execute("SELECT user_id, nickname, role FROM users WHERE user_id=? OR username=?", (int(target) if target.isdigit() else 0, target)).fetchone()
    if not user: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    if user[2] == UserRole.DIRECTOR: await msg.answer("❌ Нельзя изменить роль руководителя"); conn.close(); await state.clear(); return
    c.execute("UPDATE users SET role=? WHERE user_id=?", (UserRole.ADMIN, user[0]))
    conn.commit(); conn.close()
    await msg.answer(f"✅ {user[1]} теперь админ")
    await bot.send_message(user[0], "🎉 Вы назначены администратором!")
    await state.clear()

# ---------- БАН ИГРОКА ----------
@dp.callback_query(lambda c: c.data == "ban_leaver")
async def ban_leaver_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username игрока:")
    await state.set_state(BanFSM.waiting_user)

@dp.message(BanFSM.waiting_user)
async def ban_leaver_user(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    user = c.execute("SELECT user_id, nickname, role FROM users WHERE user_id=? OR username=?", (int(target) if target.isdigit() else 0, target)).fetchone()
    if not user: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    if user[2] in [UserRole.ADMIN, UserRole.HEAD_ADMIN, UserRole.DIRECTOR]: await msg.answer("❌ Нельзя забанить админа"); conn.close(); await state.clear(); return
    conn.close()
    await state.update_data(ban_user_id=user[0], ban_nick=user[1])
    await msg.answer(f"📝 Введите причину бана для {user[1]}:")
    await state.set_state(BanFSM.waiting_reason)

@dp.message(BanFSM.waiting_reason)
async def ban_leaver_reason(msg: types.Message, state: FSMContext):
    reason = msg.text.strip()
    if len(reason)<3 or len(reason)>200: await msg.answer("❌ От 3 до 200 символов"); return
    await state.update_data(ban_reason=reason)
    data = await state.get_data()
    await msg.answer(f"🔨 Выберите срок бана для {data['ban_nick']}:\n📝 Причина: {reason}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏱ 10 минут", callback_data="ban_dur_10m")],
            [InlineKeyboardButton(text="🕐 1 час", callback_data="ban_dur_1h")],
            [InlineKeyboardButton(text="📅 1 день", callback_data="ban_dur_1d")],
            [InlineKeyboardButton(text="📆 7 дней", callback_data="ban_dur_7d")],
            [InlineKeyboardButton(text="🗓 1 месяц", callback_data="ban_dur_30d")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")]
        ]))
    await state.set_state(BanFSM.waiting_duration)

@dp.callback_query(lambda c: c.data.startswith("ban_dur_"), BanFSM.waiting_duration)
async def ban_leaver_duration(cb: types.CallbackQuery, state: FSMContext):
    dur = cb.data.split("_")[2]
    data = await state.get_data()
    user_id, nick, reason = data['ban_user_id'], data['ban_nick'], data['ban_reason']
    admin_nick = cb.from_user.full_name
    durations = {"10m":(10,"10 минут"),"1h":(60,"1 час"),"1d":(1440,"1 день"),"7d":(10080,"7 дней"),"30d":(43200,"1 месяц")}
    minutes, dur_text = durations[dur]
    ban_until = ban_player(user_id, minutes, reason)
    try:
        await bot.send_message(CHANNEL_ID,
            f"🔨 <b>БЛОКИРОВКА</b>\n━━━━━━━━━━━━━━━━━━━━━━\n👤 Игрок: {escape_html(nick)}\n👮 Админ: {escape_html(admin_nick)}\n⏱ Срок: {dur_text}\n📅 Разблокировка: {datetime.fromisoformat(ban_until).strftime('%d.%m.%Y в %H:%M')}\n📝 Причина: {escape_html(reason)}",
            parse_mode="HTML")
    except: pass
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE,
        caption=f"🔨 Игрок {nick} заблокирован на {dur_text}\n📝 {reason}",
        reply_markup=admin_kb())
    try: await bot.send_message(user_id, f"⛔ Вы заблокированы на {dur_text}\n📝 {reason}\n📅 Разблокировка: {datetime.fromisoformat(ban_until).strftime('%d.%m.%Y %H:%M')}")
    except: pass
    await state.clear()

# ---------- РАЗБАН ----------
@dp.callback_query(lambda c: c.data == "unban_player")
async def unban_player_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    banned = c.execute("SELECT user_id, nickname FROM users WHERE is_banned=1").fetchall(); conn.close()
    if not banned: await cb.message.answer("✅ Нет заблокированных"); return
    kb = [[InlineKeyboardButton(text=u[1], callback_data=f"unban_{u[0]}")] for u in banned[:10]]
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")])
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption="✅ Выберите игрока для разбана:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(lambda c: c.data.startswith("unban_"))
async def unban_player_confirm(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    user_id = int(cb.data.split("_")[1])
    unban_player(user_id)
    conn = sqlite3.connect(DB_PATH); nick = conn.execute("SELECT nickname FROM users WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=f"✅ {nick[0] if nick else user_id} разблокирован!", reply_markup=admin_kb())
    try: await bot.send_message(user_id, "✅ Блокировка снята!")
    except: pass

# ---------- ЗАМЕНА ИГРОКА ----------
@dp.callback_query(lambda c: c.data == "replace_player")
async def replace_player_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    lobbies = c.execute("SELECT l.lobby_id, l.map_name FROM lobbies l JOIN match_teams mt ON l.lobby_id=mt.lobby_id WHERE l.status='closed' GROUP BY l.lobby_id ORDER BY l.created_at DESC LIMIT 10").fetchall(); conn.close()
    if not lobbies: await cb.message.answer("❌ Нет лобби с командами"); return
    kb = [[InlineKeyboardButton(text=f"Лобби #{l[0]} - {MAPS.get(l[1],'Карта')}", callback_data=f"repl_lobby_{l[0]}")] for l in lobbies]
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")])
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption="🔄 Выберите лобби:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(ReplacePlayerFSM.waiting_lobby)

@dp.callback_query(lambda c: c.data.startswith("repl_lobby_"), ReplacePlayerFSM.waiting_lobby)
async def replace_player_select_lobby(cb: types.CallbackQuery, state: FSMContext):
    lobby_id = int(cb.data.split("_")[2])
    ct_players, t_players, ct_team_id, t_team_id = get_lobby_players_list(lobby_id)
    if not ct_players: await cb.answer("❌ Команды не найдены", show_alert=True); await state.clear(); return
    await state.update_data(lobby_id=lobby_id, ct_team_id=ct_team_id, t_team_id=t_team_id)
    kb = []
    for p in ct_players: kb.append([InlineKeyboardButton(text=f"🔵 {p[1]}", callback_data=f"repl_old_{p[0]}")])
    for p in t_players: kb.append([InlineKeyboardButton(text=f"🔴 {p[1]}", callback_data=f"repl_old_{p[0]}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")])
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=f"🔄 Выберите игрока для замены в лобби #{lobby_id}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(ReplacePlayerFSM.waiting_old_player)

@dp.callback_query(lambda c: c.data.startswith("repl_old_"), ReplacePlayerFSM.waiting_old_player)
async def replace_player_select_old(cb: types.CallbackQuery, state: FSMContext):
    old_player_id = int(cb.data.split("_")[2])
    conn = sqlite3.connect(DB_PATH); old_nick = conn.execute("SELECT nickname FROM users WHERE user_id=?", (old_player_id,)).fetchone(); conn.close()
    await state.update_data(old_player_id=old_player_id, old_nick=old_nick[0] if old_nick else "Неизвестно")
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=f"🔄 Замена {old_nick[0] if old_nick else 'игрока'}\nВведите Telegram ID или @username нового игрока:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel")]]))
    await state.set_state(ReplacePlayerFSM.waiting_new_player)

@dp.message(ReplacePlayerFSM.waiting_new_player)
async def replace_player_select_new(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    new_player = c.execute("SELECT user_id, nickname, elo FROM users WHERE user_id=? OR username=?", (int(target) if target.isdigit() else 0, target)).fetchone()
    if not new_player: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    is_banned, ban_until, _ = is_player_banned(new_player[0])
    if is_banned: await msg.answer(f"❌ Заблокирован до {ban_until.strftime('%d.%m.%Y %H:%M')}"); conn.close(); await state.clear(); return
    data = await state.get_data()
    if c.execute("SELECT 1 FROM lobby_players WHERE lobby_id=? AND user_id=?", (data['lobby_id'], new_player[0])).fetchone():
        await msg.answer("❌ Уже в этом лобби"); conn.close(); await state.clear(); return
    conn.close()
    await state.update_data(new_player_id=new_player[0], new_nick=new_player[1], new_elo=new_player[2])
    data = await state.get_data()
    await msg.answer_photo(MAIN_MENU_IMAGE,
        caption=f"🔄 Подтвердите замену:\n❌ {data['old_nick']}\n✅ {data['new_nick']} (ELO: {data['new_elo']})\nЛобби #{data['lobby_id']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data="repl_confirm"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]))
    await state.set_state(ReplacePlayerFSM.confirm_replace)

@dp.callback_query(lambda c: c.data == "repl_confirm", ReplacePlayerFSM.confirm_replace)
async def replace_player_confirm(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lobby_id, old_player_id, new_player_id = data['lobby_id'], data['old_player_id'], data['new_player_id']
    old_nick, new_nick, new_elo = data['old_nick'], data['new_nick'], data['new_elo']
    admin_nick = cb.from_user.full_name
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    old_team = c.execute("SELECT team_id FROM team_players WHERE user_id=? AND team_id IN (SELECT team_id FROM match_teams WHERE lobby_id=?)", (old_player_id, lobby_id)).fetchone()
    if not old_team: await cb.answer("❌ Игрок не найден", show_alert=True); conn.close(); await state.clear(); return
    c.execute("UPDATE team_players SET user_id=?, nickname=? WHERE team_id=? AND user_id=?", (new_player_id, new_nick, old_team[0], old_player_id))
    c.execute("UPDATE lobby_players SET user_id=?, nickname=? WHERE lobby_id=? AND user_id=?", (new_player_id, new_nick, lobby_id, old_player_id))
    conn.commit()
    side = c.execute("SELECT team_side FROM match_teams WHERE team_id=?", (old_team[0],)).fetchone(); conn.close()
    side_text = side[0] if side else "?"
    side_emoji = "🔵" if side_text == "CT" else "🔴"
    try:
        await bot.send_message(CHANNEL_ID,
            f"🔄 <b>ЗАМЕНА ИГРОКА</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🎯 Лобби #{lobby_id}\n👮 Админ: {escape_html(admin_nick)}\n❌ Заменён: {escape_html(old_nick)}\n✅ Новый: {escape_html(new_nick)} (ELO: {new_elo})\n{side_emoji} Команда: {side_text}",
            parse_mode="HTML")
    except: pass
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=f"✅ Замена выполнена!\n{old_nick} → {new_nick}\n{side_emoji} {side_text}", reply_markup=admin_kb())
    try: await bot.send_message(old_player_id, f"🔄 Вас заменили в лобби #{lobby_id} на {new_nick}.")
    except: pass
    try: await bot.send_message(new_player_id, f"🔄 Вы добавлены в лобби #{lobby_id}!\n{side_emoji} Команда: {side_text}")
    except: pass
    await state.clear()

# ---------- PREMIUM ----------
@dp.callback_query(lambda c: c.data == "premium_give")
async def premium_give_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username:")
    await state.set_state(AdminFSM.premium_user)

@dp.message(AdminFSM.premium_user)
async def premium_give_user(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    user = c.execute("SELECT user_id, nickname FROM users WHERE user_id=? OR username=?", (int(target) if target.isdigit() else 0, target)).fetchone()
    if not user: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    conn.close()
    await state.update_data(premium_user_id=user[0], premium_nick=user[1])
    await msg.answer(f"Срок Premium для {user[1]}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц", callback_data="prem_dur_1m")],
        [InlineKeyboardButton(text="1 год", callback_data="prem_dur_1y")],
        [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
    ]))
    await state.set_state(AdminFSM.premium_duration)

@dp.callback_query(lambda c: c.data.startswith("prem_dur_"), AdminFSM.premium_duration)
async def premium_give_duration(cb: types.CallbackQuery, state: FSMContext):
    dur = cb.data.split("_")[2]
    data = await state.get_data()
    user_id, nick = data['premium_user_id'], data['premium_nick']
    expiry = (datetime.now() + timedelta(days=30 if dur=="1m" else 365)).isoformat()
    dur_text = "1 месяц" if dur=="1m" else "1 год"
    conn = sqlite3.connect(DB_PATH); conn.execute("UPDATE users SET premium_expiry=? WHERE user_id=?", (expiry, user_id)); conn.commit(); conn.close()
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=f"✅ Premium выдан {nick} на {dur_text}\nДо {datetime.fromisoformat(expiry).strftime('%d.%m.%Y')}", reply_markup=admin_kb())
    try: await bot.send_message(user_id, f"🎉 Premium на {dur_text} до {datetime.fromisoformat(expiry).strftime('%d.%m.%Y')}")
    except: pass
    await state.clear()

@dp.callback_query(lambda c: c.data == "premium_revoke")
async def premium_revoke_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username:")
    await state.set_state(PremiumRevoke.user)

@dp.message(PremiumRevoke.user)
async def premium_revoke_user(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    user = c.execute("SELECT user_id, nickname FROM users WHERE user_id=? OR username=?", (int(target) if target.isdigit() else 0, target)).fetchone()
    if not user: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    c.execute("UPDATE users SET premium_expiry=NULL WHERE user_id=?", (user[0],)); conn.commit(); conn.close()
    await msg.answer_photo(MAIN_MENU_IMAGE, caption=f"✅ Premium у {user[1]} отозван", reply_markup=admin_kb())
    try: await bot.send_message(user[0], "ℹ️ Premium отозван")
    except: pass
    await state.clear()

# ---------- ВОЗВРАТ В МЕНЮ ----------
@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(cb: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    u = conn.execute("SELECT role, nickname, elo, rank FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone(); conn.close()
    role = u[0] if u else UserRole.PLAYER
    cap = f"🎮 **{PROJECT_NAME}**\n👤 {u[1]}\n🏅 {u[3]} | ELO: {u[2]}" if u else f"🎮 **{PROJECT_NAME}**"
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=cap, parse_mode="Markdown", reply_markup=main_menu(cb.from_user.id))

# ---------- ОЧИСТКА ----------
def clean_expired():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE users SET premium_expiry=NULL WHERE premium_expiry IS NOT NULL AND premium_expiry < ?", (now,))
    c.execute("UPDATE users SET is_banned=0, ban_reason=NULL, last_match_date=NULL WHERE is_banned=1 AND last_match_date < ?", (now,))
    conn.commit(); conn.close()

# ---------- ЗАПУСК ----------
async def main():
    init_db()
    one_time_elo_reset()
    clean_expired()
    print(f"🔥 {PROJECT_NAME} запущен! База: {DB_PATH}")
    while True:
        try: await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            print("Перезапуск через 10 сек...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
