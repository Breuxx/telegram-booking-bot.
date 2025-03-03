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