
import sqlite3

# Connect to the database
conn = sqlite3.connect('c:/Users/Admin/Desktop/quigo/backend/quizv2.db')
cursor = conn.cursor()

# Check if column exists
try:
    cursor.execute("SELECT openrouter_api_key FROM students LIMIT 1")
    print("Column already exists.")
except sqlite3.OperationalError:
    print("Adding column...")
    cursor.execute("ALTER TABLE students ADD COLUMN openrouter_api_key TEXT")
    conn.commit()
    print("Column added successfully.")

conn.close()
