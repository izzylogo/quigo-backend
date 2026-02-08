"""
Railway Database Seeding Script

This script connects to your Railway PostgreSQL database and seeds it with test data.

Usage:
1. Get your DATABASE_URL from Railway:
   - Go to your Postgres service
   - Click "Variables" tab
   - Copy the DATABASE_URL value

2. Run this script:
   set DATABASE_URL=<your-railway-database-url>
   python seed_railway.py

Or combine into one line:
   set DATABASE_URL=<url> && python seed_railway.py
"""

import os
import sys

# Check if DATABASE_URL is set
if not os.getenv("DATABASE_URL"):
    print("ERROR: DATABASE_URL environment variable is not set!")
    print("\nTo use this script:")
    print("1. Get your DATABASE_URL from Railway (Postgres service -> Variables)")
    print("2. Run: set DATABASE_URL=<your-url> && python seed_railway.py")
    sys.exit(1)

# Import after checking env var
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
import school_auth
import credential_generator
from education_systems import EDUCATION_SYSTEMS, get_education_levels
import json
from datetime import datetime

def seed_database():
    db = SessionLocal()
    try:
        # Create Tables if they don't exist
        print("Creating tables...")
        models.Base.metadata.create_all(bind=engine)
        print("✓ Tables created successfully\n")

        schools_to_seed = [
            {
                "name": "St. Andrews International",
                "email": "contact@standrews.com",
                "password": "password123",
                "country": "United Kingdom"
            },
            {
                "name": "Lagos Technical College",
                "email": "admin@lagostech.edu.ng",
                "password": "password123",
                "country": "Nigeria"
            },
            {
                "name": "Delhi Public School",
                "email": "info@dpsdelhi.in",
                "password": "password123",
                "country": "India"
            }
        ]

        print("--- CURRENT DATABASE STATE ---")
        existing_schools = db.query(models.School).all()
        for s in existing_schools:
            scount = db.query(models.Student).filter(models.Student.school_id == s.id).count()
            ccount = db.query(models.Classroom).filter(models.Classroom.school_id == s.id).count()
            print(f"School: {s.name} (ID: {s.id}, Email: {s.email}) - {ccount} Classrooms, {scount} Students")

        for school_data in schools_to_seed:
            # Get or create school
            school = db.query(models.School).filter(models.School.email == school_data["email"]).first()
            if not school:
                print(f"\n✓ Creating School: {school_data['name']}")
                password_hash = school_auth.hash_password(school_data["password"])
                levels = get_education_levels(school_data["country"])
                school = models.School(
                    name=school_data["name"],
                    email=school_data["email"],
                    password_hash=password_hash,
                    country=school_data["country"],
                    education_system=levels
                )
                db.add(school)
                db.commit()
                db.refresh(school)
                print(f"  -> Created with ID: {school.id}")
            else:
                print(f"\n→ School {school_data['name']} already exists (ID: {school.id})")

            # Classrooms
            levels = get_education_levels(school.country)
            classroom_names = [levels[0], levels[1]] if len(levels) > 1 else ["Class A", "Class B"]
            
            for class_name_base in classroom_names:
                class_name = f"{class_name_base} - 2026"
                classroom = db.query(models.Classroom).filter(
                    models.Classroom.school_id == school.id,
                    models.Classroom.name == class_name
                ).first()
                
                if not classroom:
                    print(f"  ✓ Creating Classroom: {class_name}")
                    classroom = models.Classroom(
                        school_id=school.id,
                        name=class_name,
                        grade_level=class_name_base
                    )
                    db.add(classroom)
                    db.commit()
                    db.refresh(classroom)
                else:
                    print(f"  → Classroom {class_name} already exists (ID: {classroom.id})")
                
                # Students
                current_students_count = db.query(models.Student).filter(models.Student.classroom_id == classroom.id).count()
                
                if current_students_count < 6:
                    print(f"    ✓ Adding {6 - current_students_count} students to {class_name}")
                    for i in range(current_students_count + 1, 7):
                        student_uuid = f"{school.id}_{classroom.id}_{i}"
                        student_email = f"student_{student_uuid}@quigo.test"
                        
                        total_in_school = db.query(models.Student).filter(models.Student.school_id == school.id).count()
                        student_id = credential_generator.generate_student_id(school.id, total_in_school + 1)
                        
                        while db.query(models.Student).filter(models.Student.student_id == student_id).first():
                            total_in_school += 1
                            student_id = credential_generator.generate_student_id(school.id, total_in_school + 1)

                        print(f"      → {student_id} ({student_email})")
                        
                        plain_password = credential_generator.generate_simple_password()
                        student = models.Student(
                            school_id=school.id,
                            classroom_id=classroom.id,
                            name=f"Student {i} - {class_name}",
                            email=student_email,
                            student_id=student_id,
                            password_hash=school_auth.hash_password(plain_password),
                            password=plain_password
                        )
                        db.add(student)
                        db.commit()
                    print(f"    ✓ Finished adding students")
                else:
                    print(f"    → Classroom {class_name} already has {current_students_count} students")

        print("\n" + "="*50)
        print("✓ SEEDING COMPLETED SUCCESSFULLY!")
        print("="*50)
        print("\nYou can now log in with:")
        for school in schools_to_seed:
            print(f"  • {school['email']} / {school['password']}")

    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
