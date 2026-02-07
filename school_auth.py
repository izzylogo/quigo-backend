"""
Authentication module for school and student login.
Handles password hashing, JWT token generation, and verification.
"""

import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

# Security schemes
school_security = HTTPBearer()
student_security = HTTPBearer()

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict, token_type: str = "school") -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Dictionary containing user data (must include 'sub' for user ID)
        token_type: Type of token - 'school' or 'student'
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({
        "exp": expire,
        "type": token_type
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str, expected_type: str = None) -> dict:
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token string
        expected_type: Expected token type ('school' or 'student')
    
    Returns:
        Decoded token payload
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token type if specified
        if expected_type and payload.get("type") != expected_type:
            raise HTTPException(
                status_code=401, 
                detail=f"Invalid token type. Expected {expected_type}"
            )
        
        return payload
    except jwt.ExpiredSignatureError:
        print("DEBUG AUTH: Token has expired", flush=True)
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        print(f"DEBUG AUTH: Invalid token error: {e}", flush=True)
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        print(f"DEBUG AUTH: Unexpected error during decode: {e}", flush=True)
        raise HTTPException(status_code=401, detail="Authentication error during decoding")

from sqlalchemy.orm import Session
import database
import models

def get_current_school_id(
    credentials: HTTPAuthorizationCredentials = Security(school_security),
    db: Session = Depends(database.get_db)
) -> int:
    """
    Dependency to get the current authenticated school ID.
    Verifies that the school still exists in the database.
    """
    token = credentials.credentials
    print(f"DEBUG AUTH: Received school token: {token[:10]}...", flush=True)
    try:
        payload = decode_token(token, expected_type="school")
    except HTTPException as e:
        print(f"DEBUG AUTH: decoding failed: {e.detail}", flush=True)
        raise e
        
    school_id = payload.get("sub")
    
    print(f"DEBUG AUTH: Decoded school_id from token: {school_id} (type: {type(school_id)})", flush=True)
    
    if not school_id:
        raise HTTPException(status_code=401, detail="Invalid token payload: missing sub")
        
    # Verify school exists in DB - Explicitly cast to int
    try:
        sid_int = int(school_id)
        school = db.query(models.School).filter(models.School.id == sid_int).first()
    except (ValueError, TypeError):
        print(f"DEBUG AUTH: school_id {school_id} could not be cast to int", flush=True)
        raise HTTPException(status_code=401, detail="Invalid school ID format in token")

    if not school:
        print(f"DEBUG AUTH: School with ID {school_id} not found in database", flush=True)
        raise HTTPException(status_code=401, detail=f"School account {school_id} not found in DB")
    
    return sid_int

def get_current_student_id(
    credentials: HTTPAuthorizationCredentials = Security(student_security),
    db: Session = Depends(database.get_db)
) -> int:
    """
    Dependency to get the current authenticated student ID.
    Verifies that the student still exists in the database.
    """
    token = credentials.credentials
    print(f"DEBUG AUTH: Received student token: {token[:10]}...")
    payload = decode_token(token, expected_type="student")
    student_id = payload.get("sub")
    
    print(f"DEBUG AUTH: Decoded student_id from token: {student_id} (type: {type(student_id)})")
    
    if not student_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
        
    # Verify student exists in DB
    try:
        sid_int = int(student_id)
        student = db.query(models.Student).filter(models.Student.id == sid_int).first()
    except (ValueError, TypeError):
        print(f"DEBUG AUTH: student_id {student_id} could not be cast to int")
        raise HTTPException(status_code=401, detail="Invalid student ID format")

    if not student:
        print(f"DEBUG AUTH: Student with ID {student_id} not found in database")
        raise HTTPException(status_code=401, detail="Student account not found")
    
    return sid_int
