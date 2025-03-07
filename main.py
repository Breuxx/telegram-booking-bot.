import logging
import math
import re
import datetime
import csv
import io
import os
import asyncio
import sqlite3

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import pytz
from openpyxl import Workbook

# Для фонового планирования напоминаний и ежемесячной очистки
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

# Разделяем переменные:
ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID'))  # ID для сотрудников (общий доступ)
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))        # ID администратора (админские команды и отчёты)

tz = pytz.timezone('Asia/Tashkent')

# Дефолтный список сотрудников (7 сотрудников) с эмодзи
employees = [
    "👤 Сотрудник 1",
    "👤 Сотрудник 2",
    "👤 Сотрудник 3",
    "👤 Сотрудник 4",
    "👤 Сотрудник 5",
    "👤 Сотрудник 6",
    "👤 Сотрудник 7"
]

# Флаги для редактирования списка сотрудников
pending_employee_edit = False

# Функция геолокации оставлена (не используется в данной версии)
def calculate_distance(lat: float, lon: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat)
    delta_lambda = math.radians(lon2 - lon)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Главное меню для сотрудников – после отметки клавиатура удаляется, чтобы следующий сотрудник заново вызывал /start.
default_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
default_menu.add(KeyboardButton("🚀 Отметить приход"), KeyboardButton("🌙 Отметить уход"))
default_menu.add(KeyboardButton("📈 Статистика"), KeyboardButton("⏰ Установить график"))

# Функция проверки доступа для общих команд (приход/уход)
def check_access(message: types.Message) -> bool:
    return message.from_user.id in (ALLOWED_USER_ID, ADMIN_CHAT_ID)

# Функция проверки для админских команд – только ADMIN_CHAT_ID
def admin_only(message: types.Message) -> bool:
    return message.from_user.id == ADMIN_CHAT_ID

# --- Команда /start ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    if not check_access(message):
        await message.answer("Access denied")
        return
    # Отображаем список сотрудников через inline-клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=2)
    for i, emp in enumerate(employees):
        keyboard.add(InlineKeyboardButton(emp, callback_data=f"employee_{i}"))
    await message.answer("Выберите сотрудника для отметки прихода/ухода:", reply_markup=keyboard)

