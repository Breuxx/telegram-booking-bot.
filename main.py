import os
import logging
from datetime import datetime, time
import pytz
import pandas as pd

# Добавьте эти импорты
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
    """Инициализация файлов при первом запуске"""
    if not os.path.exists(EXCEL_FILE):
        pd.DataFrame(columns=["user_id", "name", "date", "checkin", "checkout"]).to_excel(EXCEL_FILE, index=False)
    if not os.path.exists(EMPLOYEES_FILE):
        pd.DataFrame(columns=["user_id", "name"]).to_excel(EMPLOYEES_FILE, index=False)

init_files()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    await update.message.reply_text("Добро пожаловать! Используйте команды:\n/checkin - отметить приход\n/checkout - отметить уход")

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Регистрация прихода сотрудника"""
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        df = pd.read_excel(EMPLOYEES_FILE)
        if user_id not in df["user_id"].values:
            await update.message.reply_text("Вы не зарегистрированы как сотрудник!")
            return

        name = df[df["user_id"] == user_id]["name"].values[0]
        checkins_df = pd.read_excel(EXCEL_FILE)
        
        if not checkins_df[(checkins_df["user_id"] == user_id) & (checkins_df["date"] == today)].empty:
            await update.message.reply_text("Вы уже отметили приход сегодня!")
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
        await update.message.reply_text("✅ Приход успешно зарегистрирован!")
        
    except Exception as e:
        logger.error(f"Ошибка при регистрации прихода: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка, попробуйте позже")

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Регистрация ухода сотрудника"""
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        checkins_df = pd.read_excel(EXCEL_FILE)
        record = checkins_df[(checkins_df["user_id"] == user_id) & (checkins_df["date"] == today)]
        
        if record.empty:
            await update.message.reply_text("❌ Сначала отметьте приход!")
            return
            
        if pd.notna(record.iloc[0]["checkout"]):
            await update.message.reply_text("❌ Вы уже отметили уход сегодня!")
            return
            
        idx = record.index[0]
        checkins_df.at[idx, "checkout"] = datetime.now().strftime("%H:%M:%S")
        checkins_df.to_excel(EXCEL_FILE, index=False)
        await update.message.reply_text("✅ Уход успешно зарегистрирован!")
        
    except Exception as e:
        logger.error(f"Ошибка при регистрации ухода: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка, попробуйте позже")

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Аутентификация администратора"""
    await update.message.reply_text("🔑 Введите пароль администратора:")
    context.user_data['expecting_password'] = True

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка пароля администратора"""
    if context.user_data.get('expecting_password'):
        entered_password = update.message.text.strip()
        if entered_password == ADMIN_PASSWORD:
            keyboard = [["📥 Скачать отчет"], ["👥 Добавить сотрудника"], ["✏️ Изменить имя"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("🔓 Доступ разрешен. Админ-панель:", reply_markup=reply_markup)
            context.user_data['admin_authorized'] = True
        else:
            await update.message.reply_text("❌ Неверный пароль!")
        context.user_data['expecting_password'] = False

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команд админ-панели"""
    if not context.user_data.get('admin_authorized'):
        await update.message.reply_text("⛔ Доступ запрещен!")
        return

    text = update.message.text
    if text == "📥 Скачать отчет":
        try:
            await update.message.reply_document(document=open(EXCEL_FILE, "rb"))
            logger.info("Отчет успешно отправлен администратору")
        except Exception as e:
            logger.error(f"Ошибка при отправке отчета: {str(e)}")
            await update.message.reply_text("⚠️ Не удалось отправить отчет")
            
    elif text == "👥 Добавить сотрудника":
        await update.message.reply_text("Введите команду в формате:\n/add_employee Имя_Фамилия")
        
    elif text == "✏️ Изменить имя":
        await update.message.reply_text("Введите команду в формате:\n/update_employee Старое_Имя Новое_Имя")

async def add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавление нового сотрудника"""
    try:
        # Проверка авторизации
        if not context.user_data.get('admin_authorized'):
            await update.message.reply_text("⛔ Доступ запрещен!")
            return

        # Проверка формата команды
        if len(context.args) < 1:
            await update.message.reply_text("⚠️ Используйте: /add_employee Имя_Фамилия")
            return

        name = ' '.join(context.args)
        df = pd.read_excel(EMPLOYEES_FILE)

        # Проверка существования сотрудника
        if name in df["name"].values:
            await update.message.reply_text("❌ Сотрудник уже существует!")
            return

        # Добавление сотрудника
        new_employee = {"user_id": None, "name": name}
        df = pd.concat([df, pd.DataFrame([new_employee])], ignore_index=True)
        df.to_excel(EMPLOYEES_FILE, index=False)
        
        await update.message.reply_text(f"✅ Сотрудник {name} добавлен! Попросите его написать боту.")
        logger.info(f"Добавлен сотрудник: {name}")

    except Exception as e:
        logger.error(f"Ошибка в add_employee: {str(e)}")
        await update.message.reply_text("⚠️ Ошибка при добавлении сотрудника. Проверьте логи.")

async def update_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменение имени сотрудника"""
    try:
        # Проверка авторизации
        if not context.user_data.get('admin_authorized'):
            await update.message.reply_text("⛔ Доступ запрещен!")
            return

        # Проверка формата команды
        if len(context.args) < 2:
            await update.message.reply_text("⚠️ Используйте: /update_employee Старое_Имя Новое_Имя")
            return

        old_name, new_name = context.args[0], ' '.join(context.args[1:])
        employees_df = pd.read_excel(EMPLOYEES_FILE)
        
        if old_name not in employees_df["name"].values:
            await update.message.reply_text("❌ Сотрудник не найден!")
            return
            
        employees_df.loc[employees_df["name"] == old_name, "name"] = new_name
        employees_df.to_excel(EMPLOYEES_FILE, index=False)
        
        checkins_df = pd.read_excel(EXCEL_FILE)
        checkins_df.loc[checkins_df["name"] == old_name, "name"] = new_name
        checkins_df.to_excel(EXCEL_FILE, index=False)
        
        await update.message.reply_text(f"✅ Имя успешно изменено: {old_name} → {new_name}")
        
    except Exception as e:
        logger.error(f"Ошибка при изменении имени: {str(e)}")
        await update.message.reply_text("⚠️ Ошибка при изменении имени. Проверьте логи.")

async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Регистрация нового пользователя"""
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
            await update.message.reply_text("🎉 Вы успешно зарегистрированы!")
    except Exception as e:
        logger.error(f"Ошибка регистрации: {str(e)}")

def main() -> None:
    """Запуск приложения"""
    application = Application.builder().token(TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("checkout", checkout))
    application.add_handler(CommandHandler("admin", admin_login))
    application.add_handler(CommandHandler("add_employee", add_employee))
    application.add_handler(CommandHandler("update_employee", update_employee))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_commands))
    application.add_handler(MessageHandler(filters.ALL, register_user))

    application.run_polling()

if __name__ == "__main__":
    main()