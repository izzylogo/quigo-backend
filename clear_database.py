
import sqlite3

def clear_data():
    db_path = 'quizv2.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Disable foreign key checks to allow clearing tables in any order
    cursor.execute("PRAGMA foreign_keys = OFF;")
    
    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    for table_name in tables:
        table = table_name[0]
        if table != 'sqlite_sequence': # Don't delete sequence data if we want to reset IDs we should, but usually safer to leave unless explicit
            print(f"Clearing table: {table}")
            cursor.execute(f"DELETE FROM {table};")
            
    # Reset auto-increment counters if sqlite_sequence exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence';")
    if cursor.fetchone():
        cursor.execute("DELETE FROM sqlite_sequence;")
            
    conn.commit()
    
    # Re-enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.close()
    print("Database cleared successfully.")

if __name__ == "__main__":
    clear_data()