# --- Обработка выбора сотрудника ---
@dp.callback_query_handler(lambda c: c.data.startswith("employee_"))
async def employee_selection_handler(callback_query: types.CallbackQuery):
    index = int(callback_query.data.split("_")[1])
    employee_name = employees[index]
    keyboard = InlineKeyboardMarkup(row_width=2)
    # Кнопки с эмодзи для действия
    keyboard.add(
        InlineKeyboardButton("🔥 Приход", callback_data=f"attend_arrived_{index}"),
        InlineKeyboardButton("🌓 Уход", callback_data=f"attend_left_{index}")
    )
    await bot.send_message(callback_query.from_user.id,
                           f"Вы выбрали сотрудника: {employee_name}\nВыберите действие:",
                           reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# --- Обработка отметки "Приход" с проверкой опоздания ---
@dp.callback_query_handler(lambda c: c.data.startswith("attend_arrived_"))
async def attend_arrived_handler(callback_query: types.CallbackQuery):
    index = int(callback_query.data.split("_")[-1])
    employee_name = employees[index]
    now = datetime.datetime.now(tz)
    tardy_message = ""
    try:
        log_action(index + 1, "", employee_name, "arrived")
    except Exception as e:
        logging.error(f"Error logging arrived: {e}")
    # Проверка расписания для данного сотрудника (если установлено)
    schedule = get_schedule(index + 1)
    if schedule:
        scheduled_start = schedule[0]  # строка "HH:MM"
        try:
            scheduled_start_dt = datetime.datetime.strptime(f"{now.date()} {scheduled_start}", "%Y-%m-%d %H:%M")
            if now > scheduled_start_dt:
                delay = now - scheduled_start_dt
                tardy_minutes = int(delay.total_seconds() / 60)
                tardy_message = f"\n⚠️ Опоздание: {tardy_minutes} мин."
                # Отправляем уведомление об опоздании администратору (будет также включено в отдельный отчет в /allstats)
                await bot.send_message(ADMIN_CHAT_ID,
                                       f"⚠️ Сотрудник {employee_name} опоздал на {tardy_minutes} мин. (запланировано: {scheduled_start}, пришёл: {now.strftime('%H:%M')})")
        except Exception as e:
            logging.error(f"Error processing schedule for tardiness: {e}")
    await bot.send_message(callback_query.from_user.id,
                           f"🔥 Приход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}{tardy_message}",
                           reply_markup=ReplyKeyboardRemove())
    await bot.send_message(ADMIN_CHAT_ID,
                           f"🔥 Приход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}{tardy_message}")
    await bot.answer_callback_query(callback_query.id)

# --- Обработка отметки "Уход" ---
@dp.callback_query_handler(lambda c: c.data.startswith("attend_left_"))
async def attend_left_handler(callback_query: types.CallbackQuery):
    index = int(callback_query.data.split("_")[-1])
    employee_name = employees[index]
    now = datetime.datetime.now(tz)
    try:
        log_action(index + 1, "", employee_name, "left")
    except Exception as e:
        logging.error(f"Error logging left: {e}")
    await bot.send_message(callback_query.from_user.id,
                           f"🌓 Уход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}",
                           reply_markup=ReplyKeyboardRemove())
    await bot.send_message(ADMIN_CHAT_ID,
                           f"🌓 Уход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}")
    await bot.answer_callback_query(callback_query.id)

# --- Команда /edit_employees (АДМИНСКАЯ) ---
@dp.message_handler(commands=['edit_employees'])
async def edit_employees(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    global pending_employee_edit
    pending_employee_edit = True
    await message.answer("Введите новый список сотрудников через запятую (например: Иванов, Петров, Сидоров):")

@dp.message_handler(lambda message: pending_employee_edit and admin_only(message))
async def handle_employee_edit(message: types.Message):
    global employees, pending_employee_edit
    new_list = []
    for name in message.text.split(","):
        name = name.strip()
        if name and not name.startswith("👤"):
            name = "👤 " + name
        new_list.append(name)
    if not new_list:
        await message.answer("Список пуст. Попробуйте еще раз.")
        return
    employees = new_list
    pending_employee_edit = False
    await message.answer(f"Список сотрудников обновлён: {', '.join(employees)}", reply_markup=ReplyKeyboardRemove())

# --- Команда /add_employee (АДМИНСКАЯ) ---
@dp.message_handler(commands=['add_employee'])
async def add_employee(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    new_emp = message.get_args().strip()
    if not new_emp:
        await message.answer("Используйте: /add_employee <имя сотрудника>")
        return
    if not new_emp.startswith("👤"):
        new_emp = "👤 " + new_emp
    employees.append(new_emp)
    await message.answer(f"Сотрудник {new_emp} добавлен.\nТекущий список: {', '.join(employees)}", reply_markup=ReplyKeyboardRemove())

# --- Команда /delete_employee (АДМИНСКАЯ) ---
@dp.message_handler(commands=['delete_employee'])
async def delete_employee(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Используйте: /delete_employee <employee_number>\n(Нумерация начинается с 1)")
        return
    try:
        idx = int(parts[1]) - 1
    except ValueError:
        await message.answer("Некорректный номер сотрудника. Он должен быть числом.")
        return
    if idx < 0 or idx >= len(employees):
        await message.answer("Сотрудник с таким номером не найден.")
        return
    removed = employees.pop(idx)
    await message.answer(f"Сотрудник '{removed}' удалён.\nТекущий список: {', '.join(employees)}", reply_markup=ReplyKeyboardRemove())

# --- Команда /set_schedule_for (АДМИНСКАЯ) ---
@dp.message_handler(commands=['set_schedule_for'])
async def set_schedule_for(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Используйте: /set_schedule_for <employee_number> <start>-<end>\nНапример: /set_schedule_for 1 14:00-22:00")
        return
    try:
        employee_num = int(parts[1])
        schedule_str = parts[2]
        if '-' not in schedule_str:
            raise ValueError
        start_str, end_str = schedule_str.split('-')
        start_str = start_str.strip()
        end_str = end_str.strip()
        datetime.datetime.strptime(start_str, '%H:%M')
        datetime.datetime.strptime(end_str, '%H:%M')
        set_schedule(employee_num, start_str, end_str)
        await message.answer(f"График для сотрудника {employee_num} установлен: {start_str} - {end_str}", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logging.error(f"Error in set_schedule_for: {e}")
        await message.answer("Ошибка! Используйте формат: /set_schedule_for <employee_number> <start>-<end>\nНапример: /set_schedule_for 1 14:00-22:00", reply_markup=ReplyKeyboardRemove())

# --- Команда /search (АДМИНСКАЯ) ---
@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Используйте: /search <employee_id>")
        return
    try:
        search_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный employee_id. Он должен быть числом.")
        return
    records = get_all_records()
    filtered_records = []
    for rec in records:
        if rec[0] == search_id:
            try:
                utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
            except Exception:
                utc_time = datetime.datetime.fromisoformat(rec[4])
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            adjusted_time = utc_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
            filtered_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not filtered_records:
        await message.answer("Нет записей для данного сотрудника.")
    else:
        result_text = f"Записи для сотрудника {search_id}:\n\n"
        for rec in filtered_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            result_text += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(result_text)

# --- Команда /edit_schedule (АДМИНСКАЯ) ---
@dp.message_handler(commands=['edit_schedule'])
async def edit_schedule(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    await message.answer("Для редактирования расписания используйте команду /set_schedule_for.\nПример: /set_schedule_for 1 14:00-22:00", reply_markup=ReplyKeyboardRemove())

# --- Команды отчетности (АДМИНСКИЕ) ---
@dp.message_handler(commands=['daily_report'])
async def daily_report(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    records = get_all_records()
    daily_records = []
    for rec in records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        if utc_time.astimezone(tz).date() == today:
            adjusted_time = utc_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
            daily_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not daily_records:
        await message.answer("Нет записей за сегодня.")
    else:
        report = f"Отчёт за {today.strftime('%Y-%m-%d')}:\n\n"
        for rec in daily_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['weekly_report'])
async def weekly_report(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    week_ago = today - datetime.timedelta(days=7)
    records = get_all_records()
    weekly_records = []
    for rec in records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        if week_ago <= utc_time.astimezone(tz).date() <= today:
            adjusted_time = utc_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
            weekly_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not weekly_records:
        await message.answer("Нет записей за последнюю неделю.")
    else:
        report = f"Отчёт за последнюю неделю ({week_ago} - {today}):\n\n"
        for rec in weekly_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['monthly_report'])
async def monthly_report(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).date()
    month_ago = today - datetime.timedelta(days=30)
    records = get_all_records()
    monthly_records = []
    for rec in records:
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        if month_ago <= utc_time.astimezone(tz).date() <= today:
            adjusted_time = utc_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
            monthly_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    if not monthly_records:
        await message.answer("Нет записей за последний месяц.")
    else:
        report = f"Отчёт за последний месяц ({month_ago} - {today}):\n\n"
        for rec in monthly_records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['allstats'])
async def all_stats(message: types.Message):
    if not admin_only(message):
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
        adjusted_time = utc_time.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
        adjusted_records.append((rec[0], rec[1], rec[2], rec[3], adjusted_time))
    # Генерируем CSV-файл для всех записей
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["employee_id", "username", "employee_name", "action", "timestamp"])
    for rec in adjusted_records:
        writer.writerow(rec)
    output.seek(0)
    # Генерируем Excel-файл для всех записей
    wb_all = Workbook()
    ws_all = wb_all.active
    ws_all.append(["employee_id", "username", "employee_name", "action", "timestamp"])
    for rec in adjusted_records:
        ws_all.append(rec)
    all_xlsx = io.BytesIO()
    wb_all.save(all_xlsx)
    all_xlsx.seek(0)
    # Отправляем CSV и Excel файлы, а также график
    await bot.send_document(
        ADMIN_CHAT_ID,
        types.InputFile(io.BytesIO(output.getvalue().encode('utf-8')), filename="allstats.csv")
    )
    await bot.send_document(
        ADMIN_CHAT_ID,
        types.InputFile(all_xlsx, filename="allstats.xlsx")
    )
    # Генерируем график
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
    await bot.send_photo(ADMIN_CHAT_ID, photo=types.InputFile(img_buffer, filename="stats.png"))
    # --- Дополнительно: формируем файлы для опоздавших ---
    tardy_records = []
    # Для каждого "прихода" вычисляем опоздание по расписанию, если оно установлено
    for rec in records:
        if rec[3] == "arrived":
            try:
                utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
            except Exception:
                utc_time = datetime.datetime.fromisoformat(rec[4])
            utc_time = utc_time.replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(tz)
            schedule = get_schedule(rec[0])
            if schedule:
                scheduled_start = schedule[0]
                try:
                    scheduled_start_dt = datetime.datetime.strptime(f"{local_time.date()} {scheduled_start}", "%Y-%m-%d %H:%M")
                    if local_time > scheduled_start_dt:
                        tardiness_minutes = int((local_time - scheduled_start_dt).total_seconds() / 60)
                        tardy_records.append((rec[0], rec[1], rec[2], "arrived (опоздание)", local_time.strftime('%Y-%m-%d %H:%M:%S'), scheduled_start, tardiness_minutes))
                except Exception as e:
                    logging.error(f"Error processing tardiness for record {rec}: {e}")
    # Если есть опоздавшие, создаём файлы для них
    if tardy_records:
        # TXT-файл для опоздавших
        txt_lines = ["employee_id, username, employee_name, action, arrival_time, scheduled_start, tardiness_minutes"]
        for rec in tardy_records:
            txt_lines.append(", ".join(str(x) for x in rec))
        tardy_txt_content = "\n".join(txt_lines)
        # Excel-файл для опоздавших
        wb_tardy = Workbook()
        ws_tardy = wb_tardy.active
        ws_tardy.append(["employee_id", "username", "employee_name", "action", "arrival_time", "scheduled_start", "tardiness_minutes"])
        for rec in tardy_records:
            ws_tardy.append(rec)
        tardy_xlsx = io.BytesIO()
        wb_tardy.save(tardy_xlsx)
        tardy_xlsx.seek(0)
        # Отправляем файлы для опоздавших
        await bot.send_document(
            ADMIN_CHAT_ID,
            types.InputFile(io.BytesIO(tardy_txt_content.encode('utf-8')), filename="tardy_report.txt")
        )
        await bot.send_document(
            ADMIN_CHAT_ID,
            types.InputFile(tardy_xlsx, filename="tardy_report.xlsx")
        )

@dp.message_handler(commands=['send_summary'])
async def send_summary(message: types.Message):
    if not admin_only(message):
        await message.answer("Access denied")
        return
    await message.answer("Функция отправки отчётов на email ещё не реализована.")

# --- Админ-панель (АДМИНСКАЯ) ---
@dp.message_handler(commands=['admin_panel'])
async def admin_panel(message: types.Message):
    if not admin_only(message):
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
            detailed_text += f"ID: {rec[0]}, Сотрудник: {rec[2]}, Действие: {rec[3]}, Время: {rec[4]}\n"
    await bot.send_message(ADMIN_CHAT_ID, detailed_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "manage_access")
async def process_manage_access(callback_query: types.CallbackQuery):
    await bot.send_message(ADMIN_CHAT_ID, "Функция управления правами доступа пока не реализована.")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "edit_schedules")
async def process_edit_schedules(callback_query: types.CallbackQuery):
    await bot.send_message(ADMIN_CHAT_ID, "Для редактирования расписаний используйте команду /set_schedule_for")
    await bot.answer_callback_query(callback_query.id)

# --- Напоминания по расписанию ---
async def check_shift_reminders():
    schedules = get_all_schedules()
    now = datetime.datetime.now(tz)
    for sch in schedules:
        employee_id, start_time, end_time = sch
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
            await bot.send_message(employee_id, f"⏰ Напоминание: Ваша смена начинается в {start_time}. Не забудьте отметить приход!")
        if reminder_end <= now < reminder_end + datetime.timedelta(minutes=1):
            await bot.send_message(employee_id, f"⏰ Напоминание: Ваша смена заканчивается в {end_time}. Не забудьте отметить уход!")

# --- Ежемесячная очистка базы ---
async def monthly_cleanup():
    try:
        now = datetime.datetime.now(tz)
        cutoff = now - datetime.timedelta(days=30)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attendance WHERE timestamp < ?", (cutoff_str,))
        old_records = cursor.fetchall()
        if old_records:
            # Формируем TXT-отчёт
            txt_lines = ["employee_id, username, employee_name, action, timestamp"]
            for rec in old_records:
                txt_lines.append(", ".join(str(x) for x in rec))
            txt_content = "\n".join(txt_lines)
            # Формируем CSV-отчёт (для Excel)
            csv_output = io.StringIO()
            writer = csv.writer(csv_output)
            writer.writerow(["employee_id", "username", "employee_name", "action", "timestamp"])
            for rec in old_records:
                writer.writerow(rec)
            csv_data = csv_output.getvalue()
            csv_output.close()
            # Пытаемся отправить отчёты
            await bot.send_document(ADMIN_CHAT_ID,
                                    types.InputFile(io.BytesIO(txt_content.encode('utf-8')), filename="monthly_report.txt"))
            await bot.send_document(ADMIN_CHAT_ID,
                                    types.InputFile(io.BytesIO(csv_data.encode('utf-8')), filename="monthly_report.csv"))
            # Если отчёты успешно отправлены, удаляем устаревшие записи
            cursor.execute("DELETE FROM attendance WHERE timestamp < ?", (cutoff_str,))
            conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Monthly cleanup error: {e}")

scheduler = AsyncIOScheduler()
scheduler.add_job(check_shift_reminders, 'interval', minutes=1)
# Ежемесячная очистка: каждый 1-й день месяца в 00:00 по Tashkента
scheduler.add_job(monthly_cleanup, 'cron', day=1, hour=0, minute=0, timezone=tz)
scheduler.start()

if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)