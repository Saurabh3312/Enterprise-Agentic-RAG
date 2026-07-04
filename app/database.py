"""
Persistence layer (SQLite by default, swappable to Postgres via DATABASE_URL).
Real tables for documents, chat sessions, messages, agent trace logs and
query analytics -- replaces the previous "random.randint()" fake metrics.
"""
import datetime
import uuid

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from app import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def gen_id():
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_id)
    filename = Column(String, nullable=False)
    file_size_kb = Column(Float, default=0)
    page_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    status = Column(String, default="processing")  # processing | indexed | failed
    source_type = Column(String, default="pdf")     # pdf | docx | txt | md | url
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=gen_id)
    title = Column(String, default="New conversation")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_id)
    session_id = Column(String, ForeignKey("chat_sessions.id"))
    role = Column(String)  # user | assistant
    content = Column(Text)
    sources = Column(Text, default="[]")        # JSON list of source filenames
    confidence = Column(Float, default=None)
    hops_used = Column(Integer, default=None)
    response_time_ms = Column(Integer, default=None)
    feedback = Column(Integer, default=None)     # 1 = thumbs up, -1 = thumbs down, None = no feedback
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class QueryLog(Base):
    """One row per /ask call -- powers the real analytics dashboard."""
    __tablename__ = "query_logs"

    id = Column(String, primary_key=True, default=gen_id)
    question = Column(Text)
    answer_found = Column(Boolean, default=True)
    confidence = Column(Float, default=0)
    hops_used = Column(Integer, default=1)
    sub_questions = Column(Integer, default=1)
    chunks_retrieved = Column(Integer, default=0)
    response_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentTrace(Base):
    """Stores the step-by-step reasoning trace for transparency/explainability."""
    __tablename__ = "agent_traces"

    id = Column(String, primary_key=True, default=gen_id)
    message_id = Column(String, ForeignKey("messages.id"))
    step_number = Column(Integer)
    step_type = Column(String)   # plan | retrieve | rerank | grade | refine | synthesize
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RuntimeSettings(Base):
    """Singleton row (id=1) holding live-tunable pipeline parameters set from
    the Settings/Admin panel. Values here override app.config defaults at
    runtime without needing a redeploy."""
    __tablename__ = "runtime_settings"

    id = Column(Integer, primary_key=True)
    ollama_model = Column(String, nullable=True)
    max_agent_hops = Column(Integer, nullable=True)
    min_confidence_to_stop = Column(Float, nullable=True)
    max_subquestions = Column(Integer, nullable=True)
    hybrid_alpha = Column(Float, nullable=True)
    vector_top_k = Column(Integer, nullable=True)
    bm25_top_k = Column(Integer, nullable=True)
    rerank_top_k = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


def _ensure_new_columns():
    """Lightweight migration for existing SQLite DBs created before this
    feature set existed -- adds new columns in place instead of requiring a
    full DB reset."""
    if not config.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        doc_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(documents)")}
        if "source_type" not in doc_cols:
            conn.exec_driver_sql("ALTER TABLE documents ADD COLUMN source_type VARCHAR DEFAULT 'pdf'")

        msg_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(messages)")}
        if "feedback" not in msg_cols:
            conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN feedback INTEGER")

        conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_new_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
