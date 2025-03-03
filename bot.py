import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from db import init_db, log_action, get_user_stats
from dotenv import load_dotenv
import os

# Загрузка переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher(bot)

# Главное меню
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
main_menu.add(KeyboardButton('✅ Я пришёл'), KeyboardButton('🏁 Я ушёл'))
main_menu.add(KeyboardButton('📊 Моя статистика'))

# Инлайн-кнопки подтверждения
confirm_menu = InlineKeyboardMarkup(row_width=2)
confirm_menu.add(InlineKeyboardButton('✅ Да', callback_data='confirm'),
                 InlineKeyboardButton('❌ Отмена', callback_data='cancel'))

# Стартовое сообщение
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(f"👋 Привет, {message.from_user.first_name}!\n\nВыбери действие:", reply_markup=main_menu)

# Приход
@dp.message_handler(lambda message: message.text == '✅ Я пришёл')
async def arrived(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, 'arrived')
    await message.answer('✅ Ваш приход отмечен!\n\nХорошего рабочего дня!')

# Уход
@dp.message_handler(lambda message: message.text == '🏁 Я ушёл')
async def left(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, 'left')
    await message.answer('🏁 Ваш уход отмечен!\n\nХорошего отдыха!')

# Статистика
@dp.message_handler(lambda message: message.text == '📊 Моя статистика')
async def stats(message: types.Message):
    total = get_user_stats(message.from_user.id)
    await message.answer(f"📊 Ваша активность:\n\n📅 Всего отметок: {total}")

# Запуск бота
if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)