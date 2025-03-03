from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from database import init_db, log_action, get_user_stats
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

init_db()

@dp.message_handler(commands=['start_work'])
async def start_work(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, 'start_work')
    await message.reply('✅ Вы отметили приход!')

@dp.message_handler(commands=['end_work'])
async def end_work(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, 'end_work')
    await message.reply('⏳ Вы отметили уход!')

@dp.message_handler(commands=['stats'])
async def stats(message: types.Message):
    records = get_user_stats(message.from_user.id)
    if not records:
        await message.reply('📉 Нет данных по вашему аккаунту.')
        return

    response = '📊 Ваша статистика:\n'
    for record in records:
        response += f"{record.timestamp.strftime('%Y-%m-%d %H:%M:%S')} — {record.action}\n"

    await message.reply(response)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)