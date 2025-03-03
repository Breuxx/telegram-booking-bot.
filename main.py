import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from db import init_db, log_action, get_user_stats, get_daily_report, get_all_records
from dotenv import load_dotenv
import os
import datetime
import csv
import io

# Загрузка переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher(bot)

# Получаем ID администратора из переменных окружения
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

# Главное меню для пользователей
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_menu.add(KeyboardButton('✅ Я пришёл'), KeyboardButton('🏁 Я ушёл'))
main_menu.add(KeyboardButton('📊 Моя статистика'))

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(f"👋 Привет, {message.from_user.first_name}!\n\nВыбери действие:", reply_markup=main_menu)

@dp.message_handler(lambda message: message.text == '✅ Я пришёл')
async def arrived(message: types.Message):
    now = datetime.datetime.now()
    log_action(message.from_user.id, message.from_user.username, 'arrived')
    await message.answer('✅ Ваш приход отмечен!\n\nХорошего рабочего дня!')
    # Отправляем уведомление админу
    admin_message = (
        f"📌 **Приход**:\n"
        f"Пользователь: {message.from_user.first_name} (@{message.from_user.username})\n"
        f"ID: {message.from_user.id}\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

@dp.message_handler(lambda message: message.text == '🏁 Я ушёл')
async def left(message: types.Message):
    now = datetime.datetime.now()
    log_action(message.from_user.id, message.from_user.username, 'left')
    await message.answer('🏁 Ваш уход отмечен!\n\nХорошего отдыха!')
    # Отправляем уведомление админу
    admin_message = (
        f"📌 **Уход**:\n"
        f"Пользователь: {message.from_user.first_name} (@{message.from_user.username})\n"
        f"ID: {message.from_user.id}\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

@dp.message_handler(lambda message: message.text == '📊 Моя статистика')
async def stats(message: types.Message):
    total = get_user_stats(message.from_user.id)
    await message.answer(f"📊 Ваша активность:\n\n📅 Всего отметок: {total}")

# Команда для ежедневного отчёта (только для администратора)
@dp.message_handler(commands=['daily_report'])
async def daily_report(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    records = get_daily_report(today)
    if not records:
        await message.answer("Нет записей за сегодня.")
    else:
        report = f"Отчёт за {today}:\n\n"
        for rec in records:
            report += f"Пользователь: {rec[1]} (ID: {rec[0]}) - {rec[2]} в {rec[3]}\n"
        await message.answer(report)

# Команда для экспорта всех записей в CSV (только для администратора)
@dp.message_handler(commands=['allstats'])
async def all_stats(message: types.Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Access denied")
        return
    records = get_all_records()
    if not records:
        await message.answer("Нет записей.")
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "action", "timestamp"])
    for rec in records:
        writer.writerow(rec)
    output.seek(0)
    await bot.send_document(ADMIN_CHAT_ID,
                            types.InputFile(io.BytesIO(output.getvalue().encode('utf-8')), filename="allstats.csv"))

if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)