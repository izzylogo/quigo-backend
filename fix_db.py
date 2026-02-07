from database import engine
from sqlalchemy import text

def fix_database():
    with engine.connect() as conn:
        try:
            # Check if column exists (SQLite specific check or just try adding)
            # Simplest for SQLite: try add column, ignore if exists
            print("Attempting to add difficulty column to quizzes table...")
            conn.execute(text("ALTER TABLE quizzes ADD COLUMN difficulty VARCHAR DEFAULT 'medium'"))
            print("Successfully added difficulty column.")
            conn.commit()
        except Exception as e:
            print(f"Column might already exist or error: {e}")

        try:
            print("Attempting to add question_type column to questions table...")
            conn.execute(text("ALTER TABLE questions ADD COLUMN question_type VARCHAR DEFAULT 'multiple_choice'"))
            print("Successfully added question_type column.")
            conn.commit()
        except Exception as e:
            print(f"Column might already exist or error: {e}")

        try:
            print("Attempting to add individual_id column to documents table...")
            conn.execute(text("ALTER TABLE documents ADD COLUMN individual_id INTEGER"))
            print("Successfully added individual_id column.")
            conn.commit()
        except Exception as e:
            print(f"Column might already exist or error: {e}")

if __name__ == "__main__":
    fix_database()
