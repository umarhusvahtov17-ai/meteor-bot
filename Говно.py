import asyncio
import sqlite3
import glob
import random
import json
import os
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import InputReportReasonOther
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

API_ID = ТВОЙ_API_ID
API_HASH = "ТВОЙ_API_HASH"
ADMIN_ID = ТВОЙ_ADMIN_ID
LOG_CHANNEL_ID = ТВОЙ_LOG_CHANNEL_ID

MIRROR_TOKENS = [
    "ТОКЕН_ЗЕРКАЛА_1",
    "ТОКЕН_ЗЕРКАЛА_2",
    "ТОКЕН_ЗЕРКАЛА_3",
]

BOT_TOKEN = MIRROR_TOKENS[0]

active_clients = []
user_cooldown = {}
is_attack_running = False
current_attacker = None

conn = sqlite3.connect("meteor_bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        subscription_end TEXT,
        agreed_rules INTEGER DEFAULT 0
    )
""")
conn.commit()

cursor.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cursor.fetchall()]

if "total_attacks" not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN total_attacks INTEGER DEFAULT 0")
if "total_reports" not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN total_reports INTEGER DEFAULT 0")
if "last_mirror_time" not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN last_mirror_time TEXT")
conn.commit()

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_user(user_id, username, first_name):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, subscription_end, agreed_rules, total_attacks, total_reports, last_mirror_time) VALUES (?, ?, ?, NULL, 0, 0, 0, NULL)",
                   (user_id, username, first_name))
    conn.commit()

def update_stats(user_id, reports):
    cursor.execute("UPDATE users SET total_attacks = total_attacks + 1, total_reports = total_reports + ? WHERE user_id = ?", (reports, user_id))
    conn.commit()

def set_subscription(user_id, days):
    end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET subscription_end = ? WHERE user_id = ?", (end_date, user_id))
    conn.commit()

def remove_subscription(user_id):
    cursor.execute("UPDATE users SET subscription_end = NULL WHERE user_id = ?", (user_id,))
    conn.commit()

def get_subscription_end(user_id):
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    return None

def is_subscription_active(user_id):
    end = get_subscription_end(user_id)
    return end is not None and end > datetime.now()

def set_agreed_rules(user_id):
    cursor.execute("UPDATE users SET agreed_rules = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def has_agreed_rules(user_id):
    cursor.execute("SELECT agreed_rules FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == 1

def can_get_mirror(user_id):
    cursor.execute("SELECT last_mirror_time FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        last_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - last_time < timedelta(minutes=60):
            remain = 60 - int((datetime.now() - last_time).total_seconds() // 60)
            return False, remain
    return True, 0

def set_mirror_used(user_id):
    cursor.execute("UPDATE users SET last_mirror_time = ? WHERE user_id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()

COMPLAINT_TEXT = """Бот рекламирует и распространяет инструмент массового пробива персональных данных («Шерлок»): паспорта, СНИЛС, ИНН, номера телефонов, адреса, авто, соцсети, биометрия по фото. Нарушает ФЗ-152 и ст.137 УК РФ. Требую немедленной блокировки."""

rules_text = """
Правила использования Meteor

1. Разрешённые цели:
   • scalp.today
   • go.manticore.bot/newbot

2. Мы ручаемся за снос только этих ботов!

3. Лимиты:
   • После атаки 15 минут охлаждения
   • За раз отправляется 30 жалоб

Нажми "Принимаю" для продолжения
"""

async def load_telethon_sessions():
    global active_clients
    session_files = glob.glob("*.session")
    clients = []
    for session_file in session_files:
        name = session_file.replace(".session", "")
        client = TelegramClient(name, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"Сессия {name} не авторизована")
            continue
        clients.append(client)
        print(f"Загружена: {name}")
    active_clients = clients
    print(f"Всего сессий: {len(active_clients)}")

async def report_profile(client, username):
    try:
        entity = await client.get_entity(username)
        await client(ReportPeerRequest(
            peer=entity,
            reason=InputReportReasonOther(),
            message=COMPLAINT_TEXT
        ))
        return True
    except Exception as e:
        print(f"Ошибка: {e}")
        return False

async def perform_attack(target_username, user_id):
    global is_attack_running, current_attacker, user_cooldown
    is_attack_running = True
    current_attacker = user_id
    sent = 0
    total_reports = 30
    
    try:
        while sent < total_reports:
            shuffled_clients = active_clients.copy()
            random.shuffle(shuffled_clients)
            
            for client in shuffled_clients:
                if sent >= total_reports:
                    break
                if await report_profile(client, target_username):
                    sent += 1
                    print(f"Репорт {sent}/30 | @{target_username}")
                await asyncio.sleep(1.0)
    finally:
        is_attack_running = False
        current_attacker = None
        user_cooldown[user_id] = datetime.now() + timedelta(minutes=15)
        update_stats(user_id, sent)
    return sent

async def send_attack_log(user_id, username, target, sent):
    try:
        user = get_user(user_id)
        user_name = user[2] if user else str(user_id)
        user_tag = f"@{user[1]}" if user and user[1] else "нет юзернейма"
        total_attacks = user[5] if user else 0
        total_reports_all = user[6] if user else 0
        
        log_text = f"""
