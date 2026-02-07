# Individual Portal Backend Endpoints

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import datetime

# Individual Dashboard Stats
@app.get("/api/individual/dashboard")
def get_individual_dashboard(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get dashboard statistics for individual users (reusing school auth)."""
    # Count total quizzes created
    total_quizzes = db.query(models.Quiz).filter(
        models.Quiz.user_id == str(school_id)
    ).count()
    
    # Count total attempts
    total_attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(school_id)
    ).count()
    
    # Calculate average score
    attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(school_id),
        models.Attempt.score.isnot(None)
    ).all()
    
    avg_score = 0
    if attempts:
        scores = [int(a.score.split('%')[0]) if '%' in a.score else int(a.score.split('/')[0])/int(a.score.split('/')[1])*100 
                  for a in attempts if a.score]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    
    # Get recent activity (last 7 days)
    seven_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    recent_attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(school_id),
        models.Attempt.timestamp >= seven_days_ago
    ).order_by(models.Attempt.timestamp.desc()).limit(5).all()
    
    return {
        "total_quizzes": total_quizzes,
        "total_attempts": total_attempts,
        "avg_score": avg_score,
        "recent_activity": [
            {
                "id": a.id,
                "quiz_topic": a.quiz.topic if a.quiz else "Unknown",
                "score": a.score,
                "timestamp": a.timestamp
            }
            for a in recent_attempts
        ]
    }

# Get all individual quizzes
@app.get("/api/individual/quizzes")
def get_individual_quizzes(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all quizzes created by individual user."""
    quizzes = db.query(models.Quiz).filter(
        models.Quiz.user_id == str(school_id)
    ).order_by(models.Quiz.created_at.desc()).all()
    
    return [
        {
            "id": q.id,
            "topic": q.topic,
            "quiz_format": q.quiz_format,
            "num_questions": q.num_questions,
            "difficulty": q.difficulty,
            "time_limit": q.time_limit,
            "created_at": q.created_at
        }
        for q in quizzes
    ]

# Create a new quiz
@app.post("/api/individual/quizzes")
async def create_individual_quiz(
    topic: str = Form(...),
    quiz_format: str = Form("multiple_choice"),
    num_questions: int = Form(5),
    difficulty: str = Form("medium"),
    time_limit: int = Form(88),
    file: Optional[UploadFile] = File(None),
    document_id: Optional[int] = Form(None),
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Create a new quiz for individual practice."""
    # Create quiz record
    new_quiz = models.Quiz(
        user_id=str(school_id),
        topic=topic,
        quiz_format=quiz_format,
        num_questions=num_questions,
        difficulty=difficulty,
        time_limit=time_limit
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)
    
    # Generate questions using Gemini
    prompt = generate_quiz_prompt(topic, quiz_format, num_questions, difficulty)
    questions = await generate_quiz_questions(prompt, quiz_format, num_questions)
    
    # Save questions
    for idx, q_data in enumerate(questions):
        question = models.Question(
            quiz_id=new_quiz.id,
            text=q_data.get('question', ''),
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
        "created_at": new_quiz.created_at
    }

# Start a quiz attempt
@app.post("/api/individual/quizzes/{quiz_id}/start")
def start_individual_quiz(
    quiz_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Start a quiz attempt for an individual."""
    quiz = db.query(models.Quiz).filter(
        models.Quiz.id == quiz_id,
        models.Quiz.user_id == str(school_id)
    ).first()
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Get questions
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == quiz_id
    ).all()
    
    # Create attempt
    attempt = models.Attempt(
        user_id=str(school_id),
        quiz_id=quiz_id
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    
    return {
        "attempt_id": attempt.id,
        "quiz_topic": quiz.topic,
        "time_limit": quiz.time_limit,
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

# Submit quiz attempt
@app.post("/api/individual/attempts/{attempt_id}/submit")
async def submit_individual_attempt(
    attempt_id: int,
    req: QuizSubmitRequest,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Submit answers for grading."""
    attempt = db.query(models.Attempt).filter(
        models.Attempt.id == attempt_id,
        models.Attempt.user_id == str(school_id)
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Get quiz and questions
    quiz = attempt.quiz
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == quiz.id
    ).all()
    
    # Grade answers
    correct_count = 0
    feedback = []
    
    for question in questions:
        user_answer = req.answers.get(str(question.id), "")
        is_correct = user_answer.strip().lower() == question.correct_answer.strip().lower()
        
        if is_correct:
            correct_count += 1
        
        feedback.append({
            "question_id": question.id,
            "correct": is_correct,
            "user_answer": user_answer,
            "correct_answer": question.correct_answer
        })
    
    # Calculate score
    score_percentage = round((correct_count / len(questions)) * 100, 1)
    score = f"{correct_count}/{len(questions)}"
    
    # Update attempt
    attempt.score = score
    attempt.timestamp = datetime.datetime.utcnow()
    attempt.feedback = feedback
    db.commit()
    
    return {
        "score": score,
        "score_percentage": score_percentage,
        "feedback": feedback
    }

# Get attempt history
@app.get("/api/individual/attempts")
def get_individual_attempts(
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get all quiz attempts for individual."""
    attempts = db.query(models.Attempt).filter(
        models.Attempt.user_id == str(school_id),
        models.Attempt.score.isnot(None)
    ).order_by(models.Attempt.timestamp.desc()).all()
    
    return [
        {
            "id": a.id,
            "quiz_topic": a.quiz.topic if a.quiz else "Unknown",
            "quiz_format": a.quiz.quiz_format if a.quiz else "Unknown",
            "num_questions": a.quiz.num_questions if a.quiz else 0,
            "time_limit": a.quiz.time_limit if a.quiz else 30,
            "score": a.score,
            "timestamp": a.timestamp
        }
        for a in attempts
    ]

# Get attempt details
@app.get("/api/individual/attempts/{attempt_id}")
def get_individual_attempt_details(
    attempt_id: int,
    school_id: int = Depends(school_auth.get_current_school_id),
    db: Session = Depends(database.get_db)
):
    """Get detailed results for a specific attempt."""
    attempt = db.query(models.Attempt).filter(
        models.Attempt.id == attempt_id,
        models.Attempt.user_id == str(school_id)
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Get questions
    questions = db.query(models.Question).filter(
        models.Question.quiz_id == attempt.quiz_id
    ).all()
    
    return {
        "id": attempt.id,
        "quiz_topic": attempt.quiz.topic if attempt.quiz else "Unknown",
        "score": attempt.score,
        "timestamp": attempt.timestamp,
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
