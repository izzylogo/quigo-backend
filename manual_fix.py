import sqlite3

import sqlite3

conn = sqlite3.connect('quizv2.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE documents ADD COLUMN individual_id INTEGER")
    print("Added individual_id column.")
except Exception as e:
    print(f"Error adding individual_id: {e}")

conn.commit()
conn.close()
