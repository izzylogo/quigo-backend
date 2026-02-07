from pydantic import BaseModel
from typing import Optional, List, Any

# ... (existing imports)

class StudentQuizGenerateRequest(BaseModel):
    api_key: str

class StudentSubmitQuizRequest(BaseModel):
    answers: dict[str, str] # Question ID -> Answer Option (A, B, C, D)
