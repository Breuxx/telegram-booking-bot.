import os
import logging
from datetime import datetime
import pytz
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройки
TOKEN = os.environ.get("TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
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
        pd.DataFrame(columns=["user_id", "name"]).to_excel(EMPLOYEES_FILE, index=False)

init_files()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Добро пожаловать!\n"
        "🟢 /checkin - Отметить приход\n"
        "🔴 /checkout - Отметить уход"
    )

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        employees_df = pd.read_excel(EMPLOYEES_FILE)
        if user_id not in employees_df["user_id"].values:
            await update.message.reply_text("❌ Вы не зарегистрированы!")
            return

        name = employees_df[employees_df["user_id"] == user_id]["name"].values[0]
        checkins_df = pd.read_excel(EXCEL_FILE)
        
        if not checkins_df[(checkins_df["user_id"] == user_id) & (checkins_df["date"] == today)].empty:
            await update.message.reply_text("⚠️ Вы уже отметили приход!")
            return
            
        new_row = {
            "user_id": user_id,
            "name": name,
            "date": today,
            "checkin": datetime.now().strftime("%H:%M:%S"),
            "checkout": None
        }
        
        checkins_df = pd.concat([checkins_df, pd.DataFrame([new_row])], ignore_index=True)
        checkins_df.to_excel(EXCEL_FILE, index=False)
        await update.message.reply_text("✅ Приход зарегистрирован!")
        
    except Exception as e:
        logger.error(f"Checkin error: {str(e)}")
        await update.message.reply_text("🚨 Ошибка! Попробуйте позже.")

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        checkins_df = pd.read_excel(EXCEL_FILE)
        record = checkins_df[(checkins_df["user_id"] == user_id) & (checkins_df["date"] == today)]
        
        if record.empty:
            await update.message.reply_text("❌ Сначала отметьте приход!")
            return
            
        if pd.notna(record.iloc[0]["checkout"]):
            await update.message.reply_text("⚠️ Вы уже отметили уход!")
            return
            
        idx = record.index[0]
        checkins_df.at[idx, "checkout"] = datetime.now().strftime("%H:%M:%S")
        checkins_df.to_excel(EXCEL_FILE, index=False)
        await update.message.reply_text("✅ Уход зарегистрирован!")
        
    except Exception as e:
        logger.error(f"Checkout error: {str(e)}")
        await update.message.reply_text("🚨 Ошибка! Попробуйте позже.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        ["📊 Скачать отчет"],
        ["👤 Добавить сотрудника", "✏️ Изменить имя"],
        ["🔐 Выйти из админки"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("🔑 Введите пароль админа:", reply_markup=reply_markup)
    context.user_data["awaiting_password"] = True

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    user_data = context.user_data
    
    if user_data.get("awaiting_password"):
        if text == ADMIN_PASSWORD:
            user_data["admin_mode"] = True
            user_data["awaiting_password"] = False
            await show_admin_menu(update)
        else:
            await update.message.reply_text("❌ Неверный пароль!")
            user_data.clear()
        return

    if not user_data.get("admin_mode"):
        return

    if text == "📊 Скачать отчет":
        try:
            await update.message.reply_document(document=open(EXCEL_FILE, "rb"))
        except Exception as e:
            logger.error(f"Report error: {str(e)}")
            await update.message.reply_text("🚨 Не удалось отправить отчет!")
    
    elif text == "👤 Добавить сотрудника":
        await update.message.reply_text("Введите имя нового сотрудника:")
        user_data["adding_employee"] = True
    
    elif text == "✏️ Изменить имя":
        await update.message.reply_text("Введите старое и новое имя через запятую:")
        user_data["renaming"] = True
    
    elif text == "🔐 Выйти из админки":
        user_data.clear()
        await update.message.reply_text("🔒 Сессия админа завершена.", reply_markup=ReplyKeyboardRemove())

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    user_data = context.user_data
    
    if user_data.get("adding_employee"):
        try:
            new_name = text.strip()
            df = pd.read_excel(EMPLOYEES_FILE)
            
            if new_name in df["name"].values:
                await update.message.reply_text("⚠️ Сотрудник уже существует!")
                return
                
            new_employee = {"user_id": None, "name": new_name}
            df = pd.concat([df, pd.DataFrame([new_employee])], ignore_index=True)
            df.to_excel(EMPLOYEES_FILE, index=False)
            await update.message.reply_text(f"✅ Сотрудник {new_name} добавлен!")
            
        except Exception as e:
            logger.error(f"Add employee error: {str(e)}")
            await update.message.reply_text("🚨 Ошибка добавления!")
        finally:
            user_data.pop("adding_employee", None)
            await show_admin_menu(update)
    
    elif user_data.get("renaming"):
        try:
            old_name, new_name = map(str.strip, text.split(",", 1))
            employees_df = pd.read_excel(EMPLOYEES_FILE)
            
            employees_df.loc[employees_df["name"] == old_name, "name"] = new_name
            employees_df.to_excel(EMPLOYEES_FILE, index=False)
            
            checkins_df = pd.read_excel(EXCEL_FILE)
            checkins_df.loc[checkins_df["name"] == old_name, "name"] = new_name
            checkins_df.to_excel(EXCEL_FILE, index=False)
            
            await update.message.reply_text(f"✅ Имя изменено: {old_name} → {new_name}")
            
        except Exception as e:
            logger.error(f"Rename error: {str(e)}")
            await update.message.reply_text("🚨 Ошибка! Формат: Старое имя, Новое имя")
        finally:
            user_data.pop("renaming", None)
            await show_admin_menu(update)

async def show_admin_menu(update: Update) -> None:
    keyboard = [
        ["📊 Скачать отчет"],
        ["👤 Добавить сотрудника", "✏️ Изменить имя"],
        ["🔐 Выйти из админки"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👑 Админ-панель:", reply_markup=reply_markup)

async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    try:
        df = pd.read_excel(EMPLOYEES_FILE)
        if user_id in df["user_id"].values:
            return
            
        mask = pd.isna(df["user_id"])
        if mask.any():
            idx = mask.idxmax()
            df.at[idx, "user_id"] = user_id
            df.to_excel(EMPLOYEES_FILE, index=False)
            await update.message.reply_text("🎉 Вы зарегистрированы!")
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("checkout", checkout))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda update, context: handle_admin_actions(update, context) if (
            update.message.text in ["📊 Скачать отчет", "👤 Добавить сотрудника", "✏️ Изменить имя", "🔐 Выйти из админки"]
        ) else handle_admin_input(update, context)
    ))
    
    application.add_handler(MessageHandler(filters.ALL, register_user))

    application.run_polling()

if __name__ == "__main__":
    main()