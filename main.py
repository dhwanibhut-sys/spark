from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path as FastAPIPath
from pydantic import BaseModel, Field

try:
    import anthropic
except ImportError:
    anthropic = None

load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "queries.json"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

app = FastAPI(
    title="Query Intelligence Endpoint",
    description="AI-powered structured extraction from natural language research queries",
    version="2.0.0",
)

llm = (
    anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    if anthropic and ANTHROPIC_API_KEY
    else None
)


# ============================================================================
# Pydantic Models
# ============================================================================


class QueryCreate(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language research query")


class QueryIntelligence(BaseModel):
    search_intent: str = Field(..., description="Short verb-led action phrase")
    summary: str = Field(..., description="One-sentence information need")
    entities: list[str] = Field(
        default_factory=list, description="Organizations, company types"
    )
    sectors: list[str] = Field(
        default_factory=list, description="Industry themes and verticals"
    )
    geographies: list[str] = Field(
        default_factory=list, description="Regions, countries, markets"
    )
    attributes: list[str] = Field(
        default_factory=list, description="Filters: growth stage, funding, traits"
    )
    time_horizon: str | None = Field(
        default=None, description="Time window if specified (e.g., 'last 12 months')"
    )
    output_mode: str = Field(
        default="llm", description="Extraction method used: 'llm' or 'heuristic_fallback'"
    )


class QueryRecord(BaseModel):
    id: str = Field(..., description="Unique query identifier (UUID)")
    query: str = Field(..., description="Original natural language query")
    extracted: QueryIntelligence = Field(..., description="Extracted structured data")
    created_at: str = Field(..., description="ISO 8601 timestamp (UTC)")


class HealthResponse(BaseModel):
    service: str
    status: str
    llm_configured: bool
    storage: str
    model: str | None = None


# ============================================================================
# LLM Tool Definition (Structured Output)
# ============================================================================


INTELLIGENCE_EXTRACTION_TOOL = {
    "name": "extract_query_intelligence",
    "description": "Extract structured intelligence from a research query",
    "input_schema": {
        "type": "object",
        "properties": {
            "search_intent": {
                "type": "string",
                "description": "Short verb-led action phrase (e.g., 'Find', 'Identify', 'List')",
            },
            "summary": {
                "type": "string",
                "description": "One-sentence summary of the user's information need",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Organization or entity types (e.g., 'startups', 'companies', 'VCs')",
            },
            "sectors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Industry themes (e.g., 'battery technology', 'AI', 'fintech')",
            },
            "geographies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Regions, countries, or markets mentioned",
            },
            "attributes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filters like growth stage, funding, or technology traits",
            },
            "time_horizon": {
                "type": ["string", "null"],
                "description": "Time window if mentioned (e.g., 'last 12 months', null if not specified)",
            },
        },
        "required": [
            "search_intent",
            "summary",
            "entities",
            "sectors",
            "geographies",
            "attributes",
        ],
    },
}


# ============================================================================
# Database Functions
# ============================================================================


def init_db() -> None:
    """Initialize the JSON database file if it doesn't exist."""
    if not DB_PATH.exists():
        DB_PATH.write_text("[]", encoding="utf-8")
        logger.info(f"Initialized database at {DB_PATH}")


def load_records() -> list[dict[str, Any]]:
    """Load all query records from disk."""
    init_db()
    try:
        records = json.loads(DB_PATH.read_text(encoding="utf-8"))
        logger.debug(f"Loaded {len(records)} records from database")
        return records
    except json.JSONDecodeError:
        logger.error("Database corruption detected; returning empty list")
        return []


def save_records(records: list[dict[str, Any]]) -> None:
    """Persist query records to disk."""
    try:
        DB_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(records)} records to database")
    except IOError as e:
        logger.error(f"Failed to write to database: {e}")
        raise


def normalize_list(values: list[Any]) -> list[str]:
    """
    Normalize and deduplicate a list of values.

    - Converts to strings, strips whitespace, filters empty values.
    - Case-insensitive deduplication.
    """
    cleaned: list[str] = []
    seen: set[str] = set()

    for value in values:
        if not isinstance(value, str):
            continue

        item = value.strip()
        if not item:
            continue

        key = item.casefold()
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(item)

    return cleaned


# ============================================================================
# Heuristic Extraction (Fallback)
# ============================================================================


