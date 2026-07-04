"""
The "agentic" part of the platform.

Instead of one-shot "embed question -> retrieve 5 chunks -> answer", the
agent runs a planning / retrieval / self-grading loop:

  1. PLAN        - decompose the user's question into focused sub-questions
                   (handles multi-part / comparison questions properly).
  2. RETRIEVE    - hybrid search (vector + BM25 + cross-encoder rerank) for
                   each sub-question.
  3. GRADE       - the LLM grades whether the gathered context is sufficient
                   to answer confidently, and what's still missing.
  4. REFINE      - if confidence is below threshold and hops remain, the
                   agent rewrites the query to target the missing
                   information and retrieves again (up to MAX_AGENT_HOPS).
  5. SYNTHESIZE  - final grounded answer is generated only from accumulated,
                   reranked context, citing which documents were used.

Every step is recorded so the dashboard can show a transparent trace of how
the agent reached its answer (a core "explainability" selling point).
"""
import json
import re
import time

import requests

from app import config, runtime_settings as rs
from app.retrieval import hybrid_retrieve


class AgentTraceRecorder:
    """Lightweight in-memory recorder; main.py persists this to AgentTrace rows."""

    def __init__(self):
        self.steps = []

    def add(self, step_type, content):
        self.steps.append({"step_number": len(self.steps) + 1, "step_type": step_type, "content": content})


def _call_llm(prompt: str, timeout: int = 120) -> str:
    response = requests.post(
        config.OLLAMA_URL,
        json={"model": rs.get("OLLAMA_MODEL"), "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


def _extract_json(text: str):
    """Ollama models don't always return clean JSON -- pull the first {...} block."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def plan_subquestions(question: str, trace: AgentTraceRecorder):
    max_subq = rs.get("MAX_SUBQUESTIONS")
    prompt = f"""Break the following user question into 1-{max_subq} focused
sub-questions needed to fully answer it. If the question is already simple
and single-part, return it unchanged as the only sub-question.

Respond ONLY with JSON in this exact format, no other text:
{{"sub_questions": ["...", "..."]}}

User question: {question}
"""
    raw = _call_llm(prompt)
    parsed = _extract_json(raw)

    if parsed and isinstance(parsed.get("sub_questions"), list) and parsed["sub_questions"]:
        sub_qs = [q.strip() for q in parsed["sub_questions"] if q.strip()][:max_subq]
    else:
        sub_qs = [question]

    trace.add("plan", json.dumps({"sub_questions": sub_qs}))
    return sub_qs


def grade_context(question: str, context: str, trace: AgentTraceRecorder):
    prompt = f"""You are grading whether the CONTEXT below contains enough
information to confidently and completely answer the QUESTION.

Respond ONLY with JSON, no other text:
{{"confidence": <float 0.0-1.0>, "missing_info": "<short description or empty string>"}}

QUESTION: {question}

CONTEXT:
{context}
"""
    raw = _call_llm(prompt)
    parsed = _extract_json(raw)

    if parsed and "confidence" in parsed:
        try:
            confidence = float(parsed["confidence"])
        except (TypeError, ValueError):
            confidence = 0.5
        missing = parsed.get("missing_info", "")
    else:
        confidence, missing = 0.5, ""

    trace.add("grade", json.dumps({"confidence": confidence, "missing_info": missing}))
    return confidence, missing


def synthesize_answer(question: str, context: str, trace: AgentTraceRecorder):
    prompt = f"""You are an enterprise document analyst. Answer the QUESTION
using ONLY the CONTEXT below. Be precise and well-structured. If the context
is genuinely insufficient, say exactly:
"Information not found in uploaded documents."

CONTEXT:
{context}

QUESTION: {question}

ANSWER:
"""
    answer = _call_llm(prompt)
    trace.add("synthesize", answer[:500])
    return answer


def run_agent(question: str):
    """Main entry point used by the API layer. Returns answer + full metadata."""
    start = time.time()
    trace = AgentTraceRecorder()

    sub_questions = plan_subquestions(question, trace)

    collected_chunks = {}  # id -> chunk dict, de-duplicated across hops/subquestions
    hops_used = 0
    max_hops = rs.get("MAX_AGENT_HOPS")
    min_confidence = rs.get("MIN_CONFIDENCE_TO_STOP")

    for hop in range(max_hops):
        hops_used += 1
        hop_queries = sub_questions if hop == 0 else [question]  # refine hops re-search the main question

        for sub_q in hop_queries:
            hits = hybrid_retrieve(sub_q)
            trace.add("retrieve", json.dumps({
                "query": sub_q,
                "hop": hop + 1,
                "hits": [{"source": h["meta"]["source"], "page": h["meta"]["page"],
                          "score": round(h["rerank_score"], 3)} for h in hits],
            }))
            for h in hits:
                collected_chunks[h["id"]] = h

        ranked_chunks = sorted(collected_chunks.values(), key=lambda c: c["rerank_score"], reverse=True)
        context = "\n\n".join(
            f"[Source: {c['meta']['source']} | Page {c['meta']['page']}]\n{c['text']}" for c in ranked_chunks
        )

        if not context:
            confidence, missing = 0.0, "no documents indexed"
            trace.add("grade", json.dumps({"confidence": confidence, "missing_info": missing}))
        else:
            confidence, missing = grade_context(question, context, trace)

        if confidence >= min_confidence or hop == max_hops - 1 or not context:
            break

        # REFINE: rewrite the question to target the missing information for the next hop
        trace.add("refine", f"Confidence {confidence:.2f} below threshold; targeting: {missing}")
        question_for_next_hop = f"{question} (focus specifically on: {missing})" if missing else question
        sub_questions = [question_for_next_hop]

    ranked_chunks = sorted(collected_chunks.values(), key=lambda c: c["rerank_score"], reverse=True)
    final_context = "\n\n".join(
        f"[Source: {c['meta']['source']} | Page {c['meta']['page']}]\n{c['text']}" for c in ranked_chunks[:8]
    )

    if not final_context:
        answer = "Information not found in uploaded documents."
        trace.add("synthesize", answer)
    else:
        answer = synthesize_answer(question, final_context, trace)

    unique_sources = []
    for c in ranked_chunks[:8]:
        name = c["meta"]["source"]
        if name not in unique_sources:
            unique_sources.append(name)

    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "answer": answer,
        "documents_used": unique_sources,
        "sources": [c["meta"] for c in ranked_chunks[:8]],
        "confidence": round(confidence if ranked_chunks else 0.0, 3),
        "hops_used": hops_used,
        "sub_questions_count": len(sub_questions) if sub_questions else 1,
        "chunks_retrieved": len(ranked_chunks),
        "response_time_ms": elapsed_ms,
        "trace": trace.steps,
    }
