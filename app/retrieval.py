"""
Hybrid retrieval engine.

Novelty vs the original single-vector-search RAG:
  1. Dense (vector) search via ChromaDB/MiniLM embeddings -- good at semantics.
  2. Sparse (BM25) keyword search over the same corpus -- good at exact terms,
     IDs, acronyms, numbers that embeddings often blur.
  3. Scores are normalized and combined (HYBRID_ALPHA controls the blend).
  4. The merged candidate pool is then reranked with a cross-encoder, which
     scores (question, chunk) pairs jointly and is far more accurate than
     either retriever alone at picking the final top-K context.
"""
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app import config, runtime_settings as rs
from app.ingest import collection, _embedder

_reranker = CrossEncoder(config.RERANKER_MODEL)

_bm25_index = None
_bm25_corpus_ids = []
_bm25_corpus_docs = []
_bm25_corpus_meta = []


def _tokenize(text: str):
    return text.lower().split()


def rebuild_bm25_index():
    """Pulls the full corpus from Chroma and rebuilds an in-memory BM25 index.
    Called after every ingest/delete so keyword search always matches the
    current knowledge base."""
    global _bm25_index, _bm25_corpus_ids, _bm25_corpus_docs, _bm25_corpus_meta

    data = collection.get(include=["documents", "metadatas"])
    _bm25_corpus_ids = data["ids"]
    _bm25_corpus_docs = data["documents"]
    _bm25_corpus_meta = data["metadatas"]

    if not _bm25_corpus_docs:
        _bm25_index = None
        return

    tokenized = [_tokenize(doc) for doc in _bm25_corpus_docs]
    _bm25_index = BM25Okapi(tokenized)


def _normalize(scores):
    if not scores:
        return scores
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.5 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def _vector_search(query: str, top_k: int):
    if collection.count() == 0:
        return {}

    embedding = _embedder.encode(query).tolist()
    results = collection.query(query_embeddings=[embedding], n_results=min(top_k, collection.count()))

    out = {}
    if not results["ids"][0]:
        return out

    distances = results["distances"][0]
    similarities = [1 - d for d in distances]  # cosine distance -> similarity
    norm = _normalize(similarities)

    for i, doc_id in enumerate(results["ids"][0]):
        out[doc_id] = {
            "text": results["documents"][0][i],
            "meta": results["metadatas"][0][i],
            "vector_score": norm[i],
        }
    return out


def _bm25_search(query: str, top_k: int):
    if _bm25_index is None:
        rebuild_bm25_index()
    if _bm25_index is None:
        return {}

    scores = _bm25_index.get_scores(_tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    raw_scores = [scores[i] for i in ranked]
    norm = _normalize(raw_scores)

    out = {}
    for rank_pos, idx in enumerate(ranked):
        doc_id = _bm25_corpus_ids[idx]
        out[doc_id] = {
            "text": _bm25_corpus_docs[idx],
            "meta": _bm25_corpus_meta[idx],
            "bm25_score": norm[rank_pos],
        }
    return out


def hybrid_retrieve(query: str, top_k: int = None):
    """Runs dense + sparse retrieval, fuses scores, then cross-encoder reranks."""
    if top_k is None:
        top_k = rs.get("RERANK_TOP_K")
    vector_hits = _vector_search(query, rs.get("VECTOR_TOP_K"))
    bm25_hits = _bm25_search(query, rs.get("BM25_TOP_K"))

    merged = {}
    for doc_id, info in vector_hits.items():
        merged[doc_id] = {**info, "bm25_score": 0.0}
    for doc_id, info in bm25_hits.items():
        if doc_id in merged:
            merged[doc_id]["bm25_score"] = info["bm25_score"]
        else:
            merged[doc_id] = {**info, "vector_score": 0.0}

    if not merged:
        return []

    candidates = []
    alpha = rs.get("HYBRID_ALPHA")
    for doc_id, info in merged.items():
        fused = alpha * info.get("vector_score", 0.0) + \
            (1 - alpha) * info.get("bm25_score", 0.0)
        candidates.append({"id": doc_id, "text": info["text"], "meta": info["meta"], "fused_score": fused})

    candidates.sort(key=lambda c: c["fused_score"], reverse=True)
    pool = candidates[: max(top_k * 3, 10)]  # widen pool before cross-encoder rerank

    if not pool:
        return []

    pairs = [[query, c["text"]] for c in pool]
    rerank_scores = _reranker.predict(pairs).tolist()

    for c, score in zip(pool, rerank_scores):
        c["rerank_score"] = float(score)

    pool.sort(key=lambda c: c["rerank_score"], reverse=True)
    return pool[:top_k]
