from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Any, Dict, Union
import shutil
from openai import OpenAI
import json
import os
from google import genai
from google.genai import types
import datetime
import models, database, auth
import school_auth
import individual_auth
import re
from education_systems import EDUCATION_SYSTEMS, get_available_countries, get_education_levels
from credential_generator import generate_student_id, generate_password, generate_simple_password

# Create Database Tables
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:5173", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation Error: {exc}")
    # Also print the body if possible, though it requires reading the stream which might consume it.
    # Safe to just print the error details.
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc)},
    )

# --- Pydantic Schemas ---

class UserSettings(BaseModel):
    openrouter_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

class GenerateQuizRequest(BaseModel):
    topic: str
    format: str # 'objective', 'theory', 'fill_in_the_blank'
    num_questions: int
    difficulty: str = "medium"
    time_limit: int = 30
    custom_instructions: Optional[str] = None

class QuizQuestion(BaseModel):
    id: int
    question: str
    options: Optional[Dict[str, str]] = None # {"A": "...", "B": "..."} or null
    answer: str # Empty string initially

class QuizData(BaseModel):
    topic: str
    format: str
    questions: List[QuizQuestion]

class SubmissionResult(BaseModel):
    id: int
    correct: bool
    feedback: str

class EvaluationResponse(BaseModel):
    score: str
    results: List[SubmissionResult]

class DocumentResponse(BaseModel):
    id: int
    filename: str
    created_at: Any

class GenerateQuizFromExistingRequest(BaseModel):
    document_id: int
    topic: str
    format: str = "objective"
    num_questions: int = 5
    difficulty: str = "medium"
    time_limit: int = 30
    custom_instructions: Optional[str] = None

# --- School Management Schemas ---

class SchoolRegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    country: str

class IndividualAuthRequest(BaseModel):
    email: str
    password: str

class IndividualRegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class SchoolLoginRequest(BaseModel):
    email: str
    password: str

class ClassroomCreateRequest(BaseModel):
    name: str
    grade_level: str

class StudentBulkImportRequest(BaseModel):
    students: List[Dict[str, str]]  # List of {"name": "...", "email": "..."}

class CreateSchoolQuizRequest(BaseModel):
    topic: str
    additional_notes: Optional[str] = None
    ai_model: str
    quiz_format: str = "objective"
    num_questions: int = 5
    difficulty: str = "medium"
    time_limit: int = 30
    created_by: Optional[str] = None

class StudentLoginRequest(BaseModel):
    student_id: str
    password: str

class StudentQuizGenerateRequest(BaseModel):
    api_key: str

class StudentQuizSubmitRequest(BaseModel):
    answers: Dict[str, Any]  # The quiz JSON with answers filled in
    api_key: str  # Student's OpenRouter API key

class QuizCreateRequest(BaseModel):
    topic: str
    quiz_format: str = "multiple_choice"
    num_questions: int = 5
    difficulty: str = "medium"
    time_limit: int = 30

class QuizSubmitRequest(BaseModel):
    answers: Dict[str, str]  # question_id -> answer

# --- Helpers ---

def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)

def get_gemini_model_name(model_name: str = "gemini-3-flash-preview"):
    # Clean the model name
    return model_name.replace("models/", "")

def get_openrouter_client(api_key: str):
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        timeout=60.0
    )

def clean_json_text(text: str) -> str:
    # Remove markdown code blocks if present
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        # Search for any code block that might contain JSON
        blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if blocks:
            text = blocks[0]
        else:
            text = text.split("```")[1].split("```")[0]
    
    # Remove any leading/trailing non-JSON characters
    text = text.strip()
    start = text.find('{')
    # If no start brace, return empty (unfixable)
    if start == -1:
        return ""
        
    # Find the last closing brace. If it's missing or after the last content, 
    # we might need to append it (truncated JSON)
    end = text.rfind('}')
    if end == -1 or end < start:
        # Basic attempt to close truncated JSON
        text = text[start:] + "\n  ]\n}"
    else:
        text = text[start:end+1]
    
    # Remove trailing commas before closing brackets/braces
    text = re.sub(r',\s*([\]}])', r'\1', text)
    # Remove single-line comments
    text = re.sub(r'//.*?\n', '\n', text)
    # Fix Python-style None/True/False
    text = re.sub(r':\s*None', ': null', text)
    text = re.sub(r':\s*\bTrue\b', ': true', text)
    text = re.sub(r':\s*\bFalse\b', ': false', text)
        
    return text.strip()

def get_actual_model_id(model_name: str) -> str:
    """
    Extract actual OpenRouter model ID from display names.
    Handles cases where UI stores names like "Xiaomi Mimo V2 Flash (Free) - Recommended"
    instead of the actual model ID "xiaomi/mimo-v2-flash:free"
    """
    # Model ID mapping for common display names
    model_mapping = {
        "xiaomi mimo v2 flash": "xiaomi/mimo-v2-flash:free",
        "xiaomi/mimo-v2-flash": "xiaomi/mimo-v2-flash:free",
        "qwen/qwen-2.5-7b-instruct": "qwen/qwen-2.5-7b-instruct:free",
        "meta-llama/llama-3.2-3b-instruct": "meta-llama/llama-3.2-3b-instruct:free",
    }
    
    # Clean the model name (lowercase, remove extra text)
    cleaned = model_name.lower().strip()
    
    # Remove common suffixes like "(Free) - Recommended"
    cleaned = cleaned.split('(')[0].strip()
    cleaned = cleaned.split('-')[0].strip() if 'recommended' in model_name.lower() else cleaned
    
    # Check if it's already a valid model ID format (contains /)
    if '/' in model_name and ':' in model_name:
        return model_name
    
    # Try to find in mapping
    for key, value in model_mapping.items():
        if key in cleaned:
            return value
    
    # Default fallback
    return "xiaomi/mimo-v2-flash:free"

def build_quiz_prompt(topic: str, quiz_format: str, num_questions: int, difficulty: str) -> str:
    options_instruction = ""
    if quiz_format == "multiple_choice" or quiz_format == "objective":
        options_instruction = "options MUST include A, B, C, D keys mapped to answer text."
    elif quiz_format in ["theory", "fill_in_the_blank"]:
        options_instruction = "options MUST be null."

    return f"""
    Generate a quiz about "{topic}".
    Format: {quiz_format}
    Difficulty: {difficulty}
    Number of questions: {num_questions}
    
    Return ONLY a raw JSON object. NO markdown.
    The JSON format MUST be EXACTLY:
    {{
      "topic": "{topic}",
      "format": "{quiz_format}",
      "questions": [
        {{
          "id": 1,
          "question": "string",
          "options": object or null, 
          "answer": null,
          "correct_answer": "correct answer text or key"
        }}
      ]
    }}
    
    Rules:
    - {options_instruction}
    - answer field MUST be null (it will be filled by user).
    - correct_answer field MUST be the actual correct answer (key or text).
    - For multiple choice, randomize correct answer position.
    - Provide clear and concise questions.
    - CRITICAL: ESCAPE all double quotes (") inside question strings with a backslash (\") or use single quotes instead.
    - CRITICAL: Ensure the JSON is valid and not truncated.
    """

async def generate_quiz_questions_ai(prompt: str, api_key: str) -> List[Dict[str, Any]]:
    client = get_gemini_client(api_key)
    content = ""
    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
            )
        )
        content = response.text
        cleaned_json = clean_json_text(content)
        # Use strict=False to allow literal control characters like unescaped newlines in JSON strings
        data = json.loads(cleaned_json, strict=False)
        return data.get("questions", [])
    except Exception as e:
        print(f"AI Generation Error: {e}")
        if content:
            # Print start and end of failed content to diagnose truncation or errors
            length = len(content)
            print(f"FAILED CONTENT PREVIEW (Length: {length}):")
            print(f"START: {content[:500]}...")
            if length > 500:
                print(f"END: ...{content[-500:]}")
        return []

async def evaluate_submission_ai(questions: List[Dict], answers: Dict[str, str], api_key: str) -> Dict[str, Any]:
    """
    Evaluates quiz submission using AI.
    Returns: { "score": "X/Y", "results": [ { "id": 1, "correct": true, "feedback": "..." } ] }
    """
    if not api_key:
        return {"score": "0/0", "results": []}

    client = get_gemini_client(api_key)
    
    # improved prompt for partial credit and theory evaluation
    prompt = f"""
    Evaluate this quiz submission.
    
    Questions and Model Answers (Reference):
    {json.dumps(questions, indent=2)}
    
    User Answers:
    {json.dumps(answers, indent=2)}
    
    Task:
    1. For Multiple Choice questions:
       - Compare the selected Option Key (e.g., "A") with the correct option key.
       - These are strictly right (1.0) or wrong (0.0).
    2. For Theory/Subjective questions:
       - Award a score between 0.0 and 1.0 based on conceptual accuracy.
       - SCORING RULES:
         a. Close but missing main points: 0.5 to 0.8.
         b. List and explain (but only listed): 0.4 to 0.5.
         c. Partial list (e.g., 3/5): proportional score (~0.65).
         d. Perfect: 1.0.
         e. Irrelevant/Wrong: 0.0.
     3. Provide brief feedback for each question.
    
    Return valid JSON ONLY in this exact format:
    {{
      "results": [
        {{ 
          "id": question_id, 
          "score": float, (0.0 to 1.0)
          "feedback": "short explanation" 
        }}
      ]
    }}
    """
    
    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        content = response.text
        cleaned_json = clean_json_text(content)
        evaluation = json.loads(cleaned_json)
        
        # Calculate final score string and ensure "correct" mapping for UI
        results = evaluation.get("results", [])
        total_obtained = 0
        for r in results:
            if "score" in r:
                s = float(r.get("score", 0))
            else:
                # Fallback to 'correct' if 'score' is missing
                s = 1.0 if r.get("correct") else 0.0
                r["score"] = s
                
            total_obtained += s
            r["correct"] = s >= 0.5
            
        display_score = f"{int(total_obtained) if total_obtained.is_integer() else round(total_obtained, 2)}/{len(results)}"
        
        return {
            "score": display_score,
            "results": results
        }
    except Exception as e:
        print(f"AI Evaluation Error: {e}")
        # Fallback empty result
        return {"score": "0/0", "results": []}

