import logging
import math
import re
import datetime
import csv
import io
import os
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import pytz

# Для фонового планирования напоминаний
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import (
    init_db, log_action, get_user_stats, get_daily_report, get_all_records,
    set_schedule, get_all_schedules, get_schedule
)

# Загрузка переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher(bot)

# Получаем ID администратора и устанавливаем часовой пояс для Ташкента
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))
tz = pytz.timezone('Asia/Tashkent')

# Разрешённая точка (по умолчанию)
ALLOWED_LAT = 41.2995      # начальная широта (центр Ташкента)
ALLOWED_LON = 69.2401      # начальная долгота
ALLOWED_RADIUS = 1000      # радиус проверки в метрах

# Флаг для ожидания установки новой точки проверки от админа
pending_allowed_location = False

# Глобальный словарь для хранения ожидаемых действий пользователя (приход/уход)
pending_actions = {}

def calculate_distance(lat: float, lon: float, lat2: float, lon2: float) -> float:
    """Вычисляет расстояние между двумя координатами (в метрах) по формуле гаверсина."""
    R = 6371000  # Радиус Земли в метрах
    phi1 = math.radians(lat)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat)
    delta_lambda = math.radians(lon2 - lon)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Главное меню для пользователей
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_menu.add(KeyboardButton('✅ Я пришёл'), KeyboardButton('🏁 Я ушёл'))
main_menu.add(KeyboardButton('📊 Моя статистика'))
main_menu.add(KeyboardButton('🕒 Установить график'))

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\nВыбери действие:",
        reply_markup=main_menu
    )

# === Новый функционал: установка точки проверки администратором ===
@dp.message_handler(commands=['set_allowed_location'])
async def set_allowed_location_command(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    global pending_allowed_location
    pending_allowed_location = True
    location_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    location_keyboard.add(KeyboardButton("Поделиться локацией", request_location=True))
    await message.answer("Отправьте, пожалуйста, локацию, которая станет новой точкой проверки (ALLOWED_LAT, ALLOWED_LON).",
                         reply_markup=location_keyboard)

@dp.message_handler(lambda message: message.from_user.id == ADMIN_CHAT_ID and pending_allowed_location,
                    content_types=types.ContentType.LOCATION)
async def admin_location_handler(message: types.Message):
    global ALLOWED_LAT, ALLOWED_LON, pending_allowed_location
    ALLOWED_LAT = message.location.latitude
    ALLOWED_LON = message.location.longitude
    pending_allowed_location = False
    await message.answer(f"Новая точка проверки установлена:\nШирота: {ALLOWED_LAT}\nДолгота: {ALLOWED_LON}",
                         reply_markup=ReplyKeyboardRemove())

@dp.message_handler(lambda message: message.from_user.id == ADMIN_CHAT_ID and pending_allowed_location and 
                    ("maps.apple.com" in message.text or "goo.gl/maps" in message.text))
async def admin_maps_link_handler(message: types.Message):
    global ALLOWED_LAT, ALLOWED_LON, pending_allowed_location
    coords = re.findall(r"(-?\d+\.\d+),\s*(-?\d+\.\d+)", message.text)
    if not coords:
        await message.answer("Не удалось извлечь координаты из ссылки. Попробуйте отправить локацию через кнопку.")
        return
    ALLOWED_LAT, ALLOWED_LON = map(float, coords[0])
    pending_allowed_location = False
    await message.answer(f"Новая точка проверки установлена:\nШирота: {ALLOWED_LAT}\nДолгота: {ALLOWED_LON}",
                         reply_markup=ReplyKeyboardRemove())

# === Обработка пользовательских действий (приход/уход) с проверкой локации ===
@dp.message_handler(lambda message: message.text == '✅ Я пришёл')
async def ask_location_arrived(message: types.Message):
    pending_actions[message.from_user.id] = 'arrived'
    location_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    location_keyboard.add(KeyboardButton("Поделиться локацией", request_location=True))
    await message.answer("Пожалуйста, отправьте вашу локацию для подтверждения прихода.",
                         reply_markup=location_keyboard)

@dp.message_handler(lambda message: message.text == '🏁 Я ушёл')
async def ask_location_left(message: types.Message):
    pending_actions[message.from_user.id] = 'left'
    location_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    location_keyboard.add(KeyboardButton("Поделиться локацией", request_location=True))
    await message.answer("Пожалуйста, отправьте вашу локацию для подтверждения ухода.",
                         reply_markup=location_keyboard)

async def process_location_async(user_id: int, lat: float, lon: float,
                                 full_name: str, username: str, action: str):
    """Асинхронно проверяет расстояние от отправленной локации до разрешённой точки и фиксирует действие."""
    distance = calculate_distance(lat, lon, ALLOWED_LAT, ALLOWED_LON)
    if distance > ALLOWED_RADIUS:
        return (False, f"Ваше местоположение находится слишком далеко от разрешенной зоны (расстояние: {distance:.1f} м). Попробуйте отправить корректную локацию.")
    now = datetime.datetime.now(tz)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, log_action, user_id, username, full_name, action)
    except Exception as e:
        logging.error(f"Error logging {action}: {e}")
    if action == 'arrived':
        response = '✅ Ваш приход подтвержден!'
        admin_message = f"📌 **Приход**:\nПользователь: {full_name}"
    else:
        response = '🏁 Ваш уход подтвержден!'
        admin_message = f"📌 **Уход**:\nПользователь: {full_name}"
    if username:
        admin_message += f" (@{username})"
    admin_message += f"\nID: {user_id}\nВремя: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    asyncio.create_task(bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown'))
    asyncio.create_task(bot.send_location(ADMIN_CHAT_ID, latitude=lat, longitude=lon))
    return (True, response + f"\nРасстояние до точки проверки: {distance:.1f} м.")

