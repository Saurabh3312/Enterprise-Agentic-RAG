import json
import os
import shutil
import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import config, runtime_settings as rs
from app.database import init_db, get_db, Document, ChatSession, Message, QueryLog, AgentTrace, RuntimeSettings, SessionLocal
from app.ingest import ingest_by_extension, ingest_url, delete_document, collection, SUPPORTED_EXTENSIONS
from app.retrieval import rebuild_bm25_index
from app.agent import run_agent

app = FastAPI(title=config.API_TITLE, version=config.API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    rebuild_bm25_index()
    db = SessionLocal()
    try:
        row = db.query(RuntimeSettings).filter(RuntimeSettings.id == 1).first()
        if row is None:
            row = RuntimeSettings(id=1)
            db.add(row)
            db.commit()
        rs.load_from_row(row)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None


class SessionCreate(BaseModel):
    title: str | None = "New conversation"


class UrlIngestRequest(BaseModel):
    url: str


class FeedbackRequest(BaseModel):
    rating: int  # 1 = thumbs up, -1 = thumbs down, 0 = clear


class SettingsUpdate(BaseModel):
    OLLAMA_MODEL: str | None = None
    MAX_AGENT_HOPS: int | None = None
    MIN_CONFIDENCE_TO_STOP: float | None = None
    MAX_SUBQUESTIONS: int | None = None
    HYBRID_ALPHA: float | None = None
    VECTOR_TOP_K: int | None = None
    BM25_TOP_K: int | None = None
    RERANK_TOP_K: int | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    return {"message": "Enterprise Agentic RAG Platform Running", "version": config.API_VERSION}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    extension = Path(file.filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{extension}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    file_path = os.path.join(config.UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    size_kb = round(os.path.getsize(file_path) / 1024, 2)

    doc_row = Document(filename=file.filename, file_size_kb=size_kb, status="processing", source_type=extension.lstrip("."))
    db.add(doc_row)
    db.commit()

    try:
        chunks, pages = ingest_by_extension(file_path, file.filename, extension)
        rebuild_bm25_index()
        doc_row.chunk_count = chunks
        doc_row.page_count = pages
        doc_row.status = "indexed"
        db.commit()
    except Exception as e:
        doc_row.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "chunks_indexed": chunks, "pages": pages, "document_id": doc_row.id}


@app.post("/documents/from-url")
def upload_from_url(payload: UrlIngestRequest, db: Session = Depends(get_db)):
    doc_row = Document(filename=payload.url, file_size_kb=0, status="processing", source_type="url")
    db.add(doc_row)
    db.commit()

    try:
        chunks, pages, title = ingest_url(payload.url)
        rebuild_bm25_index()
        doc_row.filename = title or payload.url
        doc_row.chunk_count = chunks
        doc_row.page_count = pages
        doc_row.status = "indexed"
        db.commit()
    except Exception as e:
        doc_row.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "chunks_indexed": chunks, "pages": pages, "document_id": doc_row.id, "title": doc_row.filename}


@app.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_size_kb": d.file_size_kb,
            "page_count": d.page_count,
            "chunk_count": d.chunk_count,
            "status": d.status,
            "source_type": d.source_type or "pdf",
            "uploaded_at": d.uploaded_at.isoformat(),
        }
        for d in docs
    ]


@app.delete("/documents/{document_id}")
def remove_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_document(doc.filename)
    rebuild_bm25_index()
    db.delete(doc)
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------

@app.post("/chat/sessions")
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    session = ChatSession(title=payload.title or "New conversation")
    db.add(session)
    db.commit()
    return {"id": session.id, "title": session.title, "created_at": session.created_at.isoformat()}


