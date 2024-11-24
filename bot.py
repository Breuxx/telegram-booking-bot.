import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Получение токена из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Не найден токен бота. Убедитесь, что TELEGRAM_BOT_TOKEN установлен.")

bot = telebot.TeleBot(TOKEN)

# Хранилище данных о бронированиях
bookings = {}
admin_password = "moloko123"
admin_logged_in = False

# Функция для получения списка свободных компьютеров
def get_free_computers():
    booked_computers = {int(comp) for comp in bookings.keys()}
    all_computers = set(range(1, 43))
    return sorted(all_computers - booked_computers)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Добро пожаловать! Напишите /book, чтобы забронировать компьютеры."
    )
    bot.send_sticker(message.chat.id, "CAACAgIAAxkBAAIDc2TNcz9UvF1vV5k9lGuXJ-BcWWj9AAIpAQACVp29CnKRFH4cG0itLwQ")

@bot.message_handler(commands=['book'])
def book_computers(message):
    free_computers = get_free_computers()
    if not free_computers:
        bot.send_message(message.chat.id, "Извините, все компьютеры заняты.")
        return

    bot.send_message(
        message.chat.id,
        f"Свободные компьютеры: {', '.join(f'{x:02}' for x in free_computers)}\n"
        "Введите номера компьютеров для бронирования (например, 05-10):"
    )
    bot.register_next_step_handler(message, get_booking_details)

def get_booking_details(message):
    try:
        if '-' in message.text:
            start, end = map(int, message.text.split('-'))
            computers = range(start, end + 1)
        else:
            computers = [int(message.text)]

        free_computers = get_free_computers()
        if any(comp not in free_computers for comp in computers):
            bot.send_message(
                message.chat.id,
                "Некоторые компьютеры из выбранного диапазона уже заняты или недоступны. Попробуйте снова."
            )
            return book_computers(message)

        bot.send_message(message.chat.id, "Введите ваше имя:")
        bot.register_next_step_handler(message, lambda msg: get_name(msg, computers))
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова.")
        book_computers(message)

def get_name(message, computers):
    name = message.text
    bot.send_message(message.chat.id, "Введите вашу фамилию:")
    bot.register_next_step_handler(message, lambda msg: get_surname(msg, computers, name))

def get_surname(message, computers, name):
    surname = message.text
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    button_phone = KeyboardButton("Отправить номер телефона", request_contact=True)
    markup.add(button_phone)
    bot.send_message(
        message.chat.id,
        "Нажмите кнопку ниже, чтобы отправить ваш номер телефона:",
        reply_markup=markup,
    )
    bot.register_next_step_handler(message, lambda msg: get_time(msg, computers, name, surname))

def get_time(message, computers, name, surname):
    if message.contact is None or not message.contact.phone_number:
        bot.send_message(message.chat.id, "Ошибка получения номера телефона. Попробуйте снова.")
        return

    phone = message.contact.phone_number
    bot.send_message(
        message.chat.id,
        "Введите время бронирования в формате HH:MM (например, 14:30):",
        reply_markup=telebot.types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(
        message,
        lambda msg: confirm_booking(msg, computers, name, surname, phone)
    )

def confirm_booking(message, computers, name, surname, phone):
    time = message.text
    try:
        # Проверяем формат времени
        hours, minutes = map(int, time.split(':'))
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError

        for comp in computers:
            bookings[f"{comp:02}"] = {
                "name": name,
                "surname": surname,
                "phone": phone,
                "time": time
            }

        bot.send_message(
            message.chat.id,
            f"Компьютеры {', '.join(f'{x:02}' for x in computers)} успешно забронированы на {time}!"
        )
        bot.send_sticker(message.chat.id, "CAACAgIAAxkBAAIDdGTNc0QbD9_Fh_wdbWtRO02NiyksAAKwAQACVp29CoYzClxo62tLLwQ")

        # Уведомление администратору о бронировании
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")  # Укажите ID администратора в переменной окружения
        if admin_chat_id:
            bot.send_message(
                admin_chat_id,
                f"Клиент забронировал компьютеры: {', '.join(f'{x:02}' for x in computers)}\n"
                f"Имя: {name}\nФамилия: {surname}\nТелефон: {phone}\nВремя: {time}"
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "Неверный формат времени. Попробуйте снова."
        )
        get_time(message, computers, name, surname)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    bot.send_message(message.chat.id, "Введите пароль:")
    bot.register_next_step_handler(message, check_password)

def check_password(message):
    global admin_logged_in
    if message.text == admin_password:
        admin_logged_in = True
        bot.send_message(message.chat.id, "Добро пожаловать в админскую панель.")
        show_admin_menu(message)
    else:
        bot.send_message(message.chat.id, "Неверный пароль.")

def show_admin_menu(message):
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("Показать бронирования", "Удалить бронирование", "Удалить все бронирования", "Выйти из админ-панели")
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)
    bot.register_next_step_handler(message, handle_admin_action)

def handle_admin_action(message):
    global admin_logged_in
    if message.text == "Показать бронирования":
        if not bookings:
            bot.send_message(message.chat.id, "Нет активных бронирований.")
        else:
            booking_list = "\n".join(
                [f"Компьютер {comp}: {data['name']} {data['surname']}, Телефон: {data['phone']}, Время: {data['time']}" for comp, data in bookings.items()]
            )
            bot.send_message(message.chat.id, f"Список бронирований:\n{booking_list}")
        show_admin_menu(message)
    elif message.text == "Удалить бронирование":
        if not bookings:
            bot.send_message(message.chat.id, "Нет активных бронирований.")
            show_admin_menu(message)
            return

        markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        for comp in bookings.keys():
            markup.add(comp)
        bot.send_message(message.chat.id, "Введите номер компьютера для удаления бронирования:", reply_markup=markup)
        bot.register_next_step_handler(message, delete_booking)
    elif message.text == "Удалить все бронирования":
        bookings.clear()
        bot.send_message(message.chat.id, "Все бронирования удалены.")
        show_admin_menu(message)
    elif message.text == "Выйти из админ-панели":
        admin_logged_in = False
        bot.send_message(message.chat.id, "Вы вышли из админской панели.", reply_markup=telebot.types.ReplyKeyboardRemove())
    else:
        bot.send_message(message.chat.id, "Неверная команда.")
        show_admin_menu(message)

def delete_booking(message):
    computer = message.text
    if computer in bookings:
        del bookings[computer]
        bot.send_message(message.chat.id, f"Бронирование компьютера {computer} удалено.")
    else:
        bot.send_message(message.chat.id, "Неверный номер компьютера.")
    show_admin_menu(message)

bot.polling(none_stop=True)