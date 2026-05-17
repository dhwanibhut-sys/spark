"""
Test suite for Query Intelligence Endpoint.

Covers:
- Unit tests for extraction and normalization
- Integration tests for API endpoints
- Mock tests for LLM failure scenarios
- Edge cases and validation
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# We'll use the main.py module
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from main_v2 import (
    QueryCreate,
    QueryIntelligence,
    QueryRecord,
    app,
    extract_query_intelligence,
    fetch_query,
    heuristic_extract,
    insert_query,
    normalize_list,
)

client = TestClient(app)


# ============================================================================
# Unit Tests: normalize_list
# ============================================================================


class TestNormalizeList:
    """Test the normalize_list function."""

    def test_basic_normalization(self):
        """Test basic list normalization."""
        result = normalize_list(["  Battery  ", "  Technology  "])
        assert result == ["Battery", "Technology"]

    def test_deduplication(self):
        """Test case-insensitive deduplication."""
        result = normalize_list(["AI", "ai", "AI", "Artificial Intelligence"])
        assert len(result) == 2
        assert "AI" in result or "ai" in result
        assert "Artificial Intelligence" in result

    def test_empty_string_filtering(self):
        """Test that empty and whitespace-only strings are filtered."""
        result = normalize_list(["  ", "", "Valid"])
        assert result == ["Valid"]

    def test_non_string_filtering(self):
        """Test that non-string values are skipped."""
        result = normalize_list([123, "Valid", None, "Another"])
        assert result == ["Valid", "Another"]

    def test_empty_list(self):
        """Test handling of empty input list."""
        result = normalize_list([])
        assert result == []


# ============================================================================
# Unit Tests: Heuristic Extraction
# ============================================================================


class TestHeuristicExtraction:
    """Test the heuristic_extract function."""

    def test_battery_startup_query(self):
        """Test extraction of battery startup query."""
        query = "find battery technology startups in Southeast Asia"
        result = heuristic_extract(query)

        assert result.output_mode == "heuristic_fallback"
        assert "startup" in result.entities or "startups" in result.entities
        assert any("battery" in s.lower() for s in result.sectors)
        assert "Southeast Asia" in result.geographies

    def test_ai_company_query(self):
        """Test extraction of AI company query."""
        query = "list AI companies in Europe"
        result = heuristic_extract(query)

        assert "companies" in result.entities
        assert any("ai" in s.lower() for s in result.sectors)
        assert "Europe" in result.geographies

    def test_fintech_query(self):
        """Test extraction of fintech query."""
        query = "identify fintech startups in India"
        result = heuristic_extract(query)

        assert "startups" in result.entities
        assert any("fintech" in s.lower() for s in result.sectors)
        assert "India" in result.geographies

    def test_minimal_query(self):
        """Test extraction of minimal query."""
        query = "startups"
        result = heuristic_extract(query)

        # Should still return valid structure
        assert isinstance(result, QueryIntelligence)
        assert result.entities is not None
        assert result.sectors is not None
        assert result.output_mode == "heuristic_fallback"

    def test_summary_generation(self):
        """Test that summary is always generated."""
        query = "find battery tech startups"
        result = heuristic_extract(query)

        assert len(result.summary) > 0
        assert result.search_intent is not None


# ============================================================================
# Unit Tests: Pydantic Models
# ============================================================================


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_query_create_valid(self):
        """Test valid QueryCreate."""
        qc = QueryCreate(query="find startups in Asia")
        assert qc.query == "find startups in Asia"

    def test_query_create_too_short(self):
        """Test QueryCreate with query too short."""
        with pytest.raises(ValueError):
            QueryCreate(query="ab")

    def test_query_intelligence_valid(self):
        """Test valid QueryIntelligence."""
        qi = QueryIntelligence(
            search_intent="Find startups",
            summary="Find AI startups in Asia",
            entities=["startups"],
            sectors=["AI"],
            geographies=["Asia"],
            attributes=["seed-stage"],
        )
        assert qi.search_intent == "Find startups"
        assert qi.output_mode == "llm"  # default

    def test_query_record_valid(self):
        """Test valid QueryRecord."""
        from datetime import datetime, timezone

        qi = QueryIntelligence(
            search_intent="Find",
            summary="Test",
            entities=["startups"],
            sectors=["tech"],
            geographies=[],
            attributes=[],
        )
        qr = QueryRecord(
            id="123e4567-e89b-12d3-a456-426614174000",
            query="find AI startups",
            extracted=qi,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        assert qr.id == "123e4567-e89b-12d3-a456-426614174000"


# ============================================================================
# Integration Tests: API Endpoints
# ============================================================================


class TestAPIEndpoints:
    """Test FastAPI endpoints."""

    def test_health_check(self):
        """Test GET / health check."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["service"] == "query-intelligence-endpoint"
        assert data["status"] == "ok"
        assert "llm_configured" in data
        assert "storage" in data

    def test_create_query_heuristic_mode(self):
        """Test POST /queries with heuristic extraction (no LLM)."""
        with patch("main_v2.llm", None):
            response = client.post(
                "/queries",
                json={"query": "find battery technology startups in Southeast Asia"},
            )

            assert response.status_code == 201

            data = response.json()
            assert "id" in data
            assert data["query"] == "find battery technology startups in Southeast Asia"
            assert data["extracted"]["output_mode"] == "heuristic_fallback"
            assert len(data["extracted"]["sectors"]) > 0
            assert len(data["extracted"]["geographies"]) > 0
            assert "created_at" in data

    def test_create_query_invalid_input(self):
        """Test POST /queries with invalid input."""
        response = client.post("/queries", json={"query": "ab"})
        assert response.status_code == 422  # Validation error

    def test_create_query_missing_field(self):
        """Test POST /queries with missing required field."""
        response = client.post("/queries", json={})
        assert response.status_code == 422

    def test_get_query_success(self):
        """Test GET /queries/{id} for existing query."""
        # First create a query
        create_response = client.post(
            "/queries", json={"query": "find AI startups in India"}
        )
        assert create_response.status_code == 201

        query_id = create_response.json()["id"]

        # Then retrieve it
        get_response = client.get(f"/queries/{query_id}")
        assert get_response.status_code == 200

        data = get_response.json()
        assert data["id"] == query_id
        assert data["query"] == "find AI startups in India"

    def test_get_query_not_found(self):
        """Test GET /queries/{id} for non-existent query."""
        response = client.get("/queries/non-existent-id")
        assert response.status_code == 404

    def test_list_queries_empty(self):
        """Test GET /queries when no queries exist."""
        # In a fresh state or with mocking
        response = client.get("/queries?limit=10&offset=0")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_queries_with_pagination(self):
        """Test GET /queries with pagination parameters."""
        response = client.get("/queries?limit=5&offset=0")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) <= 5


