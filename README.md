# Enterprise Agentic RAG Platform

An enterprise document-intelligence platform that goes beyond basic
"embed → retrieve → generate" RAG. It runs a true **agentic retrieval loop**
on top of a **hybrid search pipeline**, backed by real persistence and a
custom-built analytics dashboard.

## What makes this different from a basic RAG demo

| Basic RAG | This project |
|---|---|
| One-shot vector search, top-5 chunks | **Hybrid retrieval**: dense (vector) + sparse (BM25) search, fused and reranked with a cross-encoder |
| Single embed → answer | **Agentic loop**: the LLM plans sub-questions, retrieves, self-grades its confidence in the retrieved context, and refines the query for another retrieval hop if confidence is too low (up to N hops) |
| Fake dashboard metrics (`random.randint`) | **Real SQL-backed analytics**: every query, its confidence, hop count, response time, and user feedback is logged and charted |
| No persistence | SQLite (swappable to Postgres) stores documents, chat sessions, message history, and a full step-by-step **agent reasoning trace** for explainability |
| Default Streamlit widgets | Custom-built dashboard (vanilla HTML/CSS/JS + Chart.js) with a "control room" visual identity, live agent trace visualization, drag-and-drop upload with real progress, and **searchable chat history** |
| PDF-only ingestion | **Multi-format ingestion**: PDF, DOCX, TXT, Markdown, and live URL scraping, all through the same chunk → embed → index pipeline |
| Fixed, hardcoded knobs | **Live admin panel**: retrieval top-K, hybrid alpha, agent hop limit, confidence threshold, and the Ollama model itself are all tunable at runtime from Settings — no redeploy needed |
| No answer quality signal | **Thumbs up/down feedback** on every answer, rolled up into a "positive feedback rate" KPI on Analytics |

## Architecture

```
┌─────────────┐      ┌──────────────────────────────────────────────┐
│  Dashboard   │ HTTP │                   FastAPI                    │
│ (HTML/JS/CSS)│◄────►│  /upload  /ask  /documents  /chat/*  /analytics│
└─────────────┘      └───────────────┬──────────────────────────────┘
                                      │
                  ┌───────────────────┼───────────────────┐
                  ▼                   ▼                   ▼
            ┌───────────┐     ┌──────────────┐     ┌─────────────┐
            │  ingest.py │     │  agent.py     │     │ database.py │
            │ PDF→chunks │     │ plan→retrieve │     │  SQLite via │
            │ →embeddings│     │ →grade→refine │     │  SQLAlchemy │
            └─────┬─────┘     │ →synthesize    │     └─────────────┘
                  │           └──────┬────────┘
                  ▼                  ▼
            ┌───────────┐     ┌──────────────┐
            │  ChromaDB  │◄───│ retrieval.py  │
            │  (vectors) │     │ vector+BM25+ │
            └───────────┘     │ cross-encoder│
                               └──────┬───────┘
                                      ▼
                               ┌─────────────┐
                               │   Ollama     │
                               │ llama3.2:3b  │
                               └─────────────┘
```

## Tech stack

- **Backend**: FastAPI, SQLAlchemy (SQLite by default, set `DATABASE_URL` for Postgres)
- **Retrieval**: ChromaDB (vectors), `rank-bm25` (keyword search), `sentence-transformers` cross-encoder (reranking)
- **Embeddings**: `all-MiniLM-L6-v2`
- **LLM**: Ollama running `llama3.2:3b` locally (swap the model name in `app/config.py`)
- **Frontend**: vanilla HTML/CSS/JS + Chart.js (no build step required)

## Run it with one click (Windows)

No terminal, no commands. Double-click **`Start Dashboard.bat`**.

- **First run**: it creates a private Python environment and installs
  everything automatically (a few minutes, needs internet). It also checks
  whether Ollama is installed and tells you if it isn't.
- **Every run after that**: it skips setup and opens the dashboard in your
  browser in a couple of seconds.
- To hand this project to someone else, zip the whole folder and send it —
  they just need Python and Ollama installed once, then double-click the
  same `.bat` file.

