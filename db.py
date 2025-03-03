import sqlite3

def init_db():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_action(user_id, username, action):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO attendance (user_id, username, action) VALUES (?, ?, ?)',
                   (user_id, username, action))
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
    cursor.execute("SELECT user_id, username, action, timestamp FROM attendance WHERE date(timestamp) = ?", (date_str,))
    records = cursor.fetchall()
    conn.close()
    return records

def get_all_records():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, action, timestamp FROM attendance")
    records = cursor.fetchall()
    conn.close()
    return records