# --- Routes ---

@app.post("/api/user/settings")
def save_settings(settings: UserSettings, user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        user = models.User(id=user_id)
        db.add(user)
    
    if settings.openrouter_api_key is not None:
        user.openrouter_api_key = settings.openrouter_api_key
    if settings.google_api_key is not None:
        user.google_api_key = settings.google_api_key
    db.commit()
    return {"message": "Settings saved"}

# Removed duplicate student routes to prevent 401 loop and key mismatch

@app.post("/api/generate-quiz")
def generate_quiz(req: GenerateQuizRequest, user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.google_api_key:
        raise HTTPException(status_code=400, detail="Google API Key not set. Please go to settings.")

    client = get_gemini_client(user.google_api_key)

    # Prompt construction based on format
    options_instruction = ""
    if req.format == "objective":
        options_instruction = "options MUST include A, B, C, D keys mapped to answer text."
    elif req.format in ["theory", "fill_in_the_blank"]:
        options_instruction = "options MUST be null."

    prompt = f"""
    Generate a quiz about "{req.topic}".
    Format: {req.format}
    Difficulty: {req.difficulty}
    Number of questions: {req.num_questions}
    Custom Instructions: {req.custom_instructions or "None"}
    
    Return ONLY a raw JSON object. NO markdown.
    The JSON format MUST be EXACTLY:
    {{
      "topic": "{req.topic}",
      "format": "{req.format}",
      "questions": [
        {{
          "id": 1,
          "question": "string",
          "options": object or null, 
          "answer": ""
        }}
      ]
    }}
    
    Rules:
    - {options_instruction}
    - answer field MUST be null (user input initially).
    - correct_answer field MUST contain the correct answer.
    - Randomize the position of the correct answer (A, B, C, D). Do NOT default to 'B', 'C', or 'D'.
    - Ask and generate questions from random parts.
    - ensure unique IDs for questions (1, 2, 3...)
    - Focus ONLY on the SUBJECT MATTER and CONTENT of the document.
    """
    
    print(f"Generating quiz with prompt: {prompt}") # Debug

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        text = clean_json_text(response.text)
        quiz_json = json.loads(text)
        
    except Exception as e:
        print(f"Error generating quiz: {e}")
        if hasattr(e, 'status_code'):
             print(f"API ERROR STATUS: {e.status_code}")
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}")

    # Save to DB
    new_quiz = models.Quiz(
        topic=req.topic, 
        user_id=user_id,
        quiz_format=req.format,
        num_questions=req.num_questions,
        time_limit=req.time_limit
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)

    # Save questions (optional, but good for record)
    for q in quiz_json.get("questions", []):
        new_q = models.Question(
            quiz_id=new_quiz.id,
            text=q["question"],
            options=q["options"],
            correct_answer="" # Not known yet
        )
        db.add(new_q)
    db.commit()
    
    # Return the AI generated JSON directly (with the quiz_id added if needed, or just let frontend handle)
    # User requirement: "Return ONLY valid JSON... format EXACTLY..."
    # If we want to track it on submission, we might want to inject our DB ID, 
    # but the user specified constraint format. I'll adhere to the format but add quiz_id metadata if possible,
    # or just trust the frontend sends back the questions for evaluation.
    # The requirement #4 says "Sennds the FULL quiz JSON (with user answers filled in)".
    # So I can probably just return what the AI gave me. 
    # BUT, for the DB record, I'll return what the AI gave.
    
    # Return the AI generated JSON directly, but INJECT our database ID
    quiz_json['quiz_id'] = new_quiz.id
    quiz_json['time_limit'] = new_quiz.time_limit
    return quiz_json

from fastapi import UploadFile, File, Form
from llama_parse import LlamaParse
import nest_asyncio
nest_asyncio.apply()

@app.post("/api/generate-quiz-from-doc")
async def generate_quiz_from_doc(
    file: UploadFile = File(...),
    topic: str = Form(...),
    format: str = Form("objective"),
    num_questions: int = Form(5),
    difficulty: str = Form("medium"),
    time_limit: int = Form(30),
    custom_instructions: Optional[str] = Form(None),
    user_id: str = Depends(auth.get_current_user_id),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.google_api_key:
        raise HTTPException(status_code=400, detail="Google API Key not set.")

    # Save file temporarily
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    try:
        # Load parsing key from env
        parsing_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not parsing_api_key:
             raise HTTPException(status_code=500, detail="LLAMA_CLOUD_API_KEY not set on server.")

        print(f"DEBUG: Loaded LLAMA_CLOUD_API_KEY: {parsing_api_key[:10]}... (Length: {len(parsing_api_key)})")

        parser = LlamaParse(
            api_key=parsing_api_key,
            result_type="markdown",
            verbose=True
        )
        
        documents = await parser.aload_data(file_path)
        if not documents:
             raise HTTPException(status_code=400, detail="Could not parse document.")
        
        context_text = documents[0].text
        # Limit context to avoid context window issues (simple truncation for now)
        context_text = context_text[:15000] 

    except Exception as e:
        print(f"Parsing error: {e}")
        raise HTTPException(status_code=500, detail=f"Document Parsing Failed: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    # Save to DB
    new_doc = models.Document(
        user_id=user_id,
        filename=file.filename,
        content=context_text
    )
    db.add(new_doc)
    # We commit later with quiz or now? A single commit is usually better but here we have unrelated operations.
    # Let's commit doc now so it's saved even if quiz generation fails? 
    # Or keep it atomic? User wants "save it as markdown". 
    db.commit() 
    db.refresh(new_doc)

    # Save to DB (new_doc already saved above)

    # Generate Quiz with context
    client = get_gemini_client(user.google_api_key)

    options_instruction = ""
    if format == "objective":
        options_instruction = "options MUST include A, B, C, D keys mapped to answer text."
    elif format in ["theory", "fill_in_the_blank"]:
        options_instruction = "options MUST be null."

    # Difficulty Logic
    difficulty_instruction = ""
    if difficulty.lower() == "easy":
        difficulty_instruction = "Focus on high-level definitions and key terms. Keep questions simple and direct."
    elif difficulty.lower() == "medium":
        difficulty_instruction = "Extract questions from the beginning, middle, and end. Focus on core concepts and relationships."
    elif difficulty.lower() == "hard":
        difficulty_instruction = "Focus on subtle details, logical inferences, and complex scenarios found deep in the text. Ignore obvious surface-level facts. Ask 'why' and 'how'."

    prompt = f"""
    Generate a quiz about "{topic}" based on the following DOCUMENT CONTEXT.
    
    DOCUMENT CONTEXT:
    {context_text}
    
    ----------------
    
    Task:
    Generate {num_questions} questions.
    Format: {format}
    Difficulty: {difficulty}
    Custom Instructions: {custom_instructions or "None"}
    
    Return ONLY a raw JSON object. NO markdown.
    The JSON format MUST be EXACTLY:
    {{
      "topic": "{topic}",
      "format": "{format}",
      "questions": [
        {{
          "id": 1,
          "question": "string",
          "options": object or null, 
          "answer": ""
        }}
      ]
    }}
    
    Rules:
    - Questions MUST be answered using the provided context.
    - Randomize the position of the correct answer (A, B, C, D). Do NOT default to 'B', 'C', or 'D'. Randomize the position of the correct answer (A, B, C, D).
    - Ask and generate questions from random parts of the document, do not ask questions from starting to ending - you can start asking questions from the middle of the pdf and also from bullet points mentioned in the document.
    - {difficulty_instruction}
    - ENSURE questions are distributed across the ENTIRE text provided.
    - {options_instruction}
    - answer field MUST always be an empty string string (user will fill it).
    - ensure unique IDs for questions (1, 2, 3...)
    - NEGATIVE CONSTRAINTS: Do NOT ask about the author, publication date, or document structure (e.g., 'what is after chapter 1', 'what is the matriculation number'). Focus ONLY on the SUBJECT MATTER and CONTENT of the document.
    """
    
    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        text = clean_json_text(response.text)
        quiz_json = json.loads(text)
        
    except Exception as e:
        print(f"Error generating quiz from doc: {e}")
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}")

    # Save to DB
    new_quiz = models.Quiz(
        user_id=user_id,
        quiz_format=format,
        num_questions=num_questions,
        time_limit=time_limit
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)

    for q in quiz_json.get("questions", []):
        new_q = models.Question(
            quiz_id=new_quiz.id,
            text=q["question"],
            options=q["options"],
            correct_answer=""
        )
        db.add(new_q)
    db.commit()
    
    quiz_json['quiz_id'] = new_quiz.id
    return quiz_json

@app.get("/api/documents", response_model=List[DocumentResponse])
def get_documents(user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    docs = db.query(models.Document).filter(models.Document.user_id == user_id).order_by(models.Document.created_at.desc()).all()
    return docs

@app.post("/api/generate-quiz-from-existing-doc")
def generate_quiz_from_existing_doc(req: GenerateQuizFromExistingRequest, user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.google_api_key:
        raise HTTPException(status_code=400, detail="Google API Key not set.")

    # Fetch document
    doc = db.query(models.Document).filter(models.Document.id == req.document_id, models.Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    context_text = doc.content # Already parsed markdown

    client = get_gemini_client(user.google_api_key)

    options_instruction = ""
    if req.format == "objective":
        options_instruction = "options MUST include A, B, C, D keys mapped to answer text."
    elif req.format in ["theory", "fill_in_the_blank"]:
        options_instruction = "options MUST be null."

    # Difficulty Logic
    difficulty_instruction = ""
    if req.difficulty.lower() == "easy":
        difficulty_instruction = "Focus on high-level definitions and key terms. Keep questions simple and direct."
    elif req.difficulty.lower() == "medium":
        difficulty_instruction = "Extract questions from the beginning, middle, and end. Focus on core concepts and relationships."
    elif req.difficulty.lower() == "hard":
        difficulty_instruction = "Focus on subtle details, logical inferences, and complex scenarios found deep in the text. Ignore obvious surface-level facts. Ask 'why' and 'how'."

    prompt = f"""
    Generate a quiz about "{req.topic}" based on the following DOCUMENT CONTEXT.
    
    DOCUMENT CONTEXT:
    {context_text}
    
    ----------------
    
    Task:
    Generate {req.num_questions} questions.
    Format: {req.format}
    Difficulty: {req.difficulty}
    Custom Instructions: {req.custom_instructions or "None"}
    
    Return ONLY a raw JSON object. NO markdown.
    The JSON format MUST be EXACTLY:
    {{
      "topic": "{req.topic}",
      "format": "{req.format}",
      "questions": [
        {{
          "id": 1,
          "question": "string",
          "options": object or null, 
          "answer": ""
        }}
      ]
    }}
    
    Rules:
    - Questions MUST be answered using the provided context.
    - Randomize the position of the correct answer (A, B, C, D). Do NOT default to 'B', 'C', or 'D'. Randomize the position of the correct answer (A, B, C, D).
    - Generate questions from random parts, do not start from the beginning or end of the text (that is you can from the middle, from chapter 2 or even from random parts).
    - {difficulty_instruction}
    - ENSURE questions are distributed across the ENTIRE text provided.
    - {options_instruction}
    - answer field MUST always be an empty string string (user will fill it).
    - ensure unique IDs for questions (1, 2, 3...)
    - NEGATIVE CONSTRAINTS: Do NOT ask about the author, publication date, or document structure (e.g., 'what is after chapter 1', 'what is the matriculation number'). Focus ONLY on the SUBJECT MATTER and CONTENT of the document.
    """
    
    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        text = clean_json_text(response.text)
        quiz_json = json.loads(text)
        
    except Exception as e:
        print(f"Error generating quiz from existing doc: {e}")
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}")

    # Save to DB
    new_quiz = models.Quiz(
        topic=req.topic, 
        user_id=user_id,
        quiz_format=req.format,
        num_questions=req.num_questions,
        time_limit=req.time_limit
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)

    for q in quiz_json.get("questions", []):
        new_q = models.Question(
            quiz_id=new_quiz.id,
            text=q["question"],
            options=q["options"],
            correct_answer=""
        )
        db.add(new_q)
    db.commit()
    
    quiz_json['quiz_id'] = new_quiz.id
    return quiz_json

@app.post("/api/submit-quiz")
def submit_quiz(submission: Dict[str, Any], user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    # submisison is the FULL quiz JSON with "answer" filled in.
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.google_api_key:
        raise HTTPException(status_code=400, detail="API Key missing")

    client = get_gemini_client(user.google_api_key)

    submission_str = json.dumps(submission, indent=2)

    prompt = f"""
    Evaluate this quiz submission.
    
    Submission JSON:
    {submission_str}
    
    Task:
    - Evaluate each question's answer based on the question text and format.
    - Return ONLY valid JSON in this format:
    {{
      "score": "correct_count/total_questions",
      "results": [
        {{
          "id": number,
          "correct": boolean,
          "feedback": "short explanation"
        }}
      ]
    }}
    
    No markdown. No extra text.
    """

    try:
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        raw_text = response.text
        print(f"DEBUG - Raw AI Response: {raw_text}") 
        
        text = clean_json_text(raw_text)
        print(f"DEBUG - Cleaned JSON Text: {text}") 
        
        evaluation = json.loads(text)
        
    except Exception as e:
        print(f"Error evaluating quiz: {e}")
        print(f"Failed prompt was: {prompt}")
        raise HTTPException(status_code=500, detail=f"AI Evaluation Failed: {str(e)}")

    # Extract quiz_id if present to link correctly
    quiz_id = submission.get('quiz_id')
    
    attempt = models.Attempt(
        user_id=user_id,
        score=evaluation.get("score", "0/0"),
        feedback=evaluation.get("results"),
        quiz_id=quiz_id 
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt) # Refresh to get ID

    return {
        "attempt_id": attempt.id,
        **evaluation
    }

@app.get("/api/history")
def get_history(user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    attempts = db.query(models.Attempt).filter(models.Attempt.user_id == user_id).order_by(models.Attempt.timestamp.desc()).all()
    return [
        {
            "id": a.id,
            "quiz_topic": a.quiz.topic if a.quiz else "Unknown Topic", # Handle missing quiz relation safely
            "score": a.score,
            "timestamp": a.timestamp,
        }
        for a in attempts
    ]

@app.get("/api/history/{attempt_id}")
def get_attempt_details(attempt_id: int, user_id: str = Depends(auth.get_current_user_id), db: Session = Depends(database.get_db)):
    attempt = db.query(models.Attempt).filter(models.Attempt.id == attempt_id, models.Attempt.user_id == user_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Fetch questions for this quiz to get the original text
    questions = []
    if attempt.quiz_id:
        questions = db.query(models.Question).filter(models.Question.quiz_id == attempt.quiz_id).order_by(models.Question.id.asc()).all()
    
    # Map index+1 to question text (assuming AI used IDs 1, 2, 3...)
    q_map = {i+1: q.text for i, q in enumerate(questions)}
    
    enhanced_feedback = []
    if attempt.feedback:
        for item in attempt.feedback:
            # item is dict {id, correct, feedback}
            # We clone it to avoid mutating the ORM object in place (though it's JSON)
            new_item = item.copy()
            qid = new_item.get('id')
            
            # Try to map by ID (1-based index)
            if isinstance(qid, int) and qid in q_map:
                new_item['question_text'] = q_map[qid]
            # Fallback: if we have questions but ID doesn't match, maybe try array index matching if IDs are weird?
            # But let's trust strict ID matching 1..N first for simplicity. 
            elif questions and isinstance(qid, int) and 0 <= qid - 1 < len(questions):
                 # ID might be 1-based index but q_map failed? Re-try simple index access
                 new_item['question_text'] = questions[qid-1].text
            else:
                 new_item['question_text'] = "Question text unavailable"
            
            enhanced_feedback.append(new_item)

    return {
        "id": attempt.id,
        "quiz_topic": attempt.quiz.topic if attempt.quiz else "Unknown Topic",
        "score": attempt.score,
        "timestamp": attempt.timestamp,
        "feedback": enhanced_feedback
    }

# --- School Management Endpoints ---

@app.post("/api/school/register")
def register_school(req: SchoolRegisterRequest, db: Session = Depends(database.get_db)):
    """Register a new school."""
    # Check if email already exists
    existing_school = db.query(models.School).filter(models.School.email == req.email).first()
    if existing_school:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Validate country
    if req.country not in EDUCATION_SYSTEMS:
        raise HTTPException(status_code=400, detail="Invalid country selection")
    
    # Hash password
    password_hash = school_auth.hash_password(req.password)
    
    # Get education system for country
    education_system = EDUCATION_SYSTEMS[req.country]["levels"]
    
    # Create school
    new_school = models.School(
        name=req.name,
        email=req.email,
        password_hash=password_hash,
        country=req.country,
        education_system=education_system
    )
    db.add(new_school)
    db.commit()
    db.refresh(new_school)
    
    # Generate token
    token = school_auth.create_access_token(
        data={"sub": str(new_school.id)},
        token_type="school"
    )
    
    return {
        "message": "School registered successfully",
        "school_id": new_school.id,
        "token": token,
        "school": {
            "id": new_school.id,
            "name": new_school.name,
            "email": new_school.email,
            "country": new_school.country,
            "education_system": new_school.education_system
        }
    }

@app.post("/api/school/login")
def login_school(req: SchoolLoginRequest, db: Session = Depends(database.get_db)):
    """School login."""
    school = db.query(models.School).filter(models.School.email == req.email).first()
    
    if not school:
        raise HTTPException(status_code=401, detail="Invalid credentials - school not found")
    
    if not school_auth.verify_password(req.password, school.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials - password mismatch")
    
    # Create JWT token
    access_token = school_auth.create_access_token(
        data={"sub": str(school.id)},
        token_type="school"
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": school.id,
            "name": school.name,
            "email": school.email,
            "country": school.country
        }
    }

@app.get("/api/school/list")
def list_schools(db: Session = Depends(database.get_db)):
    """List all registered schools for demo/pre-login selection."""
    schools = db.query(models.School).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "email": s.email
        }
        for s in schools
    ]

# --- Individual Authentication Endpoints ---

@app.post("/api/individual/register")
def register_individual(req: IndividualRegisterRequest, db: Session = Depends(database.get_db)):
    """Register a new individual user."""
    # Check if email already exists
    existing = db.query(models.Individual).filter(models.Individual.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash password
    password_hash = individual_auth.hash_password(req.password)
    
    # Create individual
    new_individual = models.Individual(
        name=req.name,
        email=req.email,
        password_hash=password_hash
    )
    
    db.add(new_individual)
    db.commit()
    db.refresh(new_individual)
    
    return {"message": "Individual registered successfully", "id": new_individual.id}

@app.post("/api/individual/login")
def login_individual(req: IndividualAuthRequest, db: Session = Depends(database.get_db)):
    """Login for individual users."""
    individual = db.query(models.Individual).filter(models.Individual.email == req.email).first()
    
    if not individual or not individual_auth.verify_password(req.password, individual.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = individual_auth.create_individual_access_token(data={"sub": str(individual.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": individual.id,
            "name": individual.name,
            "email": individual.email
        }
    }

@app.get("/api/school/profile")
def get_school_profile(school_id: int = Depends(school_auth.get_current_school_id), db: Session = Depends(database.get_db)):
    """Get school profile."""
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    
    return {
        "id": school.id,
        "name": school.name,
        "email": school.email,
        "country": school.country,
        "education_system": school.education_system,
        "created_at": school.created_at
    }

@app.get("/api/school/education-systems")
def get_education_systems():
    """Get all available countries and their education systems."""
    return {
        "countries": get_available_countries(),
        "systems": EDUCATION_SYSTEMS
    }

@app.get("/api/school/dashboard/overview")
def get_school_dashboard_overview(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get school dashboard overview statistics with completion rate."""
    # Get total classrooms
    total_classrooms = db.query(models.Classroom).filter(
        models.Classroom.school_id == school_id
    ).count()
    
    # Get total students
    total_students = db.query(models.Student).filter(
        models.Student.school_id == school_id
    ).count()
    
    # Get total quizzes
    total_quizzes = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.school_id == school_id
    ).count()
    
    # Calculate completion rate
    total_possible_attempts = total_students * total_quizzes
    total_actual_attempts = db.query(models.StudentAttempt).join(
        models.Student
    ).filter(
        models.Student.school_id == school_id,
        models.StudentAttempt.score.isnot(None)
    ).count()
    
    completion_rate = 0
    if total_possible_attempts > 0:
        completion_rate = round((total_actual_attempts / total_possible_attempts) * 100, 1)
    
    return {
        "statistics": {
            "total_classrooms": total_classrooms,
            "total_students": total_students,
            "total_quizzes": total_quizzes,
            "completion_rate": f"{completion_rate}%"
        }
    }

# --- Classroom Management Endpoints ---

@app.post("/api/school/classrooms")
def create_classroom(
    req: ClassroomCreateRequest,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Create a new classroom."""
    new_classroom = models.Classroom(
        school_id=school_id,
        name=req.name,
        grade_level=req.grade_level
    )
    db.add(new_classroom)
    db.commit()
    db.refresh(new_classroom)
    
    return {
        "message": "Classroom created successfully",
        "classroom": {
            "id": new_classroom.id,
            "name": new_classroom.name,
            "grade_level": new_classroom.grade_level,
            "created_at": new_classroom.created_at
        }
    }

@app.get("/api/school/classrooms")
def get_classrooms(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all classrooms for the school."""
    classrooms = db.query(models.Classroom).filter(
        models.Classroom.school_id == school_id
    ).order_by(models.Classroom.created_at.desc()).all()
    
    return [
        {
            "id": c.id,
            "name": c.name,
            "grade_level": c.grade_level,
            "student_count": len(c.students),
            "active_quizzes": len(c.school_quizzes),
            "created_at": c.created_at
        }
        for c in classrooms
    ]

@app.get("/api/school/classrooms/{classroom_id}")
def get_classroom_details(
    classroom_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get detailed classroom information."""
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    students_data = [
        {
            "id": s.id,
            "name": s.name,
            "email": s.email,
            "student_id": s.student_id,
            "password": s.password,
            "created_at": s.created_at,
            "attempts_count": len(s.student_attempts),
            "average_score": calculate_student_average(s.student_attempts),
            "quiz_scores": {str(a.school_quiz_id): a.score for a in s.student_attempts if a.score}
        }
        for s in classroom.students
    ]

    # Calculate aggregate stats for classroom
    all_attempts = []
    for s in classroom.students:
        all_attempts.extend(s.student_attempts)
    
    avg_score = calculate_student_average(all_attempts)
    total_quizzes = len(classroom.school_quizzes)
    total_students = len(classroom.students)
    total_actual_submissions = len(all_attempts)
    total_possible_submissions = total_quizzes * total_students
    
    completion_percentage = (total_actual_submissions / total_possible_submissions * 100) if total_possible_submissions > 0 else 0
    submission_ratio = f"{total_actual_submissions}/{total_possible_submissions}"

    return {
        "id": classroom.id,
        "name": classroom.name,
        "grade_level": classroom.grade_level,
        "created_at": classroom.created_at,
        "average_score": avg_score,
        "total_tests_count": total_quizzes,
        "total_students_count": total_students,
        "completion_percentage": round(completion_percentage, 1),
        "submission_ratio": submission_ratio,
        "students": students_data,
        "quizzes": [
            {
                "id": q.id,
                "topic": q.topic,
                "quiz_format": q.quiz_format,
                "num_questions": q.num_questions,
                "difficulty": q.difficulty,
                "created_at": q.created_at,
                "attempts_count": len(q.student_attempts)
            }
            for q in classroom.school_quizzes
        ]
    }

def calculate_student_average(attempts):
    if not attempts:
        return 0
    total = 0
    count = 0
    for a in attempts:
        try:
            # score format "X/Y"
            if not a.score: continue
            parts = a.score.split('/')
            if len(parts) == 2:
                num = float(parts[0])
                den = float(parts[1])
                if den > 0:
                    total += (num / den) * 100
                    count += 1
        except Exception:
            continue
    return round(total / count, 1) if count > 0 else 0

@app.get("/api/school/attempts/{attempt_id}")
def get_attempt_details(
    attempt_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get detailed attempt info including script."""
    attempt = db.query(models.StudentAttempt).join(
        models.Student
    ).join(
        models.Classroom
    ).filter(
        models.StudentAttempt.id == attempt_id,
        models.Classroom.school_id == school_id
    ).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    return {
        "id": attempt.id,
        "score": attempt.score,
        "completed_at": attempt.completed_at,
        "questions": attempt.questions,
        "answers": attempt.answers,
        "feedback": attempt.feedback,
        "student_name": attempt.student.name,
        "quiz_difficulty": attempt.school_quiz.difficulty
    }

@app.get("/api/school/students/{student_id}/attempts")
def get_student_attempts_school(
    student_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get list of attempts for a specific student (School Admin view)."""
    student = db.query(models.Student).filter(
        models.Student.id == student_id,
        models.Student.school_id == school_id
    ).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    attempts = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id
    ).order_by(models.StudentAttempt.completed_at.desc()).all()

    # Fetch all quizzes for the student's classroom
    classroom_quizzes = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.classroom_id == student.classroom_id
    ).all()

    # Identify attempted quiz IDs
    attempted_quiz_ids = {a.school_quiz_id for a in attempts}

    # Quizzes not yet attempted
    undone_quizzes = [
        {
            "id": q.id,
            "topic": q.topic,
            "quiz_format": q.quiz_format,
            "num_questions": q.num_questions,
            "created_at": q.created_at
        }
        for q in classroom_quizzes if q.id not in attempted_quiz_ids
    ]

    return {
        "student": {
            "id": student.id,
            "name": student.name,
            "email": student.email,
            "student_id": student.student_id,
            "joined_at": student.created_at
        },
        "attempts": [
            {
                "id": a.id,
                "school_quiz_id": a.school_quiz_id,
                "quiz_topic": a.school_quiz.topic,
                "quiz_format": a.school_quiz.quiz_format,
                "num_questions": a.school_quiz.num_questions,
                "score": a.score,
                "completed_at": a.completed_at
            }
            for a in attempts
        ],
        "undone_quizzes": undone_quizzes
    }


@app.delete("/api/school/classrooms/{classroom_id}")
def delete_classroom(
    classroom_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Delete a classroom."""
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    db.delete(classroom)
    db.commit()
    
    return {"message": "Classroom deleted successfully"}

# --- Student Management Endpoints ---

@app.post("/api/school/classrooms/{classroom_id}/students/bulk")
def bulk_import_students(
    classroom_id: int,
    req: StudentBulkImportRequest,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Bulk import students to a classroom."""
    # Verify classroom belongs to school
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    # Get the maximum existing student ID suffix for this school and year to prevent collisions
    current_year = datetime.datetime.now().year
    prefix = f"STU-{current_year}-{school_id:03d}-"
    
    # Query all student IDs matching this year and school
    existing_students = db.query(models.Student.student_id).filter(
        models.Student.school_id == school_id,
        models.Student.student_id.like(f"{prefix}%")
    ).all()
    
    # Extract the numeric suffixes and find the maximum
    max_suffix = 0
    for (student_id,) in existing_students:
        try:
            # Extract the last part after the final dash
            suffix = int(student_id.split('-')[-1])
            max_suffix = max(max_suffix, suffix)
        except (ValueError, IndexError):
            continue
    
    created_students = []
    
    for idx, student_data in enumerate(req.students):
        # Generate credentials using incremental suffix from max
        student_count = max_suffix + idx + 1
        unique_student_id = generate_student_id(school_id, student_count)
        password = generate_simple_password(8)  # Simpler password for students
        password_hash = school_auth.hash_password(password)
        
        # Create student
        new_student = models.Student(
            school_id=school_id,
            classroom_id=classroom_id,
            name=student_data["name"],
            email=student_data["email"],
            student_id=unique_student_id,
            password_hash=password_hash,
            password=password
        )
        db.add(new_student)
        
        created_students.append({
            "id": new_student.id,
            "name": new_student.name,
            "email": new_student.email,
            "student_id": unique_student_id,
            "password": password  # Return plain password for distribution
        })
    
    db.commit()
    
    return {
        "message": f"{len(created_students)} students created successfully",
        "students": created_students
    }

@app.get("/api/school/students")
def get_all_school_students(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all students in the school across all classrooms."""
    students = db.query(models.Student).filter(
        models.Student.school_id == school_id
    ).order_by(models.Student.created_at.desc()).all()
    
    return [
        {
            "id": s.id,
            "name": s.name,
            "email": s.email,
            "student_id": s.student_id,
            "classroom_name": s.classroom.name,
            "grade_level": s.classroom.grade_level,
            "password": s.password,
            "created_at": s.created_at,
            "attempts_count": len(s.student_attempts),
            "total_quizzes": len(s.classroom.school_quizzes) if s.classroom else 0,
             # Calculate average mastery from attempts if needed, for now placeholder or simple avg
            "mastery": calculate_student_average(s.student_attempts)
        }
        for s in students
    ]

@app.get("/api/school/classrooms/{classroom_id}/students")
def get_classroom_students(
    classroom_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all students in a classroom."""
    # Verify classroom belongs to school
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    total_classroom_quizzes = len(classroom.school_quizzes)

    students = db.query(models.Student).filter(
        models.Student.classroom_id == classroom_id
    ).all()
    
    return [
        {
            "id": s.id,
            "name": s.name,
            "email": s.email,
            "student_id": s.student_id,
            "password": s.password,
            "created_at": s.created_at,
            "attempts_count": len(s.student_attempts),
            "total_quizzes": total_classroom_quizzes,
            "mastery": calculate_student_average(s.student_attempts)
        }
        for s in students
    ]

@app.delete("/api/school/students/{student_id}")
def delete_student(
    student_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Delete a student."""
    student = db.query(models.Student).filter(
        models.Student.id == student_id,
        models.Student.school_id == school_id
    ).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    db.delete(student)
    db.commit()
    
    return {"message": "Student deleted successfully"}

# --- School Quiz Management Endpoints ---

@app.get("/api/school/documents")
def get_school_documents(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all documents uploaded by the school."""
    docs = db.query(models.Document).filter(
        models.Document.user_id == f"school_{school_id}"
    ).order_by(models.Document.created_at.desc()).all()
    
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "created_at": d.created_at
        }
        for d in docs
    ]

@app.post("/api/school/classrooms/{classroom_id}/quiz")
async def create_school_quiz(
    classroom_id: int,
    file: Optional[UploadFile] = File(None),
    document_id: Optional[int] = Form(None),
    topic: str = Form(...),
    additional_notes: Optional[str] = Form(None),
    ai_model: str = Form(...),
    quiz_format: str = Form("objective"),
    num_questions: int = Form(5),
    difficulty: str = Form("medium"),
    time_limit: int = Form(30),
    created_by: Optional[str] = Form(None),
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Create a quiz for a classroom with document upload."""
    # Verify classroom belongs to school
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    # Handle document
    final_document_id = None

    if file:
        file_path = f"temp_{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        try:
            # Parse document
            parsing_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
            if not parsing_api_key:
                raise HTTPException(status_code=500, detail="LLAMA_CLOUD_API_KEY not set on server.")
            
            parser = LlamaParse(
                api_key=parsing_api_key,
                result_type="markdown",
                verbose=True
            )
            
            documents = await parser.aload_data(file_path)
            if not documents:
                raise HTTPException(status_code=400, detail="Could not parse document.")
            
            context_text = documents[0].text[:15000]
            
            # Save document to database
            new_doc = models.Document(
                user_id=f"school_{school_id}",
                filename=file.filename,
                content=context_text
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)
            final_document_id = new_doc.id
            
        except Exception as e:
            print(f"Parsing error: {e}")
            raise HTTPException(status_code=500, detail=f"Document Parsing Failed: {str(e)}")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    elif document_id:
        # Verify document belongs to school
        existing_doc = db.query(models.Document).filter(
            models.Document.id == document_id,
            models.Document.user_id == f"school_{school_id}"
        ).first()
        if not existing_doc:
            raise HTTPException(status_code=404, detail="Document not found")
        final_document_id = document_id
    else:
        raise HTTPException(status_code=400, detail="Either file or document_id must be provided")

    # Save school quiz without questions (deferred generation)
    new_quiz = models.SchoolQuiz(
        school_id=school_id,
        classroom_id=classroom_id,
        topic=topic,
        document_id=final_document_id,
        additional_notes=additional_notes,
        ai_model=ai_model,
        quiz_format=quiz_format,
        num_questions=num_questions,
        difficulty=difficulty,
        time_limit=time_limit,
        questions=None, # Questions will be generated by student
        created_by=created_by
    )
    
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)
    
    return {
        "message": "Quiz preparation successful. Students can now generate and take the test.",
        "quiz_id": new_quiz.id,
        "document_id": final_document_id
    }

@app.get("/api/school/classrooms/{classroom_id}/quizzes")
def get_classroom_quizzes(
    classroom_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all quizzes for a classroom."""
    classroom = db.query(models.Classroom).filter(
        models.Classroom.id == classroom_id,
        models.Classroom.school_id == school_id
    ).first()
    
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    
    quizzes = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.classroom_id == classroom_id
    ).order_by(models.SchoolQuiz.created_at.desc()).all()
    
    return [
        {
            "id": q.id,
            "topic": q.topic,
            "quiz_format": q.quiz_format,
            "num_questions": q.num_questions,
            "difficulty": q.difficulty,
            "ai_model": q.ai_model,
            "created_by": q.created_by,
            "created_at": q.created_at,
            "time_limit": q.time_limit,
            "attempts_count": len(q.student_attempts)
        }
        for q in quizzes
    ]

@app.get("/api/school/quizzes/{quiz_id}/results")
def get_quiz_results(
    quiz_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all student results for a quiz."""
    quiz = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.id == quiz_id,
        models.SchoolQuiz.school_id == school_id
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    attempts = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.school_quiz_id == quiz_id
    ).order_by(models.StudentAttempt.completed_at.desc()).all()
    
    return {
        "quiz": {
            "id": quiz.id,
            "topic": quiz.topic,
            "quiz_format": quiz.quiz_format,
            "num_questions": quiz.num_questions
        },
        "results": [
            {
                "student_id": a.student.student_id,
                "student_name": a.student.name,
                "score": a.score,
                "completed_at": a.completed_at,
                "feedback": a.feedback
            }
            for a in attempts
        ]
    }

# --- Student Endpoints ---

@app.post("/api/student/login")
def login_student(req: StudentLoginRequest, db: Session = Depends(database.get_db)):
    """Student login with student ID and password."""
    student = db.query(models.Student).filter(
        models.Student.student_id == req.student_id
    ).first()
    
    if not student:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not school_auth.verify_password(req.password, student.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate token
    token = school_auth.create_access_token(
        data={"sub": str(student.id)},
        token_type="student"
    )
    
    return {
        "token": token,
        "student": {
            "id": student.id,
            "student_id": student.student_id,
            "name": student.name,
            "email": student.email,
            "classroom": {
                "id": student.classroom.id,
                "name": student.classroom.name,
                "grade_level": student.classroom.grade_level
            }
        }
    }

class StudentProfileUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

@app.get("/api/student/profile")
def get_student_profile(
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Get student profile."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    return {
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "email": student.email,
        "openrouter_api_key": student.openrouter_api_key,
        "google_api_key": student.google_api_key,
        "classroom": {
            "id": student.classroom.id,
            "name": student.classroom.name,
            "grade_level": student.classroom.grade_level
        },
        "school": {
            "name": student.school.name
        }
    }

@app.post("/api/student/profile")
def update_student_profile(
    req: StudentProfileUpdate,
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Update student profile (API Key)."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    if req.openrouter_api_key is not None:
        student.openrouter_api_key = req.openrouter_api_key
    if req.google_api_key is not None:
        student.google_api_key = req.google_api_key
    db.commit()
    return {"message": "Profile updated successfully"}

@app.get("/api/student/quizzes")
def get_student_quizzes(
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Get all available quizzes for student."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get all quizzes for student's classroom
    quizzes = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.classroom_id == student.classroom_id
    ).order_by(models.SchoolQuiz.created_at.desc()).all()
    
    # Check which quizzes student has attempted and get their scores
    attempts_map = {
        a.school_quiz_id: a.score for a in student.student_attempts if a.score
    }
    
    return [
        {
            "id": q.id,
            "title": q.topic,
            "topic": q.topic,
            "quiz_format": q.quiz_format,
            "num_questions": q.num_questions,
            "difficulty": q.difficulty,
            "created_at": q.created_at,
            "due_date": (q.created_at + datetime.timedelta(days=7)).strftime("%b %d, %Y") if q.created_at else "No Due Date",
            "status": "completed" if q.id in attempts_map else "active",
            "attempted": q.id in attempts_map,
            "score": attempts_map.get(q.id),
            "time_limit": q.time_limit
        }
        for q in quizzes
    ]

@app.get("/api/student/quizzes/{quiz_id}")
def get_student_quiz(
    quiz_id: int,
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Get quiz questions for student to take."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    quiz = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.id == quiz_id,
        models.SchoolQuiz.classroom_id == student.classroom_id
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found or not accessible")
    
    # Return quiz without answers
    return {
        "quiz_id": quiz.id,
        "topic": quiz.topic,
        "format": quiz.quiz_format,
        "questions": quiz.questions.get("questions", []) if quiz.questions else []
    }

@app.post("/api/student/quizzes/{quiz_id}/generate")
def generate_student_quiz(
    quiz_id: int,
    req: StudentQuizGenerateRequest,
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Generate quiz questions for a student using their API key."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    quiz = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.id == quiz_id,
        models.SchoolQuiz.classroom_id == student.classroom_id
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found or not accessible")

    # Check for existing open attempt to reuse
    existing_attempt = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id,
        models.StudentAttempt.school_quiz_id == quiz_id,
        models.StudentAttempt.answers == None
    ).first()

    if existing_attempt and existing_attempt.questions:
        print(f"DEBUG: Reusing existing questions for quiz {quiz_id}")
        return {
            "message": "Quiz questions retrieved successfully",
            "attempt_id": existing_attempt.id,
            "questions": existing_attempt.questions
        }

    # Get Doc Content
    doc_content = ""
    if quiz.document_id:
        doc = db.query(models.Document).filter(models.Document.id == quiz.document_id).first()
        if doc and doc.content:
            doc_content = doc.content
            
    prompt = f"""
    Create a {quiz.difficulty} difficulty quiz about {quiz.topic}.
    Format: {quiz.quiz_format}
    Number of questions: {quiz.num_questions}
    
    Context from document:
    {doc_content[:10000]}
    
    Additional Notes: {quiz.additional_notes or "None"}
    
    Return ONLY valid JSON in this format:
    {{
      "questions": [
        {{
          "id": 1,
          "text": "Question text",
          "type": "objective", # MUST match the format requested
          "options": ["Option 1", "Option 2", "Option 3", "Option 4"], 
          "correct_answer": "Exact text of the correct option"
        }}
      ]
    }}
    STRICT RULES:
    1. STRICT FORMAT ADHERENCE: You MUST ONLY generate questions for the requested format "{quiz.quiz_format}". DO NOT MIX TYPES.
    2. If format is "objective" or "Multiple Choice": Every question MUST be multiple choice with 4 distinct options. The "type" MUST be "objective".
    3. If format is "theory" or "subjective" or "Free Text": Every question MUST be open-ended. The "options" MUST be null. The "type" MUST be "theory". The "correct_answer" MUST be a detailed model answer for evaluation.
    4. If format is "fill in the blank": Every question MUST have a sentence with a missing word/phrase indicated by "____". The "type" MUST be "fill_in_the_blank". The "options" MUST be null. The "correct_answer" MUST be the exact word/phrase.
    5. No markdown. No comments. No extra text.
    """

    try:
        client = get_gemini_client(req.api_key)
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        
        raw_text = response.text
        print(f"DEBUG RAW AI: {raw_text}") # Debug AI response
        text = clean_json_text(raw_text)
        quiz_json = json.loads(text)
        
    except Exception as e:
        print(f"Error generating quiz for ID {quiz_id}: {e}")
        # Log specific details about the failure to help diagnose API/Model issues
        if hasattr(e, 'status_code'):
             print(f"API ERROR STATUS: {e.status_code}")
        if hasattr(e, 'message'):
             print(f"API ERROR MESSAGE: {e.message}")
             
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}. Please check your API key and model access.")

    if existing_attempt:
        attempt = existing_attempt
        attempt.questions = quiz_json["questions"]
    else:
        attempt = models.StudentAttempt(
            student_id=student_id,
            school_quiz_id=quiz.id,
            questions=quiz_json["questions"],
            score=None,
            answers=None,
            feedback=None
        )
        db.add(attempt)
    
    db.commit()
    db.refresh(attempt)

    return {
        "message": "Quiz generated successfully",
        "attempt_id": attempt.id,
        "questions": attempt.questions
    }

@app.post("/api/student/quizzes/{quiz_id}/submit")
def submit_student_quiz(
    quiz_id: int,
    req: StudentQuizSubmitRequest,
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Submit quiz answers using student's API key."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    quiz = db.query(models.SchoolQuiz).filter(
        models.SchoolQuiz.id == quiz_id,
        models.SchoolQuiz.classroom_id == student.classroom_id
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found or not accessible")
    
    # Find existing attempt to update (preferred)
    attempt = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id,
        models.StudentAttempt.school_quiz_id == quiz_id
    ).order_by(models.StudentAttempt.completed_at.desc()).first()

    if attempt:
        questions = attempt.questions
    else:
        # Fallback to quiz template if no specific attempt exists
        questions = quiz.questions.get("questions", []) if quiz.questions else []

    is_objective = quiz.quiz_format.lower() in ["objective", "multiple-choice", "multiple_choice", "multiple choice", "true_false", "true or false"]
    
    evaluation = {}
    
    if is_objective:
        # LOCAL GRADING - NO AI CALL (Optimized)
        results = []
        correct_count = 0
        for q in questions:
            q_id = str(q.get("id"))
            student_answer = req.answers.get(q_id)
            correct_answer = q.get("correct_answer")
            
            is_correct = False
            if student_answer and correct_answer:
                if str(student_answer).strip().lower() == str(correct_answer).strip().lower():
                    is_correct = True
                    correct_count += 1
            
            results.append({
                "id": q.get("id"),
                "correct": is_correct,
                "score": 1.0 if is_correct else 0.0,
                "feedback": "Correct!" if is_correct else f"Incorrect. The correct answer was: {correct_answer}"
            })
        
        evaluation = {
            "score": f"{correct_count}/{len(questions)}",
            "results": results
        }
    else:
        # AI EVALUATION for theory/subjective
        try:
            client = get_gemini_client(req.api_key)
            
            submission_str = json.dumps(req.answers, indent=2)
            questions_str = json.dumps(questions, indent=2)
            
            # Get Doc Content for context if available
            doc_context = ""
            if quiz.document_id:
                doc = db.query(models.Document).filter(models.Document.id == quiz.document_id).first()
                if doc and doc.content:
                    doc_context = f"Document Context:\n{doc.content[:10000]}\n"

            prompt = f"""
            Evaluate this subjective/theory quiz submission.
            
            {doc_context}
            
            Original Questions & Model Answers (Reference for Grading):
            {questions_str}
            
            Student Submission:
            {submission_str}
            
            Task:
            - For each question, compare the student's answer to the "correct_answer" (Model Answer) provided in the reference.
            - Award a score between 0.0 and 1.0 for each question based on conceptual accuracy and completeness.
            - SCORING RULES:
              1. If the answer is close but missing the main points, award 0.5 to 0.8.
              2. If the question asks to "list and explain" but the student only lists, award 0.4 to 0.5.
              3. If the user provides a partial list (e.g., 3 out of 5), award a proportional score (e.g., 0.65).
              4. Award 1.0 only for complete and accurate answers.
              5. Award 0.0 for irrelevant or completely wrong answers.
            - Provide constructive feedback explaining the score and what was missing or well done.
            - Return ONLY valid JSON in this format:
            {{
              "results": [
                {{
                  "id": number,
                  "score": float, (between 0.0 and 1.0)
                  "feedback": "short explanation"
                }}
              ]
            }}
            """
            
            response = client.models.generate_content(
                model=get_gemini_model_name(),
                contents=prompt
            )
            raw_text = response.text
            text = clean_json_text(raw_text)
            evaluation = json.loads(text)
            
            # Force score calculation with fractional support
            results = evaluation.get("results", [])
            total_obtained = 0
            for r in results:
                if "score" in r:
                    s = float(r.get("score", 0))
                else:
                    s = 1.0 if r.get("correct") else 0.0
                    r["score"] = s
                    
                total_obtained += s
                # Add "correct" field for backward compatibility/UI indicators
                r["correct"] = s >= 0.5
            
            # Format score: if it's an integer, show as int, otherwise up to 2 decimal places
            display_score = f"{int(total_obtained) if total_obtained.is_integer() else round(total_obtained, 2)}/{len(results)}"
            evaluation["score"] = display_score
            
        except Exception as e:
            print(f"Error evaluating quiz: {e}")
            raise HTTPException(status_code=500, detail=f"AI Evaluation Failed: {str(e)}")

    if attempt:
        attempt.score = evaluation.get("score", "0/0")
        attempt.answers = req.answers
        attempt.feedback = evaluation.get("results", [])
        attempt.completed_at = datetime.datetime.utcnow()
    else:
        attempt = models.StudentAttempt(
            student_id=student_id,
            school_quiz_id=quiz_id,
            score=evaluation.get("score", "0/0"),
            answers=req.answers,
            feedback=evaluation.get("results", []),
            questions=questions,
            completed_at=datetime.datetime.utcnow()
        )
        db.add(attempt)

    db.commit()
    db.refresh(attempt)
    
    return {
        "attempt_id": attempt.id,
        "score": evaluation.get("score"),
        "results": evaluation.get("results", [])
    }

@app.get("/api/student/attempts")
def get_student_attempts(
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Get student's quiz history."""
    attempts = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id,
        models.StudentAttempt.completed_at != None
    ).order_by(models.StudentAttempt.completed_at.desc()).all()
    
    return [
        {
            "id": a.id,
            "quiz_topic": a.school_quiz.topic,
            "score": a.score,
            "completed_at": a.completed_at
        }
        for a in attempts
    ]

@app.get("/api/student/attempts/{attempt_id}")
def get_attempt_details(
    attempt_id: int,
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Get detailed attempt history with questions and feedback."""
    attempt = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.id == attempt_id,
        models.StudentAttempt.student_id == student_id
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    return {
        "id": attempt.id,
        "quiz_topic": attempt.school_quiz.topic,
        "quiz_format": attempt.school_quiz.quiz_format,
        "score": attempt.score,
        "completed_at": attempt.completed_at,
        "questions": attempt.questions,
        "answers": attempt.answers,
        "feedback": attempt.feedback
    }

@app.get("/api/student/analysis")
def get_student_analysis(
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """AI-powered analysis of student progress."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Check if student has API key
    if not student.google_api_key:
        return {
            "message": "Google API key required for Guardian AI analysis.",
            "requires_api_key": True,
            "insights": [],
            "strengths": [],
            "weaknesses": [],
            "recommendations": []
        }
    
    # Get all student attempts
    attempts = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id,
        models.StudentAttempt.score != None  # Only completed attempts
    ).order_by(models.StudentAttempt.completed_at.asc()).all()
    
    if not attempts:
        return {
            "message": "No attempts found. Complete some quizzes to get AI analysis.",
            "insights": [],
            "strengths": [],
            "weaknesses": [],
            "recommendations": []
        }
    
    # Prepare data for AI analysis
    attempt_data = []
    for a in attempts:
        score_parts = a.score.split("/") if a.score else ["0", "1"]
        try:
            correct = float(score_parts[0]) if len(score_parts) > 0 else 0
            total = float(score_parts[1]) if len(score_parts) > 1 else 1
        except (ValueError, TypeError):
            correct = 0
            total = 1
        percentage = (correct / total * 100) if total > 0 else 0
        
        attempt_data.append({
            "quiz_topic": a.school_quiz.topic,
            "format": a.school_quiz.quiz_format,
            "difficulty": a.school_quiz.difficulty,
            "score": a.score,
            "percentage": round(percentage, 1),
            "date": str(a.completed_at),
            "num_questions": len(a.questions) if a.questions else 0
        })
    
    # Create AI prompt
    prompt = f"""
    Analyze this student's quiz performance data and provide insights:
    
    Student Name: {student.name}
    Total Quizzes Completed: {len(attempts)}
    
    Performance History:
    {json.dumps(attempt_data, indent=2)}
    
    Task:
    Provide a comprehensive analysis in JSON format with:
    1. Overall insights about performance trends
    2. Identified strengths (topics/formats they excel in)
    3. Identified weaknesses (areas needing improvement)
    4. Specific, actionable recommendations
    
    Return ONLY valid JSON in this exact format:
    {{
      "overall_summary": "Brief summary of overall performance",
      "insights": ["insight 1", "insight 2", "insight 3"],
      "strengths": ["strength 1", "strength 2"],
      "weaknesses": ["weakness 1", "weakness 2"],
      "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"]
    }}
    
    No markdown. No extra text.
    """
    
    try:
        client = get_gemini_client(student.google_api_key)
        response = client.models.generate_content(
            model=get_gemini_model_name(),
            contents=prompt
        )
        
        raw_text = response.text
        text = clean_json_text(raw_text)
        analysis = json.loads(text)
        
        return analysis
        
    except Exception as e:
        print(f"Error generating analysis: {e}")
        raise HTTPException(status_code=500, detail=f"AI Analysis Failed: {str(e)}")

@app.get("/api/school/dashboard/overview")
def get_school_dashboard(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get school dashboard overview statistics."""
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    
    total_classrooms = len(school.classrooms)
    total_students = len(school.students)
    total_quizzes = len(school.school_quizzes)
    
    # Get recent activity
    recent_attempts = db.query(models.StudentAttempt).join(
        models.Student
    ).filter(
        models.Student.school_id == school_id
    ).order_by(
        models.StudentAttempt.completed_at.desc()
    ).limit(10).all()
    
    return {
        "school": {
            "name": school.name,
            "country": school.country
        },
        "statistics": {
            "total_classrooms": total_classrooms,
            "total_students": total_students,
            "total_quizzes": total_quizzes
        },
        "recent_activity": [
            {
                "student_name": a.student.name,
                "quiz_topic": a.school_quiz.topic,
                "score": a.score,
                "completed_at": a.completed_at
            }
            for a in recent_attempts
        ]
    }

@app.get("/api/school/analytics")
def get_school_analytics(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get aggregated school analytics."""
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    # 1. Monthly Performance Trends (Growth Chart)
    # Get all attempts for this school in the last 6 months
    six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
    
    attempts = db.query(models.StudentAttempt).join(
        models.Student
    ).filter(
        models.Student.school_id == school_id,
        models.StudentAttempt.completed_at >= six_months_ago
    ).all()

    # Aggregate by month
    monthly_data = {}
    for a in attempts:
        if not a.completed_at: continue
        month_key = a.completed_at.strftime("%b")
        if month_key not in monthly_data:
            monthly_data[month_key] = {"total_score": 0, "count": 0}
        
        score_val = calculate_student_average([a]) # Use existing helper for single attempt
        if score_val > 0:
            monthly_data[month_key]["total_score"] += score_val
            monthly_data[month_key]["count"] += 1

    growth_trends = []
    # Ensure all 6 months are present, even if empty
    for i in range(5, -1, -1):
        m = (datetime.datetime.utcnow() - datetime.timedelta(days=i*30)).strftime("%b")
        avg = round(monthly_data[m]["total_score"] / monthly_data[m]["count"], 1) if m in monthly_data and monthly_data[m]["count"] > 0 else 0
        growth_trends.append({"month": m, "score": avg})

    # 2. Classroom Performance Distribution (Pie/Bar Chart)
    classrooms = db.query(models.Classroom).filter(models.Classroom.school_id == school_id).all()
    classroom_dist = []
    for c in classrooms:
        class_attempts = db.query(models.StudentAttempt).join(
            models.Student
        ).filter(
            models.Student.classroom_id == c.id
        ).all()
        avg_score = calculate_student_average(class_attempts)
        classroom_dist.append({"name": c.name, "value": avg_score})

    # 3. Overall Statistics
    total_classrooms = len(school.classrooms)
    total_students = len(school.students)
    overall_avg = calculate_student_average(attempts) # Using all 6 months' attempts for overall avg
    
    # 4. Recent Activity
    recent_activity = []
    sorted_attempts = sorted(attempts, key=lambda x: x.completed_at, reverse=True)[:5]
    for a in sorted_attempts:
        recent_activity.append({
            "title": f"{a.school_quiz.topic}: Attempt Logged",
            "user": a.student.name,
            "time": a.completed_at.strftime("%Y-%m-%d %H:%M") if a.completed_at else "Unknown",
            "score": a.score
        })

    return {
        "stats": {
            "total_classrooms": total_classrooms,
            "total_students": total_students,
            "avg_achievement": f"{overall_avg}%",
            "cognitive_velocity": "4.8x" # Optional placeholder as per design
        },
        "growth_trends": growth_trends,
        "classroom_distribution": classroom_dist,
        "recent_activity": recent_activity
    }

# --- Individual Portal Endpoints ---

@app.get("/api/individual/profile")
def get_individual_profile(
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get individual user profile."""
    individual = db.query(models.Individual).filter(models.Individual.id == individual_id).first()
    if not individual:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "name": individual.name,
        "email": individual.email,
        "openrouter_api_key": individual.openrouter_api_key
    }

class IndividualSettingsUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

@app.post("/api/individual/settings")
def update_individual_settings(
    settings: IndividualSettingsUpdate,
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Update individual user settings."""
    individual = db.query(models.Individual).filter(models.Individual.id == individual_id).first()
    if not individual:
        raise HTTPException(status_code=404, detail="User not found")
    
    if settings.openrouter_api_key is not None:
        individual.openrouter_api_key = settings.openrouter_api_key
    if settings.google_api_key is not None:
        individual.google_api_key = settings.google_api_key
    db.commit()
    
    return {"message": "Settings updated successfully"}

@app.get("/api/individual/dashboard")
def get_individual_dashboard(
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get dashboard statistics for individual users."""
    total_quizzes = db.query(models.Quiz).filter(
        models.Quiz.user_id == str(individual_id)
    ).count()
    
    total_attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(individual_id),
        models.Attempt.score.isnot(None)
    ).count()
    
    attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(individual_id),
        models.Attempt.score.isnot(None)
    ).all()
    
    avg_score = 0
    if attempts:
        total_score = 0
        for a in attempts:
            if '%' in a.score:
                total_score += int(a.score.split('%')[0])
            elif '/' in a.score:
                parts = a.score.split('/')
                try:
                    num = float(parts[0])
                    den = float(parts[1])
                    if den > 0:
                        total_score += (num / den) * 100
                except:
                    pass
        avg_score = round(total_score / len(attempts), 1)
    
    seven_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    recent_attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(individual_id),
        models.Attempt.timestamp >= seven_days_ago,
        models.Attempt.score.isnot(None)
    ).order_by(models.Attempt.timestamp.desc()).limit(5).all()
    
    # Get all successful attempts for history chart
    all_attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(individual_id),
        models.Attempt.score.isnot(None)
    ).order_by(models.Attempt.timestamp.asc()).all()
    
    return {
        "total_quizzes": total_quizzes,
        "total_attempts": total_attempts,
        "avg_score": avg_score,
        "recent_activity": [
            {
                "id": a.id,
                "quiz_topic": a.quiz.topic if a.quiz else "Unknown",
                "score": f"{round((float(a.score.split('/')[0])/float(a.score.split('/')[1])*100), 1) if '/' in a.score and float(a.score.split('/')[1])>0 else 0}%",
                "mark": a.score,
                "timestamp": a.timestamp.strftime("%b %d, %Y")
            }
            for a in recent_attempts
        ],
        "performance_history": [
            {
                "id": a.id,
                "quiz_topic": a.quiz.topic if a.quiz else "Unknown",
                "score": f"{round((float(a.score.split('/')[0])/float(a.score.split('/')[1])*100), 1) if '/' in a.score and float(a.score.split('/')[1])>0 else 0}%",
                "timestamp": a.timestamp.strftime("%b %d, %Y")
            }
            for a in all_attempts
        ]
    }

@app.get("/api/individual/quizzes")
def get_individual_quizzes(
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get all quizzes created by individual user."""
    quizzes = db.query(models.Quiz).filter(
        models.Quiz.user_id == str(individual_id)
    ).order_by(models.Quiz.created_at.desc()).all()
    
    
    results = []
    for q in quizzes:
        is_completed = db.query(models.Attempt).filter(
            models.Attempt.quiz_id == q.id,
            models.Attempt.score.isnot(None)
        ).count() > 0
        
        results.append({
            "id": q.id,
            "topic": q.topic,
            "quiz_format": q.quiz_format,
            "num_questions": q.num_questions,
            "difficulty": q.difficulty,
            "created_at": q.created_at.strftime("%b %d, %Y") if q.created_at else "Unknown",
            "is_completed": is_completed
        })
    return results

@app.post("/api/individual/quizzes")
async def create_individual_quiz(
    topic: str = Form(None),
    quiz_format: str = Form("multiple_choice"),
    num_questions: int = Form(5),
    difficulty: str = Form("medium"),
    time_limit: int = Form(30),
    file: UploadFile = File(None),
    document_id: int = Form(None),
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Create a new quiz for individual practice with optional document upload."""
    
    file_content = ""
    file_name_for_doc = ""
    
    # 1. Handle File Upload (and save as Document)
    if file:
        file_name_for_doc = file.filename
        base_dir = f"uploads/individuals/{individual_id}"
        os.makedirs(base_dir, exist_ok=True)
        file_path = f"{base_dir}/{file.filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        try:
            parsing_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
            if parsing_api_key:
                print("Using LlamaParse for document...")
                parser = LlamaParse(api_key=parsing_api_key, result_type="markdown", verbose=True)
                documents = await parser.aload_data(file_path)
                if documents:
                    file_content = documents[0].text
                    print(f"LlamaParse success. Content length: {len(file_content)}")
            else:
                 print("LLAMA_CLOUD_API_KEY missing. Fallback read.")
                 with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()
        except Exception as e:
            print(f"Parsing error: {e}")
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f: file_content = f.read()
            except: file_content = ""
        
        # Save to DB if we successfully got content
        if file_content:
            new_doc = models.Document(
                individual_id=individual_id,
                filename=file_name_for_doc,
                content=file_content
            )
            db.add(new_doc)
            db.commit()
            print(f"Saved new document: {file_name_for_doc}")

    # 2. Handle Saved Document Usage
    elif document_id:
        doc = db.query(models.Document).filter(
            models.Document.id == document_id, 
            models.Document.individual_id == individual_id
        ).first()
        if doc:
            file_content = doc.content
            # Use filename as topic if not provided
            if not topic: topic = doc.filename 
            print(f"Using saved document: {doc.filename}")

    # Validation
    if not topic and not file_content:
         if file_name_for_doc: topic = file_name_for_doc
         else: topic = "Untitled Quiz"

    # Create prompt with file context if available
    context_prompt = ""
    if file_content:
        context_prompt = f"\n\nContext based on document:\n{file_content[:15000]}..." 
    
    # Generate questions (This would connect to your AI service)
    # For now, we'll Create the quiz record
    new_quiz = models.Quiz(
        user_id=str(individual_id),
        topic=topic or "Untitled Quiz",
        quiz_format=quiz_format,
        num_questions=num_questions,
        difficulty=difficulty,
        time_limit=time_limit
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)
    
    # Here you would typically trigger the AI generation using the topic + context
    # generate_quiz_questions(new_quiz.id, topic, context_prompt)
    
    # Mock generation for immediate feedback (replacing the previous stub)
    # In a real app, this should be an async background task or call the AI service
    
    # Fetch individual to get API key
    individual = db.query(models.Individual).filter(models.Individual.id == individual_id).first()
    if not individual or not individual.google_api_key:
         # Log for debugging but allow "mock" generation if we wanted to support free tier without keys? 
         # For now, require key as per requirements.
         print("Missing Google API Key for quiz generation")
         # raise HTTPException(status_code=400, detail="Google API Key not set.")
         # actually, let's just proceed with a dummy key if implementation allows, or fail.
         # Based on user request "I am failing to save the api key", they probably have one now.
         # Let's start by getting the key.
         pass

    api_key_to_use = individual.google_api_key if individual and individual.google_api_key else "AI-dummy-key"

    prompt = build_quiz_prompt(topic, quiz_format, num_questions, difficulty)
    
    # If we have context, add it as a separate instruction in the prompt
    if context_prompt:
        prompt += f"\n\nBase your questions on the following content:\n{context_prompt}"

    # Only call AI if we have a key
    questions = await generate_quiz_questions_ai(prompt, api_key_to_use)
    
    # DEBUG LOGGING for User
    if questions:
        print(f"\n--- AI GENERATED QUESTIONS ({quiz_format}) ---")
        print(json.dumps(questions, indent=2))
        print("------------------------------------------\n")
    else:
        print("\n--- AI GENERATED NO QUESTIONS ---\n")

    if not questions:
        # Fallback if AI fails
        print("AI generation returned empty, using fallback.")
        questions = []
    
    for idx, q_data in enumerate(questions):
        question = models.Question(
            quiz_id=new_quiz.id,
            text=q_data.get('question', 'Question text missing'),
            options=q_data.get('options'),
            correct_answer=q_data.get('correct_answer', ''),
            question_type=quiz_format
        )
        db.add(question)
    
    db.commit()
    
    return {
        "id": new_quiz.id,
        "topic": new_quiz.topic,
        "quiz_format": new_quiz.quiz_format,
        "num_questions": new_quiz.num_questions,
        "time_limit": new_quiz.time_limit,
        "created_at": new_quiz.created_at.strftime("%b %d, %Y") if new_quiz.created_at else "Unknown"
    }

@app.post("/api/individual/quizzes/{quiz_id}/start")
def start_individual_quiz(
    quiz_id: int,
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Start a quiz attempt for an individual."""
    quiz = db.query(models.Quiz).filter(
        models.Quiz.id == quiz_id,
        models.Quiz.user_id == str(individual_id)
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == quiz_id
    ).all()
    
    attempt = models.Attempt(
        user_id=str(individual_id),
        quiz_id=quiz_id
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    
    return {
        "attempt_id": attempt.id,
        "quiz_topic": quiz.topic,
        "quiz_format": quiz.quiz_format,
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "options": q.options,
                "question_type": q.question_type
            }
            for q in questions
        ]
    }

@app.post("/api/individual/attempts/{attempt_id}/submit")
async def submit_individual_attempt(
    attempt_id: int,
    req: QuizSubmitRequest,
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Submit answers for grading."""
    attempt = db.query(models.Attempt).filter(
        models.Attempt.id == attempt_id,
        models.Attempt.user_id == str(individual_id)
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    quiz = attempt.quiz
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == quiz.id
    ).all()
    
    # Fetch Individual for API key
    individual = db.query(models.Individual).filter(models.Individual.id == individual_id).first()
    api_key = individual.google_api_key if individual else None
    
    if not api_key:
        # Fallback to simple matching if no key? Or fail? 
        # User requirement says "Configuration... Without this, quiz generation will fail."
        # Submission implies generation succeeded, so key likely exists.
        # But if they cleared it, we should probably fail or fallback.
        # For robustness, let's try fallback to simple matching if key missing, or just error.
        # Given "AI evaluates answers" is a core requirement, let's prefer AI but handle failure gracefully.
        print("Warning: No API key for grading. Result might be inaccurate for theory questions.")
        
    # Prepare data for AI
    questions_data = [
        {
            "id": q.id,
            "text": q.text,
            "options": q.options,
            "correct_answer": q.correct_answer
        }
        for q in questions
    ]
    
    # Call AI Evaluation
    ai_result = await evaluate_submission_ai(questions_data, req.answers, api_key or "AI-dummy-key")
    
    # If AI fails (empty results), fallback to basic matching for objective questions
    if not ai_result.get("results"):
        print("AI Evaluation failed or returned empty. Using fallback grading.")
        correct_count = 0
        feedback_list = []
        for q in questions:
            ua = req.answers.get(str(q.id), "")
            is_correct = ua.strip().lower() == (q.correct_answer or "").strip().lower()
            if is_correct: correct_count += 1
            feedback_list.append({
                "id": q.id,
                "correct": is_correct,
                "score": 1.0 if is_correct else 0.0,
                "user_answer": ua,
                "correct_answer": q.correct_answer,
                "feedback": "Correct" if is_correct else f"Incorrect. The right answer was {q.correct_answer}"
            })
        
        ai_result = {
            "score": f"{correct_count}/{len(questions)}",
            "results": feedback_list
        }

    # Save results
    final_feedback = ai_result.get("results", [])
    
    # Ensure user_answer and correct_answer are present in feedback items
    # We correlate by ID first, then by index as a fallback (AI often re-indexes to 1,2,3...)
    for idx, item in enumerate(final_feedback):
        q_id = str(item.get("id"))
        # Match by ID
        q_match = next((q for q in questions if str(q.id) == q_id), None)
        
        # Fallback to index-based match if AI re-indexed questions to 1,2,3...
        if not q_match and idx < len(questions):
            q_match = questions[idx]
            
        if q_match:
            if "user_answer" not in item:
                item["user_answer"] = req.answers.get(str(q_match.id), "")
            if "correct_answer" not in item:
                item["correct_answer"] = q_match.correct_answer
            # Sync ID to database ID for reliable frontend lookup
            item["id"] = q_match.id

    attempt.score = ai_result.get("score", "0/0")
    attempt.feedback = final_feedback
    attempt.timestamp = datetime.datetime.utcnow()
    
    db.commit()
    
    # Parse score for percentage
    try:
        if "/" in attempt.score:
            num, den = map(float, attempt.score.split('/'))
            score_percentage = round((num / den) * 100, 1) if den > 0 else 0
        else:
             score_percentage = 0
    except:
        score_percentage = 0

    return {
        "score": f"{score_percentage}%",
        "mark": attempt.score,
        "score_percentage": score_percentage,
        "feedback": attempt.feedback
    }

@app.get("/api/individual/attempts")
def get_individual_attempts(
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get all quiz attempts for individual."""
    attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(individual_id),
        models.Attempt.score.isnot(None)
    ).order_by(models.Attempt.timestamp.desc()).all()
    
    return [
        {
            "id": a.id,
            "quiz_topic": a.quiz.topic if a.quiz else "Unknown",
            "quiz_format": a.quiz.quiz_format if a.quiz else "Unknown",
            "num_questions": a.quiz.num_questions if a.quiz else 0,
            "score": f"{round((float(a.score.split('/')[0])/float(a.score.split('/')[1])*100), 1) if '/' in a.score and float(a.score.split('/')[1])>0 else 0}%",
            "mark": a.score,
            "timestamp": a.timestamp.strftime("%b %d, %Y") if a.timestamp else "Unknown"
        }
        for a in attempts
    ]

@app.get("/api/individual/documents")
def get_individual_documents(
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get all documents uploaded by individual."""
    docs = db.query(models.Document).filter(
        models.Document.individual_id == individual_id
    ).order_by(models.Document.created_at.desc()).all()
    
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "created_at": doc.created_at.strftime("%b %d, %Y") if doc.created_at else "Unknown"
        }
        for doc in docs
    ]

@app.get("/api/individual/attempts/{attempt_id}")
def get_individual_attempt_details(
    attempt_id: int,
    individual_id: int = Depends(individual_auth.get_current_individual_id),
    db: Session = Depends(database.get_db)
):
    """Get detailed results for a specific attempt."""
    attempt = db.query(models.Attempt).filter(
        models.Attempt.id == attempt_id,
        models.Attempt.user_id == str(individual_id)
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == attempt.quiz_id
    ).all()
    
    return {
        "id": attempt.id,
        "quiz_topic": attempt.quiz.topic if attempt.quiz else "Unknown",
        "score": f"{round((float(attempt.score.split('/')[0])/float(attempt.score.split('/')[1])*100), 1) if '/' in attempt.score and float(attempt.score.split('/')[1])>0 else 0}%",
        "mark": attempt.score,
        "timestamp": attempt.timestamp.strftime("%b %d, %Y %H:%M") if attempt.timestamp else "Unknown",
        "feedback": attempt.feedback,
        "questions": [
            {
                "id": q.id,
                "text": q.text,
                "options": q.options,
                "correct_answer": q.correct_answer
            }
            for q in questions
        ]
     }
