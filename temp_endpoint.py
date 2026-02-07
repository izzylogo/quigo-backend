@app.post("/api/student/quizzes/{quiz_id}/generate")
def generate_student_quiz(
    quiz_id: int,
    req: StudentQuizGenerateRequest, # Defined in schemas.py as: class StudentQuizGenerateRequest(BaseModel): api_key: str
    student_id: int = Depends(school_auth.get_current_student_id),
    db: Session = Depends(database.get_db)
):
    """Generate independent quiz questions for a student using their API key."""
    # check student 
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    # check quiz
    quiz = db.query(models.SchoolQuiz).filter(models.SchoolQuiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
        
    # check if attempt already exists
    # If attempt exists and has questions, return them? Or prevent re-generation?
    # For now, let's assume we want to generate if not already started.
    existing_attempt = db.query(models.StudentAttempt).filter(
        models.StudentAttempt.student_id == student_id,
        models.StudentAttempt.school_quiz_id == quiz_id
    ).first()
    
    if existing_attempt and existing_attempt.questions:
         return {
            "message": "Quiz already generated",
            "attempt_id": existing_attempt.id,
            "questions": existing_attempt.questions
        }
    
    # Get document context
    document = db.query(models.Document).filter(models.Document.id == quiz.document_id).first()
    if not document:
        raise HTTPException(status_code=400, detail="Document content not found for this quiz.")
        
    context_text = document.content
    
    # Initialize OpenRouter client with student's provided key
    try:
        client = get_openrouter_client(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid API Key provided")

    # Build prompt (Reusing logic from create_school_quiz)
    options_instruction = ""
    if quiz.quiz_format == "objective":
        options_instruction = "options MUST include A, B, C, D keys mapped to answer text."
    elif quiz.quiz_format in ["theory", "fill_in_the_blank"]:
        options_instruction = "options MUST be null."
    
    difficulty_instruction = ""
    if quiz.difficulty.lower() == "easy":
        difficulty_instruction = "Focus on high-level definitions and key terms."
    elif quiz.difficulty.lower() == "medium":
        difficulty_instruction = "Extract questions from beginning, middle, and end."
    elif quiz.difficulty.lower() == "hard":
        difficulty_instruction = "Focus on subtle details and complex scenarios."
    
    combined_context = context_text
    if quiz.additional_notes:
        combined_context += f"\n\nADDITIONAL NOTES FROM TEACHER:\n{quiz.additional_notes}"
    
    prompt = f"""
    Generate a quiz about "{quiz.topic}" based on the following DOCUMENT CONTEXT.
    
    DOCUMENT CONTEXT:
    {combined_context}
    
    ----------------
    
    Task:
    Generate {quiz.num_questions} questions.
    Format: {quiz.quiz_format}
    Difficulty: {quiz.difficulty}
    
    Return ONLY a raw JSON object. NO markdown.
    The JSON format MUST be EXACTLY:
    {{
      "topic": "{quiz.topic}",
      "format": "{quiz.quiz_format}",
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
    - Randomize the position of the correct answer (A, B, C, D).
    - Generate questions from random parts of the document.
    - {difficulty_instruction}
    - {options_instruction}
    - answer field MUST always be an empty string (student will fill it).
    - ensure unique IDs for questions (1, 2, 3...)
    - NEGATIVE CONSTRAINTS: Do NOT ask about author, publication date, or document structure.
    """
    
    try:
        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "http://localhost:5173",
                "X-Title": "School Quiz Gen",
            },
            model=quiz.ai_model,
            messages=[{"role": "user", "content": prompt}]
        )
        
        text = clean_json_text(completion.choices[0].message.content)
        quiz_json = json.loads(text)
        
    except Exception as e:
        print(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}")
        
    # Save student attempt with generated questions
    if existing_attempt:
        existing_attempt.questions = quiz_json["questions"]
        db.commit()
        db.refresh(existing_attempt)
        attempt = existing_attempt
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
