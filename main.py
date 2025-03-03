import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from db import init_db, log_action, get_user_stats
from dotenv import load_dotenv
import os
import datetime

# Загрузка переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher(bot)

# Получаем ID администратора
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

# Главное меню
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_menu.add(KeyboardButton('✅ Я пришёл'), KeyboardButton('🏁 Я ушёл'))
main_menu.add(KeyboardButton('📊 Моя статистика'))

# Стартовое сообщение
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(f"👋 Привет, {message.from_user.first_name}!\n\nВыбери действие:", reply_markup=main_menu)

# Обработчик для прихода
@dp.message_handler(lambda message: message.text == '✅ Я пришёл')
async def arrived(message: types.Message):
    now = datetime.datetime.now()  # получаем текущее время
    log_action(message.from_user.id, message.from_user.username, 'arrived')
    await message.answer('✅ Ваш приход отмечен!\n\nХорошего рабочего дня!')
    # Формируем сообщение для администратора
    admin_message = (
        f"📌 **Приход**:\n"
        f"Пользователь: {message.from_user.first_name} (@{message.from_user.username})\n"
        f"ID: {message.from_user.id}\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

# Обработчик для ухода
@dp.message_handler(lambda message: message.text == '🏁 Я ушёл')
async def left(message: types.Message):
    now = datetime.datetime.now()  # получаем текущее время
    log_action(message.from_user.id, message.from_user.username, 'left')
    await message.answer('🏁 Ваш уход отмечен!\n\nХорошего отдыха!')
    admin_message = (
        f"📌 **Уход**:\n"
        f"Пользователь: {message.from_user.first_name} (@{message.from_user.username})\n"
        f"ID: {message.from_user.id}\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')

# Обработчик для вывода статистики
@dp.message_handler(lambda message: message.text == '📊 Моя статистика')
async def stats(message: types.Message):
    total = get_user_stats(message.from_user.id)
    await message.answer(f"📊 Ваша активность:\n\n📅 Всего отметок: {total}")

if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)