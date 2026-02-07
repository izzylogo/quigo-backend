"""
Authentication module for individual users.
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

# Security scheme
individual_security = HTTPBearer()

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-individual-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 30  # 30 days

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_individual_access_token(data: dict) -> str:
    """Create a JWT access token for individual users."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({
        "exp": expire,
        "type": "individual"
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token type
        if payload.get("type") != "individual":
            raise HTTPException(
                status_code=401, 
                detail="Invalid token type. Expected individual"
            )
        
        return payload
    except jwt.ExpiredSignatureError:
        print("DEBUG AUTH: Individual token has expired", flush=True)
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        print(f"DEBUG AUTH: Invalid individual token error: {e}", flush=True)
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        print(f"DEBUG AUTH: Unexpected error during decode: {e}", flush=True)
        raise HTTPException(status_code=401, detail="Authentication error")

from sqlalchemy.orm import Session
import database
import models

def get_current_individual_id(
    credentials: HTTPAuthorizationCredentials = Security(individual_security),
    db: Session = Depends(database.get_db)
) -> int:
    """
    Dependency to get the current authenticated individual ID.
    Verifies that the individual still exists in the database.
    """
    token = credentials.credentials
    print(f"DEBUG AUTH: Received individual token: {token[:10]}...", flush=True)
    
    try:
        payload = decode_token(token)
    except HTTPException as e:
        print(f"DEBUG AUTH: Individual token decoding failed: {e.detail}", flush=True)
        raise e
    
    individual_id = payload.get("sub")
    print(f"DEBUG AUTH: Decoded individual_id from token: {individual_id} (type: {type(individual_id)})", flush=True)
    
    if not individual_id:
        raise HTTPException(status_code=401, detail="Invalid token payload: missing sub")
    
    # Verify individual exists in DB
    try:
        iid_int = int(individual_id)
        individual = db.query(models.Individual).filter(models.Individual.id == iid_int).first()
    except (ValueError, TypeError):
        print(f"DEBUG AUTH: individual_id {individual_id} could not be cast to int", flush=True)
        raise HTTPException(status_code=401, detail="Invalid individual ID format in token")
    
    if not individual:
        print(f"DEBUG AUTH: Individual with ID {individual_id} not found in database", flush=True)
        raise HTTPException(status_code=401, detail=f"Individual account {individual_id} not found in DB")
    
    return iid_int
