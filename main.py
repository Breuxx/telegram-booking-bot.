import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from db import init_db, log_action, get_user_stats, get_daily_report, get_all_records, set_schedule, get_all_schedules, get_schedule
from dotenv import load_dotenv
import os
import datetime
import csv
import io
import matplotlib.pyplot as plt
import pytz

# Для фонового планирования напоминаний
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Загрузка переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher(bot)

# Получаем ID администратора
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

# Устанавливаем часовой пояс для Tashkent
tz = pytz.timezone('Asia/Tashkent')

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

@dp.message_handler(lambda message: message.text == '✅ Я пришёл')
async def arrived(message: types.Message):
    now = datetime.datetime.now(tz)
    full_name = message.from_user.first_name
    if message.from_user.last_name:
        full_name += " " + message.from_user.last_name
    log_action(message.from_user.id, message.from_user.username, full_name, 'arrived')
    await message.answer('✅ Ваш приход отмечен!\n\nХорошего рабочего дня!')
    
    admin_message = f"📌 **Приход**:\nПользователь: {full_name}"
    if message.from_user.username:
        admin_message += f" (@{message.from_user.username})"
    admin_message += f"\nID: {message.from_user.id}\nВремя: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

@dp.message_handler(lambda message: message.text == '🏁 Я ушёл')
async def left(message: types.Message):
    now = datetime.datetime.now(tz)
    full_name = message.from_user.first_name
    if message.from_user.last_name:
        full_name += " " + message.from_user.last_name
    log_action(message.from_user.id, message.from_user.username, full_name, 'left')
    await message.answer('🏁 Ваш уход отмечен!\n\nХорошего отдыха!')
    
    admin_message = f"📌 **Уход**:\nПользователь: {full_name}"
    if message.from_user.username:
        admin_message += f" (@{message.from_user.username})"
    admin_message += f"\nID: {message.from_user.id}\nВремя: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

@dp.message_handler(lambda message: message.text == '📊 Моя статистика')
async def stats(message: types.Message):
    total = get_user_stats(message.from_user.id)
    await message.answer(f"📊 Ваша активность:\n\n📅 Всего отметок: {total}")

# Обработчик для установки графика работы
@dp.message_handler(lambda message: message.text == '🕒 Установить график')
async def set_schedule_handler(message: types.Message):
    await message.answer("Введите ваш график в формате HH:MM-HH:MM (например, 14:00-22:00)")

@dp.message_handler(lambda message: '-' in message.text and ':' in message.text)
async def schedule_input(message: types.Message):
    # Пример ввода: "14:00-22:00"
    try:
        parts = message.text.split('-')
        if len(parts) != 2:
            raise ValueError("Неверный формат")
        start_str = parts[0].strip()
        end_str = parts[1].strip()
        # Проверка формата времени
        datetime.datetime.strptime(start_str, '%H:%M')
        datetime.datetime.strptime(end_str, '%H:%M')
        set_schedule(message.from_user.id, start_str, end_str)
        await message.answer(f"✅ График установлен: {start_str} - {end_str}")
    except Exception as e:
        await message.answer("Ошибка! Введите время в формате HH:MM-HH:MM (например, 14:00-22:00)")

# Команда для ежедневного отчёта (только для администратора)
@dp.message_handler(commands=['daily_report'])
async def daily_report(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    today = datetime.datetime.now(tz).strftime('%Y-%m-%d')
    records = get_daily_report(today)
    if not records:
        await message.answer("Нет записей за сегодня.")
    else:
        report = f"Отчёт за {today}:\n\n"
        for rec in records:
            user_disp = rec[2]
            if rec[1]:
                user_disp += f" (@{rec[1]})"
            report += f"Пользователь: {user_disp} - {rec[3]} в {rec[4]}\n"
        await message.answer(report)

# Команда для экспорта всех записей в CSV и отправки графика (только для администратора)
@dp.message_handler(commands=['allstats'])
async def all_stats(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    records = get_all_records()
    if not records:
        await message.answer("Нет записей.")
        return

    # Конвертируем время из UTC в Tashkent для каждого лога
    adjusted_records = []
    for rec in records:
        # rec имеет вид: (user_id, username, full_name, action, timestamp)
        try:
            utc_time = datetime.datetime.strptime(rec[4], '%Y-%m-%d %H:%M:%S')
        except Exception:
            utc_time = datetime.datetime.fromisoformat(rec[4])
        utc_time = utc_time.replace(tzinfo=pytz.utc)
        tashkent_time = utc_time.astimezone(tz)
        new_rec = (rec[0], rec[1], rec[2], rec[3], tashkent_time.strftime('%Y-%m-%d %H:%M:%S'))
        adjusted_records.append(new_rec)

    # Формирование CSV-файла
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "full_name", "action", "timestamp"])
    for rec in adjusted_records:
        writer.writerow(rec)
    output.seek(0)

    # Генерация графика посещаемости (подсчёт количества 'приход' и 'уход' по датам)
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

    # Отправка CSV и графика администратору
    await bot.send_document(
        ADMIN_CHAT_ID,
        types.InputFile(io.BytesIO(output.getvalue().encode('utf-8')), filename="allstats.csv")
    )
    await bot.send_photo(ADMIN_CHAT_ID, photo=types.InputFile(img_buffer, filename="stats.png"))

# Функция, которая проверяет графики и отправляет напоминания
async def check_shift_reminders():
    schedules = get_all_schedules()
    now = datetime.datetime.now(tz)
    for sch in schedules:
        user_id, start_time, end_time = sch
        # Преобразуем строки времени в datetime для сегодняшней даты
        start_dt = datetime.datetime.strptime(start_time, '%H:%M')
        end_dt = datetime.datetime.strptime(end_time, '%H:%M')
        start_dt = now.replace(hour=start_dt.hour, minute=start_dt.minute, second=0, microsecond=0)
        end_dt = now.replace(hour=end_dt.hour, minute=end_dt.minute, second=0, microsecond=0)
        # Вычисляем время напоминания: за 15 минут до начала и окончания смены
        reminder_start = start_dt - datetime.timedelta(minutes=15)
        reminder_end = end_dt - datetime.timedelta(minutes=15)
        # Если текущее время попадает в 1-минутный интервал напоминания
        if reminder_start <= now < reminder_start + datetime.timedelta(minutes=1):
            await bot.send_message(user_id, f"⏰ Напоминание: Ваша смена начинается в {start_time}. Не забудьте отметить приход!")
        if reminder_end <= now < reminder_end + datetime.timedelta(minutes=1):
            await bot.send_message(user_id, f"⏰ Напоминание: Ваша смена заканчивается в {end_time}. Не забудьте отметить уход!")

# Инициализируем планировщик APScheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(check_shift_reminders, 'interval', minutes=1)
scheduler.start()

if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)