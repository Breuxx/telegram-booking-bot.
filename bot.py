import os
import logging
from datetime import datetime, time
import pytz

from telegram import Update, ReplyKeyboardMarkup, Sticker
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    JobQueue,
)

# Настройки
TOKEN = os.environ.get("TOKEN")  # Берем из переменных окружения Railway
ADMIN_ID = int(os.environ.get("ADMIN_ID"))  # Берем из переменных окружения
EXCEL_FILE = "checkins.xlsx"
EMPLOYEES_FILE = "employees.xlsx"
TIME_ZONE = pytz.timezone('Europe/Moscow')  # Установите свою временную зону

# Стикеры (замените на свои)
STICKERS = {
    "welcome": "CAACAgIAAxkBAAEL...",  # Пример ID стикера
    "success": "CAACAgQAAxkBAAEL...",
    "error": "CAACAgUAAxkBAAEL..."
}

# ... (остальные функции из предыдущего кода остаются без изменений)

def start(update: Update, context: CallbackContext) -> None:
    sticker_id = STICKERS["welcome"]
    update.message.reply_sticker(sticker_id)
    update.message.reply_text("Добро пожаловать в систему учета рабочего времени!")

def send_reminder(context: CallbackContext) -> None:
    """Ежедневное напоминание для всех сотрудников"""
    job = context.job
    now = datetime.now(TIME_ZONE)
    
    # Утреннее напоминание в 9:30
    if now.hour == 9 and now.minute == 30:
        df = pd.read_excel(EXCEL_FILE)
        today = now.strftime("%Y-%m-%d")
        employees = pd.read_excel(EMPLOYEES_FILE)
        
        for user_id in employees["user_id"]:
            if not df[(df["user_id"] == user_id) & (df["date"] == today)].empty:
                continue
            context.bot.send_message(
                chat_id=user_id,
                text="⏰ Не забудьте отметить приход командой /checkin!"
            )

    # Вечернее напоминание в 18:00
    elif now.hour == 18 and now.minute == 0:
        df = pd.read_excel(EXCEL_FILE)
        today = now.strftime("%Y-%m-%d")
        
        for _, row in df[df["checkout"].isna() & (df["date"] == today)].iterrows():
            context.bot.send_message(
                chat_id=row["user_id"],
                text="⏰ Не забудьте отметить уход командой /checkout!"
            )

def error_handler(update: Update, context: CallbackContext) -> None:
    """Обработка ошибок с отправкой стикера"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    update.message.reply_sticker(STICKERS["error"])
    update.message.reply_text("😢 Произошла ошибка. Попробуйте позже.")

def main() -> None:
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue

    # Инициализация напоминаний
    job_queue.run_daily(
        send_reminder,
        time(time(hour=9, minute=30), tzinfo=TIME_ZONE),
        days=(0, 1, 2, 3, 4, 5, 6)
    )
    
    job_queue.run_daily(
        send_reminder,
        time(time(hour=18, minute=0), tzinfo=TIME_ZONE),
        days=(0, 1, 2, 3, 4, 5, 6)
    )

    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    # ... остальные обработчики как в предыдущем коде
    
    # Обработка ошибок
    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()



