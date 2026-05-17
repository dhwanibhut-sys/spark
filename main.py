from __future__ import annotations

import json
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

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "queries.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

app = FastAPI(title="Query Intelligence Endpoint")
llm = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if anthropic and ANTHROPIC_API_KEY else None


class QueryCreate(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language research query")


class QueryIntelligence(BaseModel):
    search_intent: str
    summary: str
    entities: list[str]
    sectors: list[str]
    geographies: list[str]
    attributes: list[str]
    time_horizon: str | None = None
    output_mode: str = "llm"


class QueryRecord(BaseModel):
    id: str
    query: str
    extracted: QueryIntelligence
    created_at: str


class HealthResponse(BaseModel):
    service: str
    status: str
    llm_configured: bool
    storage: str


EXTRACTION_PROMPT = """You extract structured intelligence from research queries.
Return JSON only with this exact schema:
{
  "search_intent": string,
  "summary": string,
  "entities": [string],
  "sectors": [string],
  "geographies": [string],
  "attributes": [string],
  "time_horizon": string|null
}

Rules:
- Keep arrays concise and deduplicated.
- `search_intent` should be a short verb-led phrase.
- `summary` should be one sentence describing the user's information need.
- Put company or organization types into `entities`.
- Put industry themes into `sectors`.
- Put regions, countries, or markets into `geographies`.
- Put filters such as growth stage, technology, funding, or product traits into `attributes`.
"""


def init_db() -> None:
    if not DB_PATH.exists():
        DB_PATH.write_text("[]", encoding="utf-8")


def load_records() -> list[dict[str, Any]]:
    init_db()
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def save_records(records: list[dict[str, Any]]) -> None:
    DB_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def normalize_list(values: list[Any]) -> list[str]:
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


def extract_json_from_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def heuristic_extract(query: str) -> QueryIntelligence:
    lowered = query.lower()
    geographies = []
    for place in [
        "Southeast Asia",
        "Asia",
        "Europe",
        "North America",
        "Latin America",
        "Africa",
        "Middle East",
        "United States",
        "India",
        "China",
    ]:
        if place.lower() in lowered:
            geographies.append(place)

    sectors = []
    for sector in [
        ("battery technology", ["battery", "technology"]),
        ("artificial intelligence", ["ai", "artificial intelligence"]),
        ("fintech", ["fintech", "payments", "banking"]),
        ("healthtech", ["healthtech", "biotech", "digital health"]),
        ("climate tech", ["climate", "decarbonization", "clean energy"]),
    ]:
        name, keywords = sector
        if any(keyword in lowered for keyword in keywords):
            sectors.append(name)

    entities = []
    if "startup" in lowered or "startups" in lowered:
        entities.append("startups")
    elif "company" in lowered or "companies" in lowered:
        entities.append("companies")
    else:
        entities.append("organizations")

    attributes = []
    for token in [
        "battery",
        "technology",
        "seed-stage",
        "series a",
        "growth stage",
        "private company",
        "enterprise",
        "consumer",
    ]:
        if token in lowered:
            attributes.append(token)

    summary_prefix = "Identify"
    if lowered.startswith("find "):
        summary_prefix = "Find"
    elif lowered.startswith("list "):
        summary_prefix = "List"

    primary_sector = sectors[0] if sectors else "relevant"
    primary_geo = geographies[0] if geographies else "target"
    return QueryIntelligence(
        search_intent=f"Identify {entities[0]} matching the query",
        summary=f"{summary_prefix} {primary_sector} {entities[0]} in {primary_geo} that match the requested filters.",
        entities=normalize_list(entities),
        sectors=normalize_list(sectors) or ["market intelligence"],
        geographies=normalize_list(geographies),
        attributes=normalize_list(attributes),
        time_horizon=None,
        output_mode="heuristic_fallback",
    )


def extract_query_intelligence(query: str) -> QueryIntelligence:
    if llm is None:
        return heuristic_extract(query)

    try:
        response = llm.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            temperature=0,
            system=EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        payload = extract_json_from_text("\n".join(text_blocks))
        return QueryIntelligence(
            search_intent=str(payload["search_intent"]).strip(),
            summary=str(payload["summary"]).strip(),
            entities=normalize_list(payload.get("entities", [])),
            sectors=normalize_list(payload.get("sectors", [])),
            geographies=normalize_list(payload.get("geographies", [])),
            attributes=normalize_list(payload.get("attributes", [])),
            time_horizon=payload.get("time_horizon"),
            output_mode="llm",
        )
    except Exception:
        return heuristic_extract(query)


def insert_query(query: str, extracted: QueryIntelligence) -> QueryRecord:
    record = QueryRecord(
        id=str(uuid.uuid4()),
        query=query,
        extracted=extracted,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    records = load_records()
    records.append(record.model_dump())
    save_records(records)
    return record


def fetch_query(query_id: str) -> QueryRecord | None:
    records = load_records()
    for record in records:
        if record["id"] == query_id:
            return QueryRecord.model_validate(record)
    return None


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(
        service="query-intelligence-endpoint",
        status="ok",
        llm_configured=llm is not None,
        storage=str(DB_PATH.name),
    )


@app.post("/queries", response_model=QueryRecord, status_code=201)
def create_query(payload: QueryCreate) -> QueryRecord:
    extracted = extract_query_intelligence(payload.query)
    return insert_query(payload.query, extracted)


@app.get("/queries/{query_id}", response_model=QueryRecord)
def get_query(query_id: str = FastAPIPath(..., description="Query record identifier")) -> QueryRecord:
    record = fetch_query(query_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Query not found")
    return record
