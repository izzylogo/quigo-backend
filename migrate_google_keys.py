import sqlite3
import os

def migrate():
    db_path = "quizv2.db"
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables = ["users", "individuals", "students"]
    
    for table in tables:
        try:
            # Check if column exists
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [column[1] for column in cursor.fetchall()]
            
            if "google_api_key" not in columns:
                print(f"Adding google_api_key to {table}...")
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN google_api_key TEXT")
                conn.commit()
                print(f"Successfully added google_api_key to {table}.")
            else:
                print(f"google_api_key already exists in {table}.")
        except Exception as e:
            print(f"Error migrating {table}: {e}")

    conn.close()

if __name__ == "__main__":
    migrate()
