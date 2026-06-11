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

# Изображения (замените ссылки на свои)
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    # Добавляем premium_expiry, если его ещё нет
    try:
        c.execute("ALTER TABLE users ADD COLUMN premium_expiry TEXT")
    except sqlite3.OperationalError:
        pass  # столбец уже есть – ничего не делаем

    # Остальные таблицы
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
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    conn.close()

def one_time_elo_reset():
    conn = sqlite3.connect('404hp_faceit.db')
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

def get_lobby_players_text(lobby_id):
    conn = sqlite3.connect('404hp_faceit.db')
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

async def update_lobby_post(lobby_id):
    conn = sqlite3.connect('404hp_faceit.db')
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
        f"🔑 <b>Код:</b> <code>{lobby[2]}</code>\n\n"
        f"{players}\n"
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    c.execute("SELECT role, premium_expiry FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    if not user: return False
    role, expiry = user
    if role == UserRole.DIRECTOR:
        return True
    if permission == "create_lobby":
        if role in [UserRole.PREMIUM, UserRole.ADMIN, UserRole.HEAD_ADMIN]:
            return True
        if expiry:
            try:
                if datetime.fromisoformat(expiry) > datetime.now():
                    return True
            except:
                pass
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    photo = State(); score = State()

class AdminFSM(StatesGroup):
    assign = State()
    premium_user = State()
    premium_duration = State()

class PremiumRevoke(StatesGroup):
    user = State()

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
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (msg.from_user.id,))
    u = c.fetchone()
    conn.close()
    if not u:
        await msg.answer_photo(REGISTRATION_IMAGE, caption="Введите игровой никнейм:")
        await state.set_state(Reg.nick)
    else:
        if len(u) > 21 and u[21]:
            await msg.answer_photo(MAIN_MENU_IMAGE, caption="⛔ Забанен")
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

# ---------- РЕГИСТРАЦИЯ (используется REGISTRATION_IMAGE) ----------
@dp.message(Reg.nick)
async def reg_nick(msg: types.Message, state: FSMContext):
    nick = msg.text.strip()
    if len(nick)<3 or len(nick)>24 or not nick.replace('_','').replace('-','').isalnum():
        await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Некорректный ник"); return
    conn = sqlite3.connect('404hp_faceit.db')
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
        await msg.answer_photo(REGISTRATION_IMAGE, caption="❌ Не совпадают. Введите пароль заново:")
        await state.set_state(Reg.pw); return
    data = await state.get_data()
    nick, pw = data['nick'], data['pw']
    user_id = msg.from_user.id
    uname = msg.from_user.username or msg.from_user.full_name
    is_dir = (msg.from_user.username == HEAD_ADMIN_USERNAME)
    role = UserRole.DIRECTOR if is_dir else UserRole.PLAYER
    h, s = hash_password(pw)
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
    u = conn.execute("SELECT user_id, password_hash, salt, role FROM users WHERE nickname=?", (nick,)).fetchone()
    conn.close()
    if not u: await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Не найден"); return
    if verify_password(pw, u[2], u[1]):
        conn = sqlite3.connect('404hp_faceit.db')
        conn.execute("UPDATE users SET user_id=? WHERE nickname=?", (msg.from_user.id, nick))
        conn.commit(); conn.close()
        await msg.answer_photo(MAIN_MENU_IMAGE, caption=f"✅ Вход выполнен!\nРоль: {ROLE_NAMES[u[3]]}")
    else: await msg.answer_photo(MAIN_MENU_IMAGE, caption="❌ Неверный пароль")

