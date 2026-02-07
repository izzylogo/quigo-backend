"""
Utility functions for generating student credentials.
"""

import secrets
import string
from datetime import datetime

def generate_student_id(school_id: int, student_count: int) -> str:
    """
    Generate a unique student ID.
    Format: STU-{YEAR}-{SCHOOL_ID}-{COUNT}
    Example: STU-2024-001-00123
    """
    year = datetime.now().year
    return f"STU-{year}-{school_id:03d}-{student_count:05d}"

def generate_password(length: int = 12) -> str:
    """
    Generate a secure random password.
    Contains uppercase, lowercase, digits, and special characters.
    """
    # Ensure at least one of each character type
    password_chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*")
    ]
    
    # Fill the rest with random characters
    all_chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password_chars += [secrets.choice(all_chars) for _ in range(length - 4)]
    
    # Shuffle to avoid predictable patterns
    secrets.SystemRandom().shuffle(password_chars)
    
    return ''.join(password_chars)

def generate_simple_password(length: int = 8) -> str:
    """
    Generate a simpler password (alphanumeric only) for easier distribution.
    Useful for younger students.
    """
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))
