"""
Live-tunable pipeline settings.

app/config.py holds the *default* values baked in at deploy time. This
module holds the *current* values, seeded from config.py, optionally
overridden by whatever's saved in the RuntimeSettings DB row, and editable
at runtime from the Settings/Admin panel (PUT /settings) without a restart.

Everything is cached in a plain in-memory dict for hot-path speed (the
agent loop and retrieval call these on every single request), and mirrored
to the DB so changes survive a restart.
"""
from app import config

# key -> (default value, validator)
_SCHEMA = {
    "OLLAMA_MODEL": (config.OLLAMA_MODEL, str),
    "MAX_AGENT_HOPS": (config.MAX_AGENT_HOPS, int),
    "MIN_CONFIDENCE_TO_STOP": (config.MIN_CONFIDENCE_TO_STOP, float),
    "MAX_SUBQUESTIONS": (config.MAX_SUBQUESTIONS, int),
    "HYBRID_ALPHA": (config.HYBRID_ALPHA, float),
    "VECTOR_TOP_K": (config.VECTOR_TOP_K, int),
    "BM25_TOP_K": (config.BM25_TOP_K, int),
    "RERANK_TOP_K": (config.RERANK_TOP_K, int),
}

# sensible edit bounds so the admin panel can't be used to break the pipeline
_BOUNDS = {
    "MAX_AGENT_HOPS": (1, 6),
    "MIN_CONFIDENCE_TO_STOP": (0.1, 0.99),
    "MAX_SUBQUESTIONS": (1, 8),
    "HYBRID_ALPHA": (0.0, 1.0),
    "VECTOR_TOP_K": (3, 50),
    "BM25_TOP_K": (3, 50),
    "RERANK_TOP_K": (2, 20),
}

_cache = {k: v[0] for k, v in _SCHEMA.items()}


def get(key: str):
    return _cache.get(key, _SCHEMA.get(key, (None,))[0])


def get_all() -> dict:
    return dict(_cache)


def defaults() -> dict:
    return {k: v[0] for k, v in _SCHEMA.items()}


def bounds() -> dict:
    return dict(_BOUNDS)


def validate(updates: dict) -> dict:
    """Coerces + clamps incoming values, raising ValueError on bad keys/types."""
    clean = {}
    for key, value in updates.items():
        if key not in _SCHEMA:
            raise ValueError(f"Unknown setting: {key}")
        _, caster = _SCHEMA[key]
        try:
            value = caster(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid value for {key}: {value!r}")
        if key in _BOUNDS:
            lo, hi = _BOUNDS[key]
            value = max(lo, min(hi, value))
        clean[key] = value
    return clean


def set_many(updates: dict):
    _cache.update(updates)


def load_from_row(row):
    """Seeds the cache from a RuntimeSettings DB row (any non-null field
    wins over the config.py default)."""
    if row is None:
        return
    mapping = {
        "OLLAMA_MODEL": row.ollama_model,
        "MAX_AGENT_HOPS": row.max_agent_hops,
        "MIN_CONFIDENCE_TO_STOP": row.min_confidence_to_stop,
        "MAX_SUBQUESTIONS": row.max_subquestions,
        "HYBRID_ALPHA": row.hybrid_alpha,
        "VECTOR_TOP_K": row.vector_top_k,
        "BM25_TOP_K": row.bm25_top_k,
        "RERANK_TOP_K": row.rerank_top_k,
    }
    for key, value in mapping.items():
        if value is not None:
            _cache[key] = value


def apply_to_row(row, updates: dict):
    """Writes cache updates onto a RuntimeSettings DB row's columns."""
    col_map = {
        "OLLAMA_MODEL": "ollama_model",
        "MAX_AGENT_HOPS": "max_agent_hops",
        "MIN_CONFIDENCE_TO_STOP": "min_confidence_to_stop",
        "MAX_SUBQUESTIONS": "max_subquestions",
        "HYBRID_ALPHA": "hybrid_alpha",
        "VECTOR_TOP_K": "vector_top_k",
        "BM25_TOP_K": "bm25_top_k",
        "RERANK_TOP_K": "rerank_top_k",
    }
    for key, value in updates.items():
        setattr(row, col_map[key], value)
