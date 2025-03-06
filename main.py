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

# Ограничение доступа: только один разрешённый пользователь
ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID'))
ADMIN_CHAT_ID = ALLOWED_USER_ID  # Админ – единственный разрешённый
tz = pytz.timezone('Asia/Tashkent')

# Дефолтный список сотрудников (7 человек)
employees = [
    "Сотрудник 1",
    "Сотрудник 2",
    "Сотрудник 3",
    "Сотрудник 4",
    "Сотрудник 5",
    "Сотрудник 6",
    "Сотрудник 7"
]

# Флаг для ожидания редактирования списка сотрудников
pending_employee_edit = False

# (Функция геолокации остаётся, хотя в данной версии она не используется)
def calculate_distance(lat: float, lon: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat)
    delta_lambda = math.radians(lon2 - lon)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Главное меню, которое будет отображаться после выполнения действий
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_menu.add(KeyboardButton('✅ Я пришёл'), KeyboardButton('🏁 Я ушёл'))
main_menu.add(KeyboardButton('📊 Моя статистика'))
main_menu.add(KeyboardButton('🕒 Установить график'))

def check_access(message: types.Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID

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
    keyboard.add(
        InlineKeyboardButton("Приход", callback_data=f"attend_arrived_{index}"),
        InlineKeyboardButton("Уход", callback_data=f"attend_left_{index}")
    )
    await bot.send_message(callback_query.from_user.id,
                           f"Вы выбрали сотрудника: {employee_name}\nВыберите действие:",
                           reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# --- Обработка отметки "Приход" ---
@dp.callback_query_handler(lambda c: c.data.startswith("attend_arrived_"))
async def attend_arrived_handler(callback_query: types.CallbackQuery):
    index = int(callback_query.data.split("_")[-1])
    employee_name = employees[index]
    now = datetime.datetime.now(tz)
    try:
        log_action(index + 1, "", employee_name, "arrived")
    except Exception as e:
        logging.error(f"Error logging arrived: {e}")
    # Отправляем уведомление сотруднику
    await bot.send_message(callback_query.from_user.id,
                           f"Приход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}",
                           reply_markup=main_menu)
    # Отправляем уведомление администратору
    await bot.send_message(ADMIN_CHAT_ID,
                           f"Приход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}")
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
                           f"Уход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}",
                           reply_markup=main_menu)
    await bot.send_message(ADMIN_CHAT_ID,
                           f"Уход сотрудника {employee_name} зафиксирован в {now.strftime('%Y-%m-%d %H:%M:%S')}")
    await bot.answer_callback_query(callback_query.id)

# --- Команда /edit_employees для редактирования списка сотрудников ---
@dp.message_handler(commands=['edit_employees'])
async def edit_employees(message: types.Message):
    if not check_access(message):
        await message.answer("Access denied")
        return
    global pending_employee_edit
    pending_employee_edit = True
    await message.answer("Введите новый список сотрудников через запятую (например: Иванов, Петров, Сидоров):")

@dp.message_handler(lambda message: pending_employee_edit and check_access(message))
async def handle_employee_edit(message: types.Message):
    global employees, pending_employee_edit
    new_list = [name.strip() for name in message.text.split(",") if name.strip()]
    if not new_list:
        await message.answer("Список пуст. Попробуйте еще раз.")
        return
    employees = new_list
    pending_employee_edit = False
    await message.answer(f"Список сотрудников обновлён: {', '.join(employees)}", reply_markup=main_menu)

# --- Команда /delete_employee для удаления сотрудника ---
@dp.message_handler(commands=['delete_employee'])
async def delete_employee(message: types.Message):
    if not check_access(message):
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
    await message.answer(f"Сотрудник '{removed}' удалён.\nТекущий список: {', '.join(employees)}", reply_markup=main_menu)

# --- Команда /search для поиска записей по employee_id (номер сотрудника) ---
@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    if not check_access(message):
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
            tashkent_time = utc_time.astimezone(tz)
            adjusted_time = tashkent_time.strftime('%Y-%m-%d %H:%M:%S')
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

# --- Остальные команды (расписание, отчёты, графики) ---
@dp.message_handler(commands=['edit_schedule'])
async def edit_schedule(message: types.Message):
    if not check_access(message):
        await message.answer("Access denied")
        return
    current = get_schedule(message.from_user.id)
    if current:
        msg = f"Ваш текущий график: {current[0]} - {current[1]}\n"
    else:
        msg = "У вас не установлен график.\n"
    msg += "Введите новый график в формате HH:MM-HH:MM (например, 09:00-17:00)"
    await message.answer(msg)

@dp.message_handler(lambda message: '-' in message.text and ':' in message.text)
async def schedule_input(message: types.Message):
    if not check_access(message):
        await message.answer("Access denied")
        return
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
    if not check_access(message):
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
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['weekly_report'])
async def weekly_report(message: types.Message):
    if not check_access(message):
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
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['monthly_report'])
async def monthly_report(message: types.Message):
    if not check_access(message):
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
            report += f"Сотрудник: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

@dp.message_handler(commands=['allstats'])
async def all_stats(message: types.Message):
    if not check_access(message):
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
    writer.writerow(["employee_id", "username", "employee_name", "action", "timestamp"])
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
    if not check_access(message):
        await message.answer("Access denied")
        return
    await message.answer("Функция отправки отчётов на email ещё не реализована.")

# --- Админ-панель ---
@dp.message_handler(commands=['admin_panel'])
async def admin_panel(message: types.Message):
    if not check_access(message):
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
    await bot.send_message(ADMIN_CHAT_ID, "Чтобы редактировать расписания, используйте команду /edit_schedule")
    await bot.answer_callback_query(callback_query.id)

# --- Напоминания по расписанию ---
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