The one requirement it can't install for you is **Ollama** itself (it's a
separate local LLM engine, not a Python package) — grab it once from
https://ollama.com/download. The launcher pulls the `llama3.2:3b` model
automatically the first time it detects Ollama is present.

## Manual setup (any OS, or if you prefer the terminal)

1. **Install Ollama** and pull the model:
   ```bash
   ollama pull llama3.2:3b
   ollama serve
   ```

2. **Install Python dependencies** (Python 3.10+ recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate   # venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Run the backend** (serves both the API and the dashboard):
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Or, for the same one-click experience as the `.bat` file (starts Ollama,
   pulls the model if needed, opens your browser automatically):
   ```bash
   python launcher.py
   ```

4. Open **http://127.0.0.1:8000/app** in your browser.

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/upload` | Upload a PDF/DOCX/TXT/MD file, chunk + embed + index it |
| `POST` | `/documents/from-url` | Scrape a web page by URL and index its text |
| `GET` | `/documents` | List indexed documents |
| `DELETE` | `/documents/{id}` | Remove a document from the index |
| `POST` | `/ask` | Ask a question; runs the full agentic pipeline |
| `GET` | `/chat/sessions` | List chat sessions with previews, message counts, last-active time |
| `GET` | `/chat/sessions/{id}/messages` | Get message history for a session |
| `DELETE` | `/chat/sessions/{id}` | Delete a conversation |
| `POST` | `/chat/messages/{id}/feedback` | Record thumbs up/down on an answer |
| `GET` | `/chat/messages/{id}/trace` | Get the step-by-step agent reasoning trace |
| `GET` | `/settings` | Get current/default/bounds for live-tunable pipeline settings |
| `PUT` | `/settings` | Update live settings (hops, confidence threshold, top-K, model, etc.) |
| `POST` | `/settings/reset` | Reset live settings to `config.py` defaults |
| `GET` | `/analytics/overview` | Real aggregate KPIs, including positive feedback rate |
| `GET` | `/analytics/timeseries` | Daily query volume / confidence / latency |
| `GET` | `/analytics/recent-activity` | Recent query log |

## How the agent loop works (`app/agent.py`)

1. **Plan** – the LLM decomposes the question into up to 4 focused sub-questions.
2. **Retrieve** – each sub-question runs through hybrid search (`app/retrieval.py`):
   dense vector search + BM25 keyword search, fused, then reranked with a
   cross-encoder for the final top-K chunks.
3. **Grade** – the LLM grades whether the accumulated context is sufficient to
   confidently answer, and what's missing if not.
4. **Refine** – if confidence is below threshold and hops remain, the question
   is rewritten to target the missing information and retrieval runs again.
5. **Synthesize** – the final answer is generated strictly from the retrieved,
   reranked context, with cited source documents.

Every step is persisted to the `agent_traces` table and shown live in the
dashboard's chat view, so the reasoning process is fully transparent — a
strong talking point for interviews ("how does your RAG system avoid
hallucination / handle multi-part questions?").

## Resume / GitHub framing

> Built an enterprise-grade agentic RAG platform with hybrid retrieval
> (dense + sparse + cross-encoder reranking) and a self-grading agent loop
> that performs multi-hop query refinement, reducing unsupported answers by
> grounding every response in reranked, cited document context. Designed a
> custom analytics dashboard backed by SQL-logged query telemetry (confidence,
> latency, hop count) instead of static demo data.

## Project structure

```
app/
  config.py           Deploy-time defaults (chunking, retrieval, agent thresholds)
  runtime_settings.py Live-tunable overrides backing the Settings admin panel
  database.py         SQLAlchemy models: Document, ChatSession, Message, QueryLog, AgentTrace, RuntimeSettings
  ingest.py           PDF/DOCX/TXT/MD/URL → sentence-aware chunking → embeddings → ChromaDB
  retrieval.py        Hybrid (vector + BM25) retrieval + cross-encoder reranking
  agent.py            Agentic plan/retrieve/grade/refine/synthesize loop
  main.py             FastAPI routes
static/
  index.html     Dashboard shell + templates per page
  css/style.css  "Control room" design system
  js/app.js      Client-side router, API calls, Chart.js dashboards
requirements.txt
```
