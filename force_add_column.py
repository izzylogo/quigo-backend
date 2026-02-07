import sqlite3

def fix():
    db_path = "quizv2.db"
    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Attempting to add individual_id column...")
        cursor.execute("ALTER TABLE documents ADD COLUMN individual_id INTEGER")
        conn.commit()
        print("Success: individual_id added.")
    except Exception as e:
        print(f"Error adding individual_id: {e}")
        
    conn.close()

if __name__ == "__main__":
    fix()
