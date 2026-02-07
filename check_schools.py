from sqlalchemy.orm import Session
from database import SessionLocal
import models
import json

def check_schools():
    db = SessionLocal()
    try:
        schools = db.query(models.School).all()
        print(f"Total Schools Registered: {len(schools)}")
        print("-" * 50)
        for school in schools:
            print(f"ID: {school.id}")
            print(f"Name: {school.name}")
            print(f"Email: {school.email}")
            print(f"Country: {school.country}")
            print(f"Education System: {school.education_system}")
            print(f"Created At: {school.created_at}")
            
            # Count students and classrooms
            classrooms_count = len(school.classrooms)
            students_count = len(school.students)
            print(f"Classrooms: {classrooms_count}")
            print(f"Students: {students_count}")
            print("-" * 50)
    finally:
        db.close()

if __name__ == "__main__":
    check_schools()
