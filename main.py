import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

# Хранение данных в памяти
data = {
    "employees": {},  # {user_id: name}
    "checkins": []    # [{"user_id": ..., "name": ..., "date": ..., "checkin": ..., "checkout": ...}]
}

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Добро пожаловать!\n"
        "🟢 /checkin - Отметить приход\n"
        "🔴 /checkout - Отметить уход"
    )

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    if user_id not in data["employees"]:
        await update.message.reply_text("❌ Вы не зарегистрированы!")
        return

    name = data["employees"][user_id]
    for entry in data["checkins"]:
        if entry["user_id"] == user_id and entry["date"] == today:
            await update.message.reply_text("⚠️ Вы уже отметили приход!")
            return

    data["checkins"].append({
        "user_id": user_id,
        "name": name,
        "date": today,
        "checkin": datetime.now().strftime("%H:%M:%S"),
        "checkout": None
    })
    await update.message.reply_text("✅ Приход зарегистрирован!")

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    for entry in data["checkins"]:
        if entry["user_id"] == user_id and entry["date"] == today:
            if entry["checkout"] is not None:
                await update.message.reply_text("⚠️ Вы уже отметили уход!")
                return
            entry["checkout"] = datetime.now().strftime("%H:%M:%S")
            await update.message.reply_text("✅ Уход зарегистрирован!")
            return

    await update.message.reply_text("❌ Сначала отметьте приход!")

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

    if text == "📊 Скачать отчет":
        try:
            # Генерация отчета в текстовом формате
            report = "Отчет по приходам/уходам:\n"
            for entry in data["checkins"]:
                report += f"{entry['name']} ({entry['date']}): {entry['checkin']} - {entry['checkout'] or '❌'}\n"
            await update.message.reply_text(report)
        except Exception as e:
            logger.error(f"Ошибка при отправке отчета: {str(e)}")
            await update.message.reply_text("⚠️ Не удалось отправить отчет")

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
        new_name = text.strip()
        if new_name in data["employees"].values():
            await update.message.reply_text("⚠️ Сотрудник уже существует!")
        else:
            data["employees"][update.message.from_user.id] = new_name
            await update.message.reply_text(f"✅ Сотрудник {new_name} добавлен!")
        user_data.pop("adding_employee", None)
        await show_admin_menu(update)

    elif user_data.get("renaming"):
        try:
            old_name, new_name = map(str.strip, text.split(",", 1))
            for user_id, name in data["employees"].items():
                if name == old_name:
                    data["employees"][user_id] = new_name
                    for entry in data["checkins"]:
                        if entry["name"] == old_name:
                            entry["name"] = new_name
                    await update.message.reply_text(f"✅ Имя изменено: {old_name} → {new_name}")
                    break
            else:
                await update.message.reply_text("❌ Сотрудник не найден!")
        except Exception as e:
            logger.error(f"Ошибка при изменении имени: {str(e)}")
            await update.message.reply_text("⚠️ Неверный формат!")
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

    application.run_polling()

if __name__ == "__main__":
    main()