# ============================================================================
# Integration Tests: LLM Interaction
# ============================================================================


class TestLLMExtraction:
    """Test LLM-based extraction."""

    @patch("main_v2.llm")
    def test_extraction_with_mock_llm(self, mock_llm):
        """Test extraction with mocked LLM response."""
        # Mock the Anthropic API response
        mock_response = MagicMock()
        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.input = {
            "search_intent": "Find startups",
            "summary": "Find battery startups in Asia",
            "entities": ["startups"],
            "sectors": ["battery technology"],
            "geographies": ["Asia"],
            "attributes": ["seed-stage"],
            "time_horizon": None,
        }

        mock_response.content = [mock_tool_use]
        mock_llm.messages.create.return_value = mock_response

        # Test extraction
        result = extract_query_intelligence("find battery startups in Asia")

        assert result.output_mode == "llm"
        assert result.search_intent == "Find startups"
        assert "startups" in result.entities
        assert "battery technology" in result.sectors

    @patch("main_v2.llm")
    def test_extraction_fallback_on_api_error(self, mock_llm):
        """Test fallback to heuristic on API error."""
        import anthropic

        mock_llm.messages.create.side_effect = anthropic.APIError(
            "API Error", response=None, body=None
        )

        result = extract_query_intelligence("find battery startups in Asia")

        assert result.output_mode == "heuristic_fallback"
        assert len(result.sectors) > 0

    @patch("main_v2.llm")
    def test_extraction_fallback_no_tool_use(self, mock_llm):
        """Test fallback when LLM doesn't use tool."""
        mock_response = MagicMock()
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_response.content = [mock_text]

        mock_llm.messages.create.return_value = mock_response

        result = extract_query_intelligence("find battery startups in Asia")

        assert result.output_mode == "heuristic_fallback"


# ============================================================================
# Integration Tests: Data Persistence
# ============================================================================


class TestDataPersistence:
    """Test query storage and retrieval."""

    def test_insert_and_fetch_query(self):
        """Test inserting and fetching a query."""
        qi = QueryIntelligence(
            search_intent="Find",
            summary="Test query",
            entities=["startups"],
            sectors=["AI"],
            geographies=["Asia"],
            attributes=[],
        )

        record = insert_query("test query", qi)
        assert record.id is not None

        fetched = fetch_query(record.id)
        assert fetched is not None
        assert fetched.query == "test query"
        assert fetched.extracted.summary == "Test query"

    def test_fetch_nonexistent_query(self):
        """Test fetching a non-existent query."""
        result = fetch_query("nonexistent-id")
        assert result is None


# ============================================================================
# Edge Cases and Robustness
# ============================================================================


class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_very_long_query(self):
        """Test handling of very long queries."""
        long_query = "find " + "startups " * 1000
        result = heuristic_extract(long_query)
        assert isinstance(result, QueryIntelligence)

    def test_special_characters_in_query(self):
        """Test queries with special characters."""
        query = "find $TECH & @AI startups (Series A) in #Asia!"
        result = heuristic_extract(query)
        assert isinstance(result, QueryIntelligence)

    def test_unicode_in_query(self):
        """Test queries with Unicode characters."""
        query = "find startups in 中国 and भारत"
        result = heuristic_extract(query)
        assert isinstance(result, QueryIntelligence)

    def test_empty_extraction_lists(self):
        """Test queries that yield empty extraction lists."""
        query = "xyz abc def"
        result = heuristic_extract(query)
        # Should still return valid structure even if lists are empty
        assert isinstance(result, QueryIntelligence)

    def test_normalization_with_mixed_types(self):
        """Test normalize_list with various edge cases."""
        result = normalize_list(
            ["   ", None, 123, "", "Valid", "valid", "VALID", ["list"]]
        )
        # Should have only one "Valid" variant
        assert len(result) == 1
        assert result[0].lower() == "valid"


# ============================================================================
# Performance and Stress Tests
# ============================================================================


class TestPerformance:
    """Test performance characteristics."""

    def test_heuristic_extraction_speed(self):
        """Test that heuristic extraction is reasonably fast."""
        import time

        query = "find battery technology startups in Southeast Asia"
        start = time.time()

        for _ in range(100):
            heuristic_extract(query)

        elapsed = time.time() - start
        # Should complete 100 extractions in < 1 second
        assert elapsed < 1.0

    def test_normalization_performance(self):
        """Test normalization performance with large lists."""
        import time

        large_list = ["item"] * 10000

        start = time.time()
        result = normalize_list(large_list)
        elapsed = time.time() - start

        assert len(result) == 1  # All duplicates removed
        assert elapsed < 0.5  # Should be fast


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
