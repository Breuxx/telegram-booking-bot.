import os
import logging
from datetime import datetime, time
import pytz

import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
    ContextTypes
)

# Настройки
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
EXCEL_FILE = "checkins.xlsx"
EMPLOYEES_FILE = "employees.xlsx"
TIME_ZONE = pytz.timezone('Europe/Moscow')

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация файлов
def init_files():
    if not os.path.exists(EXCEL_FILE):
        pd.DataFrame(columns=["user_id", "name", "date", "checkin", "checkout"]).to_excel(
            EXCEL_FILE, index=False
        )
    if not os.path.exists(EMPLOYEES_FILE):
        pd.DataFrame(columns=["user_id", "name", "is_admin"]).to_excel(
            EMPLOYEES_FILE, index=False
        )

init_files()

# ... (Все остальные функции остаются аналогичными предыдущей версии, 
# но с заменой Filters на filters в обработчиках)

# Пример исправленного обработчика сообщений:
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    text = update.message.text
    
    if not is_admin(user_id):
        await update.message.reply_text("Неизвестная команда")
        return
        
    if text == "Скачать отчет":
        await update.message.reply_document(document=open(EXCEL_FILE, "rb"))
    elif text == "Добавить сотрудника":
        await update.message.reply_text("Введите команду в формате: /add_employee имя")
    elif text == "Изменить имя":
        await update.message.reply_text("Введите команду в формате: /update_employee старое_имя новое_имя")

# Главная функция
def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("checkout", checkout))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("add_employee", add_employee))
    application.add_handler(CommandHandler("update_employee", update_employee))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    
    # Регистрация пользователей
    application.add_handler(MessageHandler(filters.ALL, register_user))

    # Напоминания
    job_queue = application.job_queue
    job_queue.run_daily(
        send_reminder,
        time(hour=9, minute=30, tzinfo=TIME_ZONE),
        days=(0, 1, 2, 3, 4, 5, 6)
    )
    
    application.run_polling()

if __name__ == "__main__":
    main()