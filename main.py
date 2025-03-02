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

def init_files():
    if not os.path.exists(EXCEL_FILE):
        pd.DataFrame(columns=["user_id", "name", "date", "checkin", "checkout"]).to_excel(EXCEL_FILE, index=False)
    if not os.path.exists(EMPLOYEES_FILE):
        pd.DataFrame(columns=["user_id", "name", "is_admin"]).to_excel(EMPLOYEES_FILE, index=False)

init_files()

def is_admin(user_id: int) -> bool:
    df = pd.read_excel(EMPLOYEES_FILE)
    return user_id in df[df["is_admin"] == True]["user_id"].values

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    df_employees = pd.read_excel(EMPLOYEES_FILE)
    
    if user_id not in df_employees["user_id"].values:
        await update.message.reply_text("Вы не зарегистрированы как сотрудник!")
        return
        
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.read_excel(EXCEL_FILE)
    
    if not df[(df["user_id"] == user_id) & (df["date"] == today)].empty:
        await update.message.reply_text("Вы уже отметили приход сегодня!")
        return
        
    name = df_employees[df_employees["user_id"] == user_id]["name"].values[0]
    new_row = {
        "user_id": user_id,
        "name": name,
        "date": today,
        "checkin": datetime.now().strftime("%H:%M:%S"),
        "checkout": None,
    }
    
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(EXCEL_FILE, index=False)
    await update.message.reply_text("Приход успешно зарегистрирован!")

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.read_excel(EXCEL_FILE)
    
    record = df[(df["user_id"] == user_id) & (df["date"] == today)]
    if record.empty:
        await update.message.reply_text("Сначала отметьте приход!")
        return
        
    if pd.notna(record.iloc[0]["checkout"]):
        await update.message.reply_text("Вы уже отметили уход сегодня!")
        return
        
    idx = record.index[0]
    df.at[idx, "checkout"] = datetime.now().strftime("%H:%M:%S")
    df.to_excel(EXCEL_FILE, index=False)
    await update.message.reply_text("Уход успешно зарегистрирован!")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("Доступ запрещен!")
        return
        
    keyboard = [["Скачать отчет"], ["Добавить сотрудника"], ["Изменить имя"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Админ-панель:", reply_markup=reply_markup)

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

async def add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
        
    try:
        name = update.message.text.split(" ", 1)[1]
        df = pd.read_excel(EMPLOYEES_FILE)
        
        if name in df["name"].values:
            await update.message.reply_text("Сотрудник уже существует!")
            return
            
        new_employee = {"user_id": None, "name": name, "is_admin": False}
        df = pd.concat([df, pd.DataFrame([new_employee])], ignore_index=True)
        df.to_excel(EMPLOYEES_FILE, index=False)
        await update.message.reply_text(f"Сотрудник {name} добавлен! Теперь нужно чтобы сотрудник отправил любое сообщение боту")
        
    except IndexError:
        await update.message.reply_text("Неверный формат команды!")

async def update_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.message.from_user.id):
        return
        
    try:
        old_name, new_name = update.message.text.split(" ", 2)[1:]
        df = pd.read_excel(EMPLOYEES_FILE)
        
        if old_name not in df["name"].values:
            await update.message.reply_text("Сотрудник не найден!")
            return
            
        df.loc[df["name"] == old_name, "name"] = new_name
        df.to_excel(EMPLOYEES_FILE, index=False)
        
        df_checkins = pd.read_excel(EXCEL_FILE)
        df_checkins.loc[df_checkins["name"] == old_name, "name"] = new_name
        df_checkins.to_excel(EXCEL_FILE, index=False)
        
        await update.message.reply_text("Имя успешно изменено!")
        
    except Exception as e:
        await update.message.reply_text("Ошибка формата команды!")

async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    df = pd.read_excel(EMPLOYEES_FILE)
    
    if user_id in df["user_id"].values:
        return
        
    mask = pd.isna(df["user_id"])
    if mask.any():
        df.loc[mask.idxmax(), "user_id"] = user_id
        df.to_excel(EMPLOYEES_FILE, index=False)
        await update.message.reply_text("Вы успешно зарегистрированы!")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIME_ZONE)
    df = pd.read_excel(EXCEL_FILE)
    today = now.strftime("%Y-%m-%d")
    employees = pd.read_excel(EMPLOYEES_FILE)

    if now.hour == 9 and now.minute == 30:
        for user_id in employees["user_id"]:
            if not df[(df["user_id"] == user_id) & (df["date"] == today)].empty:
                continue
            await context.bot.send_message(
                chat_id=user_id,
                text="⏰ Не забудьте отметить приход командой /checkin!"
            )

    elif now.hour == 18 and now.minute == 0:
        for _, row in df[df["checkout"].isna() & (df["date"] == today)].iterrows():
            await context.bot.send_message(
                chat_id=row["user_id"],
                text="⏰ Не забудьте отметить уход командой /checkout!"
            )

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("checkout", checkout))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("add_employee", add_employee))
    application.add_handler(CommandHandler("update_employee", update_employee))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.ALL, register_user))

    job_queue = application.job_queue
    job_queue.run_daily(
        send_reminder,
        time(hour=9, minute=30, tzinfo=TIME_ZONE),
        days=(0, 1, 2, 3, 4, 5, 6)
    )
    
    application.run_polling()

if __name__ == "__main__":
    main()