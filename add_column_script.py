
import sqlite3

def add_password_column():
    conn = sqlite3.connect('quizv2.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN password TEXT")
        conn.commit()
        print("Successfully added 'password' column to 'students' table.")
    except sqlite3.OperationalError as e:
        print(f"Error: {e}")
        # Likely column already exists
    finally:
        conn.close()

if __name__ == "__main__":
    add_password_column()
