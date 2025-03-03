async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрос пароля"""
    await update.message.reply_text("Введите пароль администратора:")
    context.user_data['expecting_password'] = True

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка пароля"""
    if context.user_data.get('expecting_password'):
        entered_password = update.message.text.strip()
        if entered_password == ADMIN_PASSWORD:
            keyboard = [["Скачать отчет"], ["Добавить сотрудника"], ["Изменить имя"]]
            reply_markup = ReplyKeyboardMarkup(
                keyboard, 
                resize_keyboard=True, 
                one_time_keyboard=True  # Добавлено
            )
            await update.message.reply_text("Доступ разрешен. Админ-панель:", reply_markup=reply_markup)
            context.user_data['admin_authorized'] = True
        else:
            await update.message.reply_text("Неверный пароль!")
        context.user_data['expecting_password'] = False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команд админ-панели"""
    if not context.user_data.get('admin_authorized'):
        await update.message.reply_text("Доступ запрещен!")
        return

    text = update.message.text
    if text == "Скачать отчет":
        await update.message.reply_document(document=open(EXCEL_FILE, "rb"))
    elif text == "Добавить сотрудника":
        await update.message.reply_text("Введите команду: /add_employee Имя")
    elif text == "Изменить имя":
        await update.message.reply_text("Введите команду: /update_employee СтароеИмя НовоеИмя")