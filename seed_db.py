from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
import school_auth
import credential_generator
from education_systems import EDUCATION_SYSTEMS, get_education_levels
import json
from datetime import datetime
import sys

def seed_database():
    db = SessionLocal()
    try:
        # Create Tables if they don't exist
        models.Base.metadata.create_all(bind=engine)

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
                print(f"\nCreating School: {school_data['name']}")
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
                print(f"\nSchool {school_data['name']} already exists (ID: {school.id})")

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
                    print(f"  Creating Classroom: {class_name}")
                    classroom = models.Classroom(
                        school_id=school.id,
                        name=class_name,
                        grade_level=class_name_base
                    )
                    db.add(classroom)
                    db.commit()
                    db.refresh(classroom)
                else:
                    print(f"  Classroom {class_name} already exists (ID: {classroom.id})")
                
                # Students
                current_students_count = db.query(models.Student).filter(models.Student.classroom_id == classroom.id).count()
                
                if current_students_count < 6:
                    print(f"    Adding {6 - current_students_count} students to {class_name}")
                    for i in range(current_students_count + 1, 7):
                        # Use a very specific email to avoid any chance of conflict
                        student_uuid = f"{school.id}_{classroom.id}_{i}"
                        student_email = f"student_{student_uuid}@quigo.test"
                        
                        # Generate unique student ID
                        # Let's count total students in school to get a sequence
                        total_in_school = db.query(models.Student).filter(models.Student.school_id == school.id).count()
                        student_id = credential_generator.generate_student_id(school.id, total_in_school + 1)
                        
                        # Check global uniqueness of student_id
                        while db.query(models.Student).filter(models.Student.student_id == student_id).first():
                            total_in_school += 1
                            student_id = credential_generator.generate_student_id(school.id, total_in_school + 1)

                        print(f"      Inserting student: {student_id} ({student_email})")
                        
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
                        db.commit() # Commit each student to be safe and catch errors early
                    print(f"    Finished adding students to {class_name}")
                else:
                    print(f"    Classroom {class_name} already has {current_students_count} students.")

        print("\nSeeding finished successfully.")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