def heuristic_extract(query: str) -> QueryIntelligence:
    """
    Fallback extraction using pattern matching.

    Used when LLM is unavailable or extraction fails.
    """
    logger.info("Using heuristic extraction fallback")
    lowered = query.lower()

    # Geography extraction
    geographies = []
    geography_patterns = {
        "Southeast Asia": ["southeast asia", "southeast"],
        "Asia": ["\\basia\\b"],
        "Europe": ["\\beurope\\b"],
        "North America": ["north america"],
        "Latin America": ["latin america"],
        "Africa": ["\\bafrica\\b"],
        "Middle East": ["middle east"],
        "United States": ["united states", "u.s.", "usa"],
        "India": ["\\bindia\\b"],
        "China": ["\\bchina\\b"],
    }

    for place, patterns in geography_patterns.items():
        if any(p in lowered for p in patterns):
            geographies.append(place)

    # Sector extraction
    sectors = []
    sector_patterns = [
        ("battery technology", ["battery", "energy storage"]),
        ("artificial intelligence", ["ai", "artificial intelligence", "machine learning"]),
        ("fintech", ["fintech", "payments", "banking", "finance"]),
        ("healthtech", ["healthtech", "biotech", "digital health", "telemedicine"]),
        ("climate tech", ["climate", "decarbonization", "clean energy", "green tech"]),
        ("quantum computing", ["quantum"]),
        ("biotechnology", ["biotech", "biotech", "genetic", "crispr"]),
    ]

    for sector_name, keywords in sector_patterns:
        if any(keyword in lowered for keyword in keywords):
            sectors.append(sector_name)

    # Entity extraction
    entities = []
    if "startup" in lowered or "startups" in lowered:
        entities.append("startups")
    elif "company" in lowered or "companies" in lowered:
        entities.append("companies")
    else:
        entities.append("organizations")

    # Attribute extraction
    attributes = []
    attribute_patterns = [
        "seed-stage",
        "series a",
        "series b",
        "growth stage",
        "late stage",
        "private company",
        "enterprise",
        "consumer",
        "b2b",
        "b2c",
        "deep tech",
    ]

    for token in attribute_patterns:
        if token in lowered:
            attributes.append(token)

    # Generate summary
    summary_prefix = "Find"
    if lowered.startswith("find "):
        summary_prefix = "Find"
    elif lowered.startswith("list "):
        summary_prefix = "List"
    elif lowered.startswith("identify "):
        summary_prefix = "Identify"
    elif lowered.startswith("search for"):
        summary_prefix = "Search for"

    primary_sector = sectors[0] if sectors else "relevant"
    primary_geo = geographies[0] if geographies else "target markets"
    primary_entity = entities[0] if entities else "organizations"

    return QueryIntelligence(
        search_intent=f"{summary_prefix} {primary_entity}",
        summary=f"{summary_prefix} {primary_sector} {primary_entity} in {primary_geo} matching the specified criteria.",
        entities=normalize_list(entities),
        sectors=normalize_list(sectors) or ["market intelligence"],
        geographies=normalize_list(geographies),
        attributes=normalize_list(attributes),
        time_horizon=None,
        output_mode="heuristic_fallback",
    )


# ============================================================================
# LLM-Based Extraction (Structured via Tool Use)
# ============================================================================


def extract_query_intelligence(query: str) -> QueryIntelligence:
    """
    Extract structured intelligence from a query using Claude with tool use.

    Falls back to heuristic extraction on failure.
    """
    if llm is None:
        logger.warning("LLM not configured; using heuristic extraction")
        return heuristic_extract(query)

    try:
        logger.info(f"Invoking LLM for extraction: {query[:60]}...")

        response = llm.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            temperature=0,  # Deterministic extraction
            tools=[INTELLIGENCE_EXTRACTION_TOOL],
            messages=[
                {
                    "role": "user",
                    "content": f"Extract structured intelligence from this research query:\n\n{query}",
                }
            ],
        )

        # Find tool use block in response
        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use":
                tool_use_block = block
                break

        if tool_use_block is None:
            logger.warning(
                "No tool use block found in LLM response; falling back to heuristic"
            )
            return heuristic_extract(query)

        # Extract the structured data from tool input
        tool_input = tool_use_block.input

        extracted = QueryIntelligence(
            search_intent=str(tool_input.get("search_intent", "")).strip(),
            summary=str(tool_input.get("summary", "")).strip(),
            entities=normalize_list(tool_input.get("entities", [])),
            sectors=normalize_list(tool_input.get("sectors", [])),
            geographies=normalize_list(tool_input.get("geographies", [])),
            attributes=normalize_list(tool_input.get("attributes", [])),
            time_horizon=tool_input.get("time_horizon"),
            output_mode="llm",
        )

        logger.info(
            f"LLM extraction successful: {len(extracted.sectors)} sectors, "
            f"{len(extracted.geographies)} geographies"
        )

        return extracted

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error during extraction: {e}")
        return heuristic_extract(query)
    except Exception as e:
        logger.error(f"Unexpected error during LLM extraction: {e}")
        return heuristic_extract(query)


