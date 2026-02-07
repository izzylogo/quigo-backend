import sqlite3
import os

db_path = 'quizv2.db'

def add_questions_column():
    if not os.path.exists(db_path):
        print(f"Database file {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Check if column exists first to avoid error if re-run
        cursor.execute("PRAGMA table_info(student_attempts)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'questions' in columns:
             print("'questions' column already exists.")
        else:
            cursor.execute("ALTER TABLE student_attempts ADD COLUMN questions JSON")
            conn.commit()
            print("Successfully added 'questions' column to 'student_attempts' table.")
    except sqlite3.OperationalError as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_questions_column()
