"""
Compatibility shim.

Some docs/tests in this repo reference `main_v2.py` (e.g. `uvicorn main_v2:app`).
The production implementation lives in `main.py`, so we re-export the public API here.
"""

from main import (  # noqa: F401
    QueryCreate,
    QueryIntelligence,
    QueryRecord,
    app,
    extract_query_intelligence,
    fetch_query,
    heuristic_extract,
    insert_query,
    llm,
    normalize_list,
)

__all__ = [
    "QueryCreate",
    "QueryIntelligence",
    "QueryRecord",
    "app",
    "extract_query_intelligence",
    "fetch_query",
    "heuristic_extract",
    "insert_query",
    "llm",
    "normalize_list",
]

