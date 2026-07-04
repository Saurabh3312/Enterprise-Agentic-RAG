"""
Central configuration for the Enterprise Agentic RAG Platform.
All tunables live here so the rest of the codebase never hardcodes paths/values.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Storage paths ----
UPLOAD_DIR = BASE_DIR / "uploads"
CHROMA_DIR = BASE_DIR / "chromadb"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'enterprise_rag.db'}")

UPLOAD_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

# ---- Embedding / Reranking models ----
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ---- LLM (Ollama) ----
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# ---- Chunking ----
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120

# ---- Hybrid retrieval ----
VECTOR_TOP_K = 15        # candidates pulled from vector store
BM25_TOP_K = 15           # candidates pulled from keyword index
RERANK_TOP_K = 6          # final chunks kept after cross-encoder rerank
HYBRID_ALPHA = 0.55       # weight given to vector score vs bm25 score (0..1)

# ---- Agent loop ----
MAX_AGENT_HOPS = 3                 # max retrieval iterations per question
MIN_CONFIDENCE_TO_STOP = 0.62      # self-grading confidence threshold (0..1)
MAX_SUBQUESTIONS = 4

# ---- API ----
API_TITLE = "Enterprise Agentic RAG Platform"
API_VERSION = "4.0.0"
CORS_ORIGINS = ["*"]