# ---------- СОЗДАНИЕ ЛОББИ (используется LOBBY_CREATE_IMAGE) ----------
@dp.callback_query(lambda c: c.data == "create_lobby")
async def lobby_start(cb: types.CallbackQuery, state: FSMContext):
    if not has_permission(cb.from_user.id, "create_lobby"):
        await cb.answer("❌ Нет прав", show_alert=True); return
    kb = [[InlineKeyboardButton(text=v, callback_data=f"lobby_map_{k}")] for k,v in MAPS.items()]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")])
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, LOBBY_CREATE_IMAGE,
        caption="🗺 Выберите карту для лобби:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
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
        conn = sqlite3.connect('404hp_faceit.db')
        c = conn.cursor()
        teams = c.execute("SELECT team_id, team_side FROM match_teams WHERE lobby_id=?", (lid,)).fetchall()
        if len(teams)!=2: await msg.answer_photo(MAIN_MENU_IMAGE, caption="Лобби не найдено"); conn.close(); return
        ct_id = t_id = None
        for tid, side in teams:
            if side=='CT': ct_id = tid
            else: t_id = tid
        ct_pl = c.execute("SELECT tp.user_id, tp.nickname, u.elo FROM team_players tp JOIN users u ON tp.user_id=u.user_id WHERE tp.team_id=? ORDER BY tp.position", (ct_id,)).fetchall()
        t_pl = c.execute("SELECT tp.user_id, tp.nickname, u.elo FROM team_players tp JOIN users u ON tp.user_id=u.user_id WHERE tp.team_id=? ORDER BY tp.position", (t_id,)).fetchall()
        ct_won = ct > t
        for p in ct_pl: update_stats(p[0], ct_won)
        for p in t_pl: update_stats(p[0], not ct_won)
        map_name = c.execute("SELECT map_name FROM lobbies WHERE lobby_id=?", (lid,)).fetchone()
        map_name = map_name[0] if map_name else "Неизвестно"
        conn.commit(); conn.close()
        txt = (f"📊 <b>РЕЗУЛЬТАТ МАТЧА</b>\nЛобби #{lid}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
               f"🗺 {MAPS.get(map_name, map_name)}\n\n🔵 <b>CT:</b> {ct}\n")
        for i,p in enumerate(ct_pl): txt += f"{i+1}. {p[1]} (ELO: {p[2]})\n"
        txt += f"\n🔴 <b>T:</b> {t}\n"
        for i,p in enumerate(t_pl): txt += f"{i+1}. {p[1]} (ELO: {p[2]})\n"
        txt += f"\n🏆 Победитель: {'CT' if ct_won else 'T'}\n📸 Скриншот прилагается"
        await bot.send_photo(CHANNEL_ID, photo, caption=txt, parse_mode="HTML")
        await msg.answer_photo(MAIN_MENU_IMAGE, caption="✅ Результаты опубликованы!")
        await state.clear()
    except Exception as e:
        await msg.answer_photo(MAIN_MENU_IMAGE, caption=f"❌ Ошибка: {e}")

# ---------- ПРОФИЛЬ ----------
@dp.callback_query(lambda c: c.data == "profile")
async def profile(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    conn = sqlite3.connect('404hp_faceit.db')
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

# ---------- РЕЙТИНГ (используется LEADERBOARD_IMAGE) ----------
@dp.callback_query(lambda c: c.data == "leaderboard")
async def leaderboard(cb: types.CallbackQuery):
    conn = sqlite3.connect('404hp_faceit.db')
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

# ---------- СТАТИСТИКА (заглушка) ----------
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
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE,
        caption="⚙️ Админ-панель\nВыберите действие:", reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect('404hp_faceit.db')
    users = conn.execute("SELECT nickname, role, elo, is_banned FROM users LIMIT 20").fetchall()
    conn.close()
    txt = "👥 Пользователи:\n" + "\n".join(f"{u[0]} | {ROLE_NAMES.get(u[1],'?')} | ELO: {u[2]} | {'🚫 Бан' if u[3] else '✅'}" for u in users)
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=txt, reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_bans")
async def admin_bans(cb: types.CallbackQuery):
    if not await is_admin(cb.from_user.id): return
    conn = sqlite3.connect('404hp_faceit.db')
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
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    if target.isdigit():
        user = c.execute("SELECT user_id, nickname, role FROM users WHERE user_id=?", (int(target),)).fetchone()
    else:
        user = c.execute("SELECT user_id, nickname, role FROM users WHERE username=?", (target,)).fetchone()
    if not user: await msg.answer("❌ Не найден"); conn.close(); await state.clear(); return
    if user[2] == UserRole.DIRECTOR: await msg.answer("❌ Нельзя изменить роль руководителя"); conn.close(); await state.clear(); return
    c.execute("UPDATE users SET role=? WHERE user_id=?", (UserRole.ADMIN, user[0]))
    conn.commit(); conn.close()
    await msg.answer(f"✅ {user[1]} теперь админ")
    await bot.send_message(user[0], "🎉 Вы назначены администратором!")
    await state.clear()

# ---------- ВЫДАЧА PREMIUM ----------
@dp.callback_query(lambda c: c.data == "premium_give")
async def premium_give_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username пользователя, которому выдать Premium:")
    await state.set_state(AdminFSM.premium_user)

@dp.message(AdminFSM.premium_user)
async def premium_give_user(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    if target.isdigit():
        user = c.execute("SELECT user_id, nickname FROM users WHERE user_id=?", (int(target),)).fetchone()
    else:
        user = c.execute("SELECT user_id, nickname FROM users WHERE username=?", (target,)).fetchone()
    if not user:
        await msg.answer("❌ Пользователь не найден"); conn.close(); await state.clear(); return
    conn.close()
    await state.update_data(premium_user_id=user[0], premium_nick=user[1])
    await msg.answer(f"Выберите срок Premium для {user[1]}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 месяц", callback_data="prem_dur_1m")],
            [InlineKeyboardButton(text="1 год", callback_data="prem_dur_1y")],
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
        ]))
    await state.set_state(AdminFSM.premium_duration)