🎯 НОВАЯ АТАКА

👤 ЗАКАЗЧИК: {user_name}
🆔 ID: {user_id}
📱 ЮЗЕРНЕЙМ: {user_tag}

🤖 ЦЕЛЬ: @{target}

📊 ВСЕГО ЖАЛОБ: {sent}

⏰ ВРЕМЯ: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}

📈 СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ:
├ Всего атак: {total_attacks + 1}
└ Всего жалоб: {total_reports_all + sent}

⏳ СЛЕДУЮЩАЯ АТАКА: через 15 минут
"""
        await bot.send_message(LOG_CHANNEL_ID, log_text)
    except Exception as e:
        print(f"Ошибка лога: {e}")

def can_attack(user_id):
    if is_attack_running:
        return False, "Сейчас выполняется другая атака, подождите"
    
    last_attack = user_cooldown.get(user_id)
    if last_attack and last_attack > datetime.now():
        remain = int((last_attack - datetime.now()).total_seconds() // 60)
        remain_sec = int((last_attack - datetime.now()).total_seconds() % 60)
        return False, f"Охлаждение: {remain} мин {remain_sec} сек"
    
    return True, ""
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

class AttackStates(StatesGroup):
    waiting_for_target = State()

def main_menu_keyboard(is_admin=False):
    builder = InlineKeyboardBuilder()
    builder.button(text="Профиль", callback_data="profile")
    builder.button(text="Атака", callback_data="attack")
    builder.button(text="Зеркала", callback_data="get_mirror")
    if is_admin:
        builder.button(text="Админ", callback_data="admin")
    builder.adjust(2)
    return builder.as_markup()

def admin_panel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Выдать подписку", callback_data="admin_give")
    builder.button(text="Забрать подписку", callback_data="admin_remove")
    builder.button(text="Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def back_to_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Главное меню", callback_data="back_to_menu")
    return builder.as_markup()

def profile_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить подписку", url="https://t.me/TonkeeperlGram")
    builder.button(text="Правила", callback_data="show_rules")
    builder.button(text="Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def no_subscription_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить подписку", url="https://t.me/TonkeeperlGram")
    builder.button(text="Назад", callback_data="back_to_menu")
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    create_user(user.id, user.username or "", user.first_name or "")
    is_admin = (user.id == ADMIN_ID)
    
    await message.answer(
        f"Добро пожаловать в Meteor!\n\nПривет, {user.first_name}!\n\nБот для жалоб на ботов Manticore и Scalp\nОхлаждение 15 минут\nСтатистика в профиле\n\nЕсть кнопка Зеркала - получишь рандомного бота-клона!",
        reply_markup=main_menu_keyboard(is_admin)
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    user = callback.from_user
    is_admin = (user.id == ADMIN_ID)
    await callback.message.edit_text(
        "Главное меню",
        reply_markup=main_menu_keyboard(is_admin)
    )
    await callback.answer()

@dp.callback_query(F.data == "show_rules")
async def show_rules(callback: types.CallbackQuery):
    await callback.message.edit_text(
        rules_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Принимаю", callback_data="agree_rules")],
            [InlineKeyboardButton(text="Назад", callback_data="back_to_menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    sub_end = get_subscription_end(user_id)
    if sub_end and sub_end > datetime.now():
        days_left = (sub_end - datetime.now()).days
        sub_status = f"Активна до {sub_end.strftime('%d.%m.%Y')} (осталось {days_left} дн.)"
    else:
        sub_status = "Нет подписки"
        if sub_end and sub_end <= datetime.now():
            remove_subscription(user_id)
    
    can, _ = can_attack(user_id)
    cd_status = "15 минут" if not can else "Готов"
    
    can_get, remain = can_get_mirror(user_id)
    mirror_status = f"Готов" if can_get else f"Через {remain} мин"
    
    text = f"""
📱 Профиль

Имя: {user[2]}
ID: {user_id}
Username: @{user[1] if user[1] else "нет"}

💳 Подписка: {sub_status}

📊 Статистика:
├ Атак: {user[5] if user[5] else 0}
└ Жалоб: {user[6] if user[6] else 0}

⏳ Охлаждение атаки: {cd_status}
🪞 Зеркала: {mirror_status} (кд 60 мин)
"""
    await callback.message.edit_text(text, reply_markup=profile_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "get_mirror")
async def get_mirror(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    can_get, remain = can_get_mirror(user_id)
    if not can_get:
        await callback.answer(f"Кд 60 минут! Осталось {remain} мин", show_alert=True)
        return
    
    current_token = BOT_TOKEN
    available_mirrors = [t for t in MIRROR_TOKENS if t != current_token]
    
    if not available_mirrors:
        await callback.answer("Нет доступных зеркал", show_alert=True)
        return
    
    random_mirror = random.choice(available_mirrors)
    
    bot_username = None
    mirror_link = None
    
    try:
        temp_bot = Bot(token=random_mirror)
        me = await temp_bot.get_me()
        bot_username = me.username
        mirror_link = f"https://t.me/{bot_username}"
        await temp_bot.close()
    except Exception as e:
        print(f"Ошибка получения username: {e}")
        bot_id = random_mirror.split(":")[0]
        mirror_link = f"https://t.me/bot?start={bot_id}"
        bot_username = f"зеркало_{bot_id[-4:]}"
    
    set_mirror_used(user_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ПЕРЕЙТИ В ЗЕРКАЛО", url=mirror_link)],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(
        f"🪞 ВАШЕ ЗЕРКАЛО\n\n"
        f"🎲 Выпало: @{bot_username}\n"
        f"⏳ Следующее зеркало через 60 минут\n\n"
        f"Нажми на кнопку ниже, чтобы перейти!",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "attack")
async def start_attack(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not is_subscription_active(user_id):
        await callback.message.edit_text("Нет активной подписки", reply_markup=no_subscription_keyboard())
        await callback.answer()
        return
    
    if not has_agreed_rules(user_id):
        await callback.message.edit_text(
            rules_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Принимаю", callback_data="agree_rules")],
                [InlineKeyboardButton(text="Назад", callback_data="back_to_menu")]
            ])
        )
        await callback.answer()
        return
    
    can, msg = can_attack(user_id)
    if not can:
        await callback.answer(msg, show_alert=True)
        return
    
    await callback.message.edit_text(
        "Введите цель\n\nUsername бота без @\nПример: info_manticore_bot",
        reply_markup=back_to_menu_keyboard()
    )
    await state.set_state(AttackStates.waiting_for_target)
    await callback.answer()

@dp.callback_query(F.data == "agree_rules")
async def agree_rules(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    set_agreed_rules(user_id)
    is_admin = (callback.from_user.id == ADMIN_ID)
    await callback.message.edit_text(
        "Правила приняты\n\nНажми Атака",
        reply_markup=main_menu_keyboard(is_admin)
    )
    await callback.answer()

@dp.message(AttackStates.waiting_for_target)
async def get_target(message: Message, state: FSMContext):
    target = message.text.strip()
    if not target:
        await message.answer("Введите username")
        return
    if target.startswith("@"):
        target = target[1:]
    
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    if not is_subscription_active(user_id):
        await message.answer("Нет подписки")
        await state.clear()
        return
    
    if not has_agreed_rules(user_id):
        await message.answer("Не приняты правила")
        await state.clear()
        return
    
    can, msg = can_attack(user_id)
    if not can:
        await message.answer(msg)
        await state.clear()
        return
    
    status_msg = await message.answer(f"🚀 АТАКА НА @{target}\n⏳ ПОДОЖДИТЕ...")
    
    sent = await perform_attack(target, user_id)
    
    await status_msg.delete()
    await message.answer(f"✅ АТАКА ЗАВЕРШЕНА!\n\n🎯 ЦЕЛЬ: @{target}\n📊 ВСЕГО ЖАЛОБ: {sent}\n⏳ СЛЕДУЮЩАЯ АТАКА ЧЕРЕЗ 15 МИНУТ")
    await send_attack_log(user_id, user_name, target, sent)
    await state.clear()

@dp.callback_query(F.data == "admin")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("Админ панель", reply_markup=admin_panel_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def give_subscription_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=back_to_menu_keyboard())
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="give")
    await callback.answer()

@dp.callback_query(F.data == "admin_remove")
async def remove_subscription_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=back_to_menu_keyboard())
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="remove")
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("Некорректный ID")
        return
    
    data = await state.get_data()
    action = data.get("action")
    
    if action == "give":
        await state.update_data(user_id=user_id)
        await message.answer(f"Пользователь {user_id}\nВведите количество дней:")
        await state.set_state(AdminStates.waiting_for_days)
    elif action == "remove":
        remove_subscription(user_id)
        cursor.execute("UPDATE users SET agreed_rules = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.answer(f"Подписка удалена у {user_id}", reply_markup=back_to_menu_keyboard())
        await state.clear()
    else:
        await state.clear()
        await message.answer("Ошибка")

@dp.message(AdminStates.waiting_for_days)
async def process_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите число больше 0")
        return
    
    data = await state.get_data()
    user_id = data.get("user_id")
    
    set_subscription(user_id, days)
    end_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y %H:%M")
    
    await message.answer(f"Подписка выдана!\n\nПользователь: {user_id}\nДней: {days}\nДо: {end_date}", reply_markup=back_to_menu_keyboard())
    await state.clear()
    
    try:
        await bot.send_message(user_id, f"Вам выдана подписка!\n\n{days} дней\nДо {end_date}\n\nНажми Атака")
    except:
        pass

async def main():
    await load_telethon_sessions()
    print("=" * 50)
    print("Бот Meteor запущен")
    print(f"Админ: {ADMIN_ID}")
    print(f"Сессий: {len(active_clients)}")
    print(f"Лог канал: {LOG_CHANNEL_ID}")
    print(f"Зеркал загружено: {len(MIRROR_TOKENS)}")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())