@app.get("/chat/sessions")
def list_sessions(db: Session = Depends(get_db)):
    """Powers the chat history sidebar: each session comes back with a
    message count and a preview of the last message so past conversations
    are actually browsable, not just a bare title."""
    sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()
    out = []
    for s in sessions:
        last_msg = (
            db.query(Message)
            .filter(Message.session_id == s.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        msg_count = db.query(Message).filter(Message.session_id == s.id).count()
        out.append({
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "message_count": msg_count,
            "last_message_preview": (last_msg.content[:80] if last_msg else ""),
            "last_active": (last_msg.created_at.isoformat() if last_msg else s.created_at.isoformat()),
        })
    out.sort(key=lambda r: r["last_active"], reverse=True)
    return out


@app.get("/chat/sessions/{session_id}/messages")
def get_session_messages(session_id: str, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.created_at).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "sources": json.loads(m.sources or "[]"),
            "confidence": m.confidence,
            "hops_used": m.hops_used,
            "response_time_ms": m.response_time_ms,
            "feedback": m.feedback,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@app.delete("/chat/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        db.delete(session)
        db.commit()
    return {"status": "deleted"}


@app.post("/chat/messages/{message_id}/feedback")
def set_feedback(message_id: str, payload: FeedbackRequest, db: Session = Depends(get_db)):
    if payload.rating not in (-1, 0, 1):
        raise HTTPException(status_code=400, detail="rating must be -1, 0, or 1")
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.feedback = payload.rating or None
    db.commit()
    return {"status": "ok", "feedback": msg.feedback}


# ---------------------------------------------------------------------------
# Agentic RAG ask endpoint
# ---------------------------------------------------------------------------

@app.post("/ask")
def ask_question(query: QueryRequest, db: Session = Depends(get_db)):
    session_id = query.session_id
    if not session_id:
        session = ChatSession(title=query.question[:60])
        db.add(session)
        db.commit()
        session_id = session.id

    user_msg = Message(session_id=session_id, role="user", content=query.question)
    db.add(user_msg)
    db.commit()

    result = run_agent(query.question)

    assistant_msg = Message(
        session_id=session_id,
        role="assistant",
        content=result["answer"],
        sources=json.dumps(result["documents_used"]),
        confidence=result["confidence"],
        hops_used=result["hops_used"],
        response_time_ms=result["response_time_ms"],
    )
    db.add(assistant_msg)
    db.commit()

    for step in result["trace"]:
        db.add(AgentTrace(
            message_id=assistant_msg.id,
            step_number=step["step_number"],
            step_type=step["step_type"],
            content=step["content"][:2000],
        ))

    db.add(QueryLog(
        question=query.question,
        answer_found=result["answer"] != "Information not found in uploaded documents.",
        confidence=result["confidence"],
        hops_used=result["hops_used"],
        sub_questions=result["sub_questions_count"],
        chunks_retrieved=result["chunks_retrieved"],
        response_time_ms=result["response_time_ms"],
    ))
    db.commit()

    return {**result, "session_id": session_id, "message_id": assistant_msg.id}


@app.get("/chat/messages/{message_id}/trace")
def get_trace(message_id: str, db: Session = Depends(get_db)):
    steps = db.query(AgentTrace).filter(AgentTrace.message_id == message_id).order_by(AgentTrace.step_number).all()
    return [{"step_number": s.step_number, "step_type": s.step_type, "content": s.content} for s in steps]


# ---------------------------------------------------------------------------
# Analytics (real data, not random numbers)
# ---------------------------------------------------------------------------

@app.get("/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)):
    total_documents = db.query(Document).filter(Document.status == "indexed").count()
    total_chunks = collection.count()
    total_queries = db.query(QueryLog).count()

    avg_response_ms = db.query(func.avg(QueryLog.response_time_ms)).scalar() or 0
    avg_confidence = db.query(func.avg(QueryLog.confidence)).scalar() or 0
    answered = db.query(QueryLog).filter(QueryLog.answer_found == True).count()  # noqa: E712
    answer_rate = (answered / total_queries * 100) if total_queries else 0
    avg_hops = db.query(func.avg(QueryLog.hops_used)).scalar() or 0

    total_feedback = db.query(Message).filter(Message.feedback.isnot(None)).count()
    positive_feedback = db.query(Message).filter(Message.feedback == 1).count()
    positive_feedback_rate = round((positive_feedback / total_feedback) * 100, 1) if total_feedback else None

    return {
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "total_queries": total_queries,
        "avg_response_seconds": round(avg_response_ms / 1000, 2),
        "avg_confidence": round(avg_confidence, 3),
        "answer_rate_percent": round(answer_rate, 1),
        "avg_hops_per_query": round(avg_hops, 2),
        "positive_feedback_rate": positive_feedback_rate,
        "total_feedback": total_feedback,
    }


@app.get("/analytics/timeseries")
def analytics_timeseries(db: Session = Depends(get_db)):
    rows = db.query(
        func.date(QueryLog.created_at).label("day"),
        func.count(QueryLog.id).label("queries"),
        func.avg(QueryLog.response_time_ms).label("avg_ms"),
        func.avg(QueryLog.confidence).label("avg_confidence"),
    ).group_by("day").order_by("day").all()

    return [
        {
            "day": str(r.day),
            "queries": r.queries,
            "avg_response_seconds": round((r.avg_ms or 0) / 1000, 2),
            "avg_confidence": round(r.avg_confidence or 0, 3),
        }
        for r in rows
    ]


@app.get("/analytics/documents")
def analytics_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.status == "indexed").all()
    return [{"filename": d.filename, "chunks": d.chunk_count, "pages": d.page_count} for d in docs]


@app.get("/analytics/recent-activity")
def recent_activity(db: Session = Depends(get_db)):
    logs = db.query(QueryLog).order_by(QueryLog.created_at.desc()).limit(10).all()
    return [
        {
            "question": l.question,
            "confidence": l.confidence,
            "hops_used": l.hops_used,
            "response_time_ms": l.response_time_ms,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


# ---------------------------------------------------------------------------
# Runtime settings (Admin panel) -- live-tunable pipeline parameters
# ---------------------------------------------------------------------------

@app.get("/settings")
def get_settings():
    return {
        "current": rs.get_all(),
        "defaults": rs.defaults(),
        "bounds": rs.bounds(),
        "static_info": {
            "embedding_model": config.EMBEDDING_MODEL,
            "reranker_model": config.RERANKER_MODEL,
            "chunk_size": config.CHUNK_SIZE,
            "chunk_overlap": config.CHUNK_OVERLAP,
        },
    }


@app.put("/settings")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")

    try:
        clean = rs.validate(updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rs.set_many(clean)

    row = db.query(RuntimeSettings).filter(RuntimeSettings.id == 1).first()
    if row is None:
        row = RuntimeSettings(id=1)
        db.add(row)
    rs.apply_to_row(row, clean)
    db.commit()

    return {"status": "ok", "updated": clean, "current": rs.get_all()}


@app.post("/settings/reset")
def reset_settings(db: Session = Depends(get_db)):
    defaults = rs.defaults()
    rs.set_many(defaults)
    row = db.query(RuntimeSettings).filter(RuntimeSettings.id == 1).first()
    if row is None:
        row = RuntimeSettings(id=1)
        db.add(row)
    rs.apply_to_row(row, defaults)
    db.commit()
    return {"status": "ok", "current": rs.get_all()}


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

if os.path.isdir("static"):
    app.mount("/assets", StaticFiles(directory="static"), name="assets")

    @app.get("/app")
    def serve_dashboard():
        return FileResponse("static/index.html")
