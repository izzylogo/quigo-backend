from sqlalchemy import Column, Integer, String, ForeignKey, JSON, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True) # Clerk User ID
    openrouter_api_key = Column(String, nullable=True)
    google_api_key = Column(String, nullable=True)
    
    quizzes = relationship("Quiz", back_populates="user")
    attempts = relationship("Attempt", back_populates="user")
    documents = relationship("Document", back_populates="user")

class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, index=True)
    quiz_format = Column(String) # 'objective', 'theory', 'fill_in_the_blank'
    num_questions = Column(Integer)
    difficulty = Column(String, default="medium")
    time_limit = Column(Integer, default=30) # Time limit in minutes
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(String, ForeignKey("users.id"))

    user = relationship("User", back_populates="quizzes")
    questions = relationship("Question", back_populates="quiz")
    attempts = relationship("Attempt", back_populates="quiz")

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    text = Column(String)
    options = Column(JSON) # Store list of options as JSON
    correct_answer = Column(String, nullable=True) # AI will evaluate, so this might be empty/unused initially
    question_type = Column(String, default="multiple_choice")

    quiz = relationship("Quiz", back_populates="questions")

class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    user_id = Column(String, ForeignKey("users.id"))
    score = Column(String) # Changed to String to support "X/Y" format or similar if needed, or keep Integer. User asked for "score": "x/y".
    feedback = Column(JSON) # Store detailed feedback from AI
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    quiz = relationship("Quiz", back_populates="attempts")
    user = relationship("User", back_populates="attempts")

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True) # Optional now
    individual_id = Column(Integer, ForeignKey("individuals.id"), nullable=True) # Added for Individual Portal
    filename = Column(String)
    content = Column(String) # Storing markdown content
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="documents")
    individual = relationship("Individual") # Simple relationship

# --- School Quiz Management Models ---

class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    country = Column(String, nullable=False)
    education_system = Column(JSON) # Store education levels as JSON array
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    classrooms = relationship("Classroom", back_populates="school", cascade="all, delete-orphan")
    students = relationship("Student", back_populates="school", cascade="all, delete-orphan")
    school_quizzes = relationship("SchoolQuiz", back_populates="school", cascade="all, delete-orphan")

class Individual(Base):
    __tablename__ = "individuals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    openrouter_api_key = Column(String, nullable=True)
    google_api_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Classroom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String, nullable=False) # e.g., "Primary 3A"
    grade_level = Column(String, nullable=False) # e.g., "Primary 3"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    school = relationship("School", back_populates="classrooms")
    students = relationship("Student", back_populates="classroom", cascade="all, delete-orphan")
    school_quizzes = relationship("SchoolQuiz", back_populates="classroom", cascade="all, delete-orphan")

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    student_id = Column(String, unique=True, nullable=False, index=True) # Unique student identifier
    password_hash = Column(String, nullable=False)
    password = Column(String, nullable=True) # Plain text password for display
    openrouter_api_key = Column(String, nullable=True)
    google_api_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    school = relationship("School", back_populates="students")
    classroom = relationship("Classroom", back_populates="students")
    student_attempts = relationship("StudentAttempt", back_populates="student", cascade="all, delete-orphan")

class SchoolQuiz(Base):
    __tablename__ = "school_quizzes"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id"), nullable=False)
    topic = Column(String, nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True) # Optional document reference
    additional_notes = Column(String, nullable=True) # Extra instructions from IT personnel
    ai_model = Column(String, nullable=False) # Selected AI model
    quiz_format = Column(String, nullable=False) # 'objective', 'theory', 'fill_in_the_blank'
    num_questions = Column(Integer, nullable=False)
    difficulty = Column(String, default="medium")
    time_limit = Column(Integer, default=30) # Time limit in minutes
    questions = Column(JSON, nullable=True) # Store generated questions as JSON (Nullable for template quizzes)
    created_by = Column(String, nullable=True) # IT personnel name/identifier
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    school = relationship("School", back_populates="school_quizzes")
    classroom = relationship("Classroom", back_populates="school_quizzes")
    document = relationship("Document")
    student_attempts = relationship("StudentAttempt", back_populates="school_quiz", cascade="all, delete-orphan")

class StudentAttempt(Base):
    __tablename__ = "student_attempts"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    school_quiz_id = Column(Integer, ForeignKey("school_quizzes.id"), nullable=False)
    score = Column(String, nullable=True) # Format: "X/Y" (Null if not submitted)
    answers = Column(JSON, nullable=True) # Store student answers (Null initially)
    questions = Column(JSON, nullable=False) # Store generated questions for this attempt
    feedback = Column(JSON, nullable=True) # Store AI feedback
    completed_at = Column(DateTime, nullable=True)

    student = relationship("Student", back_populates="student_attempts")
    school_quiz = relationship("SchoolQuiz", back_populates="student_attempts")
