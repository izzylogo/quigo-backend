import sqlite3

import sqlite3

conn = sqlite3.connect('quizv2.db')
cursor = conn.cursor()

try:
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id VARCHAR,
        individual_id INTEGER,
        filename VARCHAR,
        content VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    print("Created documents table.")
except Exception as e:
    print(f"Error creating table: {e}")

conn.commit()
conn.close()
