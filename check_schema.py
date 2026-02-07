import sqlite3

def check_schema():
    conn = sqlite3.connect("quizv2.db")
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(documents)")
        columns = cursor.fetchall()
        print("Columns in 'documents' table:")
        for col in columns:
            print(col)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_schema()