# ============================================================================
# Query Storage Functions
# ============================================================================


def insert_query(query: str, extracted: QueryIntelligence) -> QueryRecord:
    """Create and persist a new query record."""
    record = QueryRecord(
        id=str(uuid.uuid4()),
        query=query,
        extracted=extracted,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    records = load_records()
    records.append(record.model_dump())
    save_records(records)

    logger.info(f"Query inserted: {record.id}")
    return record


def fetch_query(query_id: str) -> QueryRecord | None:
    """Retrieve a query record by ID."""
    records = load_records()

    for record in records:
        if record.get("id") == query_id:
            logger.debug(f"Query found: {query_id}")
            return QueryRecord.model_validate(record)

    logger.warning(f"Query not found: {query_id}")
    return None


def list_queries(limit: int = 100, offset: int = 0) -> list[QueryRecord]:
    """Retrieve paginated query records."""
    records = load_records()
    paginated = records[offset : offset + limit]
    logger.debug(f"Retrieved {len(paginated)} queries (offset={offset}, limit={limit})")
    return [QueryRecord.model_validate(r) for r in paginated]


# ============================================================================
# FastAPI Event Handlers
# ============================================================================


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database on startup."""
    init_db()
    logger.info(
        f"Service started. LLM: {llm is not None}, Model: {ANTHROPIC_MODEL}, DB: {DB_PATH}"
    )


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/", response_model=HealthResponse, tags=["Health"])
def root() -> HealthResponse:
    """
    Health check endpoint.

    Returns service status and configuration details.
    """
    return HealthResponse(
        service="query-intelligence-endpoint",
        status="ok",
        llm_configured=llm is not None,
        storage=str(DB_PATH.name),
        model=ANTHROPIC_MODEL if llm is not None else None,
    )


@app.post("/queries", response_model=QueryRecord, status_code=201, tags=["Queries"])
def create_query(payload: QueryCreate) -> QueryRecord:
    """
    Create a new query record.

    Accepts a natural language research query, extracts structured intelligence using Claude,
    and persists the result.

    **Request:**
    ```json
    {
      "query": "find battery technology startups in Southeast Asia"
    }
    ```

    **Response (201):**
    ```json
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "query": "find battery technology startups in Southeast Asia",
      "extracted": {
        "search_intent": "Find startups",
        "summary": "Find battery technology startups in Southeast Asia matching the specified criteria.",
        "entities": ["startups"],
        "sectors": ["battery technology"],
        "geographies": ["Southeast Asia"],
        "attributes": [],
        "time_horizon": null,
        "output_mode": "llm"
      },
      "created_at": "2026-05-17T12:34:56.789000+00:00"
    }
    ```
    """
    logger.info(f"POST /queries: {payload.query[:60]}...")

    extracted = extract_query_intelligence(payload.query)
    record = insert_query(payload.query, extracted)

    logger.info(f"Query created: {record.id}")
    return record


@app.get("/queries/{query_id}", response_model=QueryRecord, tags=["Queries"])
def get_query(
    query_id: str = FastAPIPath(..., description="Query record identifier (UUID)")
) -> QueryRecord:
    """
    Retrieve a specific query record by ID.

    **Response (200):**
    ```json
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "query": "find battery technology startups in Southeast Asia",
      "extracted": { ... },
      "created_at": "2026-05-17T12:34:56.789000+00:00"
    }
    ```

    **Response (404):** Query not found
    """
    logger.info(f"GET /queries/{query_id}")

    record = fetch_query(query_id)
    if record is None:
        logger.warning(f"Query not found: {query_id}")
        raise HTTPException(status_code=404, detail="Query not found")

    return record


@app.get("/queries", response_model=list[QueryRecord], tags=["Queries"])
def list_all_queries(limit: int = 100, offset: int = 0) -> list[QueryRecord]:
    """
    Retrieve all query records with pagination.

    **Query Parameters:**
    - `limit`: Maximum number of records to return (default: 100)
    - `offset`: Number of records to skip (default: 0)

    **Response (200):**
    ```json
    [
      { ... },
      { ... }
    ]
    ```
    """
    logger.info(f"GET /queries (limit={limit}, offset={offset})")

    return list_queries(limit=limit, offset=offset)


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler with logging."""
    logger.error(f"HTTP Exception: {exc.status_code} - {exc.detail}")
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    logger.info("Starting Query Intelligence Endpoint...")
