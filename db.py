import sqlite3

def init_db():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    # Таблица для отметок прихода/ухода
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            action TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Таблица для хранения графика работы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            user_id INTEGER PRIMARY KEY,
            start_time TEXT,
            end_time TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_action(user_id, username, full_name, action):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO attendance (user_id, username, full_name, action) VALUES (?, ?, ?, ?)',
                   (user_id, username, full_name, action))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM attendance WHERE user_id = ?', (user_id,))
    total = cursor.fetchone()[0]
    conn.close()
    return total

def get_daily_report(date_str):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, username, full_name, action, timestamp FROM attendance WHERE date(timestamp) = ?",
        (date_str,)
    )
    records = cursor.fetchall()
    conn.close()
    return records

def get_all_records():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, full_name, action, timestamp FROM attendance")
    records = cursor.fetchall()
    conn.close()
    return records

def set_schedule(user_id, start_time, end_time):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('REPLACE INTO schedules (user_id, start_time, end_time) VALUES (?, ?, ?)',
                   (user_id, start_time, end_time))
    conn.commit()
    conn.close()

def get_all_schedules():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, start_time, end_time FROM schedules')
    schedules = cursor.fetchall()
    conn.close()
    return schedules

def get_schedule(user_id):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('SELECT start_time, end_time FROM schedules WHERE user_id = ?', (user_id,))
    schedule = cursor.fetchone()
    conn.close()
    return schedule