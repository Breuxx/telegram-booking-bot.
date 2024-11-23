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
    bot.register_next_step_handler(message, lambda msg: confirm_booking(msg, computers, name, surname))

@bot.message_handler(content_types=['contact'])
def confirm_booking(message, computers=None, name=None, surname=None):
    if message.contact is None or not message.contact.phone_number:
        bot.send_message(message.chat.id, "Ошибка получения номера телефона. Попробуйте снова.")
        return

    phone = message.contact.phone_number
    for comp in computers:
        bookings[f"{comp:02}"] = {"name": name, "surname": surname, "phone": phone}

    bot.send_message(
        message.chat.id,
        f"Компьютеры {', '.join(f'{x:02}' for x in computers)} успешно забронированы!"
    )

    bot.send_message(
        message.chat.id,
        f"Свободные компьютеры: {', '.join(f'{x:02}' for x in get_free_computers())}",
        reply_markup=telebot.types.ReplyKeyboardRemove()
    )

    # Уведомление администратору о бронировании
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")  # Укажите ID администратора в переменной окружения
    if admin_chat_id:
        bot.send_message(
            admin_chat_id,
            f"Клиент забронировал компьютеры: {', '.join(f'{x:02}' for x in computers)}\n"
            f"Имя: {name}\nФамилия: {surname}\nТелефон: {phone}"
        )

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
    markup.add("Показать бронирования", "Удалить бронирование", "Удалить все бронирования")
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)
    bot.register_next_step_handler(message, handle_admin_action)

def handle_admin_action(message):
    if message.text == "Показать бронирования":
        if not bookings:
            bot.send_message(message.chat.id, "Нет активных бронирований.")
        else:
            booking_list = "\n".join(
                [f"Компьютер {comp}: {data['name']} {data['surname']}, Телефон: {data['phone']}" for comp, data in bookings.items()]
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