@dp.callback_query(lambda c: c.data.startswith("prem_dur_"), AdminFSM.premium_duration)
async def premium_give_duration(cb: types.CallbackQuery, state: FSMContext):
    dur = cb.data.split("_")[2]
    data = await state.get_data()
    user_id = data['premium_user_id']
    nick = data['premium_nick']
    if dur == "1m":
        expiry = (datetime.now() + timedelta(days=30)).isoformat()
        dur_text = "1 месяц"
    else:
        expiry = (datetime.now() + timedelta(days=365)).isoformat()
        dur_text = "1 год"
    conn = sqlite3.connect('404hp_faceit.db')
    conn.execute("UPDATE users SET premium_expiry=? WHERE user_id=?", (expiry, user_id))
    conn.commit()
    conn.close()
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE,
        caption=f"✅ Premium выдан пользователю {nick} на {dur_text}.\nДействует до {datetime.fromisoformat(expiry).strftime('%d.%m.%Y')}",
        reply_markup=admin_kb())
    try:
        await bot.send_message(user_id, f"🎉 Вам выдан Premium на {dur_text}! Действует до {datetime.fromisoformat(expiry).strftime('%d.%m.%Y')}")
    except: pass
    await state.clear()

# ---------- ЗАБРАТЬ PREMIUM ----------
@dp.callback_query(lambda c: c.data == "premium_revoke")
async def premium_revoke_start(cb: types.CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id): return
    await cb.message.answer("Введите Telegram ID или @username пользователя, у которого забрать Premium:")
    await state.set_state(PremiumRevoke.user)

@dp.message(PremiumRevoke.user)
async def premium_revoke_user(msg: types.Message, state: FSMContext):
    target = msg.text.strip().replace("@","")
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    if target.isdigit():
        user = c.execute("SELECT user_id, nickname FROM users WHERE user_id=?", (int(target),)).fetchone()
    else:
        user = c.execute("SELECT user_id, nickname FROM users WHERE username=?", (target,)).fetchone()
    if not user:
        await msg.answer("❌ Пользователь не найден"); conn.close(); await state.clear(); return
    c.execute("UPDATE users SET premium_expiry=NULL WHERE user_id=?", (user[0],))
    conn.commit(); conn.close()
    await msg.answer_photo(MAIN_MENU_IMAGE,
        caption=f"✅ Premium у пользователя {user[1]} отозван.",
        reply_markup=admin_kb())
    try:
        await bot.send_message(user[0], "ℹ️ Ваш Premium-статус был отозван администратором.")
    except: pass
    await state.clear()

# ---------- ВОЗВРАТ В МЕНЮ ----------
@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(cb: types.CallbackQuery):
    conn = sqlite3.connect('404hp_faceit.db')
    u = conn.execute("SELECT role, nickname, elo, rank FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone()
    conn.close()
    if u:
        role, nick, elo, rank = u
        cap = f"🎮 **{PROJECT_NAME}**\n👤 {nick}\n🏅 {rank} | ELO: {elo}\nВыберите действие:"
    else:
        role, cap = UserRole.PLAYER, f"🎮 **{PROJECT_NAME}**"
    await cb.message.delete()
    await bot.send_photo(cb.from_user.id, MAIN_MENU_IMAGE, caption=cap, parse_mode="Markdown", reply_markup=main_menu(cb.from_user.id))

# ---------- ОЧИСТКА ИСТЁКШИХ PREMIUM ----------
def clean_expired_premium():
    conn = sqlite3.connect('404hp_faceit.db')
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE users SET premium_expiry=NULL WHERE premium_expiry IS NOT NULL AND premium_expiry < ?", (now,))
    conn.commit()
    conn.close()

# ---------- ЗАПУСК ----------
async def main():
    init_db()
    one_time_elo_reset()
    clean_expired_premium()
    print(f"🔥 {PROJECT_NAME} запущен! (все ELO = 0)")
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            print("Перезапуск через 10 сек...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())