@dp.message_handler(content_types=types.ContentType.LOCATION)
async def location_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_actions:
        return  # Если нет ожидаемого действия – не обрабатываем
    action = pending_actions.pop(user_id)
    full_name = message.from_user.first_name + ((" " + message.from_user.last_name) if message.from_user.last_name else "")
    valid, resp = await process_location_async(user_id, message.location.latitude, message.location.longitude,
                                                 full_name, message.from_user.username, action)
    # Отправляем ответ с главным меню, чтобы кнопки остались
    await message.answer(resp, reply_markup=main_menu)

@dp.message_handler(lambda message: ("google.com/maps" in message.text or "goo.gl/maps" in message.text))
async def google_maps_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_actions:
        return
    action = pending_actions.pop(user_id)
    coords = re.findall(r"(-?\d+\.\d+),\s*(-?\d+\.\d+)", message.text)
    if not coords:
        await message.answer("Не удалось определить координаты из ссылки. Попробуйте отправить локацию через кнопку.",
                             reply_markup=main_menu)
        return
    lat, lon = map(float, coords[0])
    full_name = message.from_user.first_name + ((" " + message.from_user.last_name) if message.from_user.last_name else "")
    valid, resp = await process_location_async(user_id, lat, lon, full_name, message.from_user.username, action)
    await message.answer(resp, reply_markup=main_menu)

# === Новая команда: /search ===
@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    # Доступна только администратору
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Используйте: /search <user_id>")
        return
    try:
        search_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный user_id. Он должен быть числом.")
        return
    records = get_all_records()
    filtered_records = []
    for rec in records:
        # rec: (user_id, username, full_name, action, timestamp)
        if rec[0] == search_id:
            try:
                utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
            except Exception:
                utc_time = datetime.datetime.fromisoformat(rec[4])
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            tashkent_time = utc_time.astimezone(tz)
            adjusted_time = tashkent_time.strftime('%Y-%m-%d %H:%M:%S')
            filtered_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not filtered_records:
        await message.answer("Нет записей для данного пользователя.")
    else:
        result_text = f"Записи для пользователя {search_id}:\n\n"
        for rec in filtered_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            result_text += f"Пользователь: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(result_text)

@dp.message_handler(lambda message: message.text == '📊 Моя статистика')
async def stats(message: types.Message):
    try:
        total = get_user_stats(message.from_user.id)
    except Exception as e:
        logging.error(f"Error getting stats: {e}")
        total = 0
    await message.answer(f"📊 Ваша активность:\n\n📅 Всего отметок: {total}")

@dp.message_handler(lambda message: message.text == '🕒 Установить график')
async def set_schedule_handler(message: types.Message):
    await message.answer("Введите ваш график в формате HH:MM-HH:MM (например, 14:00-22:00)")

@dp.message_handler(commands=['edit_schedule'])
async def edit_schedule(message: types.Message):
    current = get_schedule(message.from_user.id)
    if current:
        msg = f"Ваш текущий график: {current[0]} - {current[1]}\n"
    else:
        msg = "У вас не установлен график.\n"
    msg += "Введите новый график в формате HH:MM-HH:MM (например, 09:00-17:00)"
    await message.answer(msg)

@dp.message_handler(lambda message: '-' in message.text and ':' in message.text)
async def schedule_input(message: types.Message):
    try:
        parts = message.text.split('-')
        if len(parts) != 2:
            raise ValueError("Неверный формат")
        start_str = parts[0].strip()
        end_str = parts[1].strip()
        datetime.datetime.strptime(start_str, '%H:%M')
        datetime.datetime.strptime(end_str, '%H:%M')
        set_schedule(message.from_user.id, start_str, end_str)
        await message.answer(f"✅ График установлен: {start_str} - {end_str}")
    except Exception as e:
        logging.error(f"Error setting schedule: {e}")
        await message.answer("Ошибка! Введите время в формате HH:MM-HH:MM (например, 14:00-22:00)")

@dp.message_handler(commands=['daily_report'])
async def daily_report(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    all_records = get_all_records()
    daily_records = []
    for rec in all_records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        tashkent_time = utc_time.astimezone(tz)
        if tashkent_time.date() == today:
            adjusted_time = tashkent_time.strftime('%Y-%m-%d %H:%M:%S')
            daily_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not daily_records:
        await message.answer("Нет записей за сегодня.")
    else:
        report = f"Отчёт за {today.strftime('%Y-%m-%d')}:\n\n"
        for rec in daily_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Пользователь: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['weekly_report'])
async def weekly_report(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    week_ago = today - datetime.timedelta(days=7)
    all_records = get_all_records()
    weekly_records = []
    for rec in all_records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        tashkent_time = utc_time.astimezone(tz)
        if week_ago <= tashkent_time.date() <= today:
            adjusted_time = tashkent_time.strftime('%Y-%m-%d %H:%M:%S')
            weekly_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not weekly_records:
        await message.answer("Нет записей за последнюю неделю.")
    else:
        report = f"Отчёт за последнюю неделю ({week_ago} - {today}):\n\n"
        for rec in weekly_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Пользователь: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['monthly_report'])
async def monthly_report(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    month_ago = today - datetime.timedelta(days=30)
    all_records = get_all_records()
    monthly_records = []
    for rec in all_records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        tashkent_time = utc_time.astimezone(tz)
        if month_ago <= tashkent_time.date() <= today:
            adjusted_time = tashkent_time.strftime('%Y-%m-%d %H:%M:%S')
            monthly_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not monthly_records:
        await message.answer("Нет записей за последний месяц.")
    else:
        report = f"Отчёт за последний месяц ({month_ago} - {today}):\n\n"
        for rec in monthly_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Пользователь: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['allstats'])
async def all_stats(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    records = get_all_records()
    if not records:
        await message.answer("Нет записей.")
        return

    adjusted_records = []
    for rec in records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        tashkent_time = utc_time.astimezone(tz)
        new_rec = (rec[0], rec[1], rec[2], rec[3], tashkent_time.strftime('%Y-%m-%d %H:%M:%S'))
        adjusted_records.append(new_rec)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "full_name", "action", "timestamp"])
    for rec in adjusted_records:
        writer.writerow(rec)
    output.seek(0)

    dates = {}
    for rec in adjusted_records:
        date_only = rec[4].split()[0]
        if date_only not in dates:
            dates[date_only] = {"arrived": 0, "left": 0}
        if rec[3] == "arrived":
            dates[date_only]["arrived"] += 1
        elif rec[3] == "left":
            dates[date_only]["left"] += 1
    sorted_dates = sorted(dates.keys())
    arrived_counts = [dates[d]["arrived"] for d in sorted_dates]
    left_counts = [dates[d]["left"] for d in sorted_dates]

    plt.figure(figsize=(10, 5))
    plt.plot(sorted_dates, arrived_counts, marker='o', label='Приход')
    plt.plot(sorted_dates, left_counts, marker='o', label='Уход')
    plt.xlabel('Дата')
    plt.ylabel('Количество')
    plt.title('Статистика прихода и ухода')
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png')
    plt.close()
    img_buffer.seek(0)

    await bot.send_document(
        ADMIN_CHAT_ID,
        types.InputFile(io.BytesIO(output.getvalue().encode('utf-8')), filename="allstats.csv")
    )
    await bot.send_photo(ADMIN_CHAT_ID, photo=types.InputFile(img_buffer, filename="stats.png"))

@dp.message_handler(commands=['send_summary'])
async def send_summary(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    await message.answer("Функция отправки отчётов на email ещё не реализована.")

# === Админ-панель ===
@dp.message_handler(commands=['admin_panel'])
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Детализированный отчёт", callback_data="detailed_report"),
        InlineKeyboardButton("Управление правами", callback_data="manage_access"),
        InlineKeyboardButton("Редактировать расписания", callback_data="edit_schedules")
    )
    await message.answer("Выберите опцию админ-панели:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == "detailed_report")
async def process_detailed_report(callback_query: types.CallbackQuery):
    records = get_all_records()
    if not records:
        detailed_text = "Нет записей."
    else:
        detailed_text = "Детализированный отчёт:\n\n"
        for rec in records:
            detailed_text += f"ID: {rec[0]}, Пользователь: {rec[2]}, Действие: {rec[3]}, Время: {rec[4]}\n"
    await bot.send_message(ADMIN_CHAT_ID, detailed_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "manage_access")
async def process_manage_access(callback_query: types.CallbackQuery):
    await bot.send_message(ADMIN_CHAT_ID, "Функция управления правами доступа пока не реализована.")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "edit_schedules")
async def process_edit_schedules(callback_query: types.CallbackQuery):
    await bot.send_message(ADMIN_CHAT_ID, "Чтобы редактировать расписания, используйте команду /edit_schedule")
    await bot.answer_callback_query(callback_query.id)

# === Напоминания по расписанию ===
async def check_shift_reminders():
    schedules = get_all_schedules()
    now = datetime.datetime.now(tz)
    for sch in schedules:
        user_id, start_time, end_time = sch
        try:
            start_dt = datetime.datetime.strptime(start_time, '%H:%M')
            end_dt = datetime.datetime.strptime(end_time, '%H:%M')
        except Exception as e:
            logging.error(f"Error parsing schedule times: {e}")
            continue
        start_dt = now.replace(hour=start_dt.hour, minute=start_dt.minute, second=0, microsecond=0)
        end_dt = now.replace(hour=end_dt.hour, minute=end_dt.minute, second=0, microsecond=0)
        reminder_start = start_dt - datetime.timedelta(minutes=15)
        reminder_end = end_dt - datetime.timedelta(minutes=10)
        if reminder_start <= now < reminder_start + datetime.timedelta(minutes=1):
            await bot.send_message(user_id, f"⏰ Напоминание: Ваша смена начинается в {start_time}. Не забудьте отметить приход!")
        if reminder_end <= now < reminder_end + datetime.timedelta(minutes=1):
            await bot.send_message(user_id, f"⏰ Напоминание: Ваша смена заканчивается в {end_time}. Не забудьте отметить уход!")

scheduler = AsyncIOScheduler()
scheduler.add_job(check_shift_reminders, 'interval', minutes=1)
scheduler.start()

if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)