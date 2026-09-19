"""Smoke tests for the search feature against the live Meilisearch instance.

These tests override auth to bypass OIDC JWT validation and hit the real
Meilisearch index running at MEILI_HOST.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

FAKE_USER = {"id": 1, "name": "Smoke Test User"}


@pytest.fixture
def client():
    from lifelog.main import app
    from lifelog.auth import validate_oidc_token

    async def fake_oidc():
        return FAKE_USER

    app.dependency_overrides[validate_oidc_token] = fake_oidc
    with TestClient(app, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def test_search_returns_results(client):
    """Basic search returns hits with expected shape."""
    resp = client.get("/api/v1/search", params={"q": "meeting", "limit": 3})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "hits" in data
    assert "total" in data
    assert "processingTimeMs" in data
    assert isinstance(data["hits"], list)
    assert data["total"] >= 0
    assert data["processingTimeMs"] >= 0


def test_search_kind_filter(client):
    """Kind filter restricts results to that kind."""
    resp = client.get("/api/v1/search", params={"q": "the", "kind": "summary", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    for hit in data["hits"]:
        assert hit["kind"] == "summary", f"Expected kind=summary, got {hit['kind']}"


def test_search_facets(client):
    """Facets endpoint returns facet lists."""
    resp = client.get("/api/v1/search/facets")
    assert resp.status_code == 200
    data = resp.json()
    assert "kinds" in data
    assert "speakers" in data
    assert isinstance(data["kinds"], list)


def test_search_empty_query_returns_error(client):
    """Empty query is rejected."""
    resp = client.get("/api/v1/search", params={"q": ""})
    assert resp.status_code == 422  # validation error


def test_search_reindex(client):
    """Reindex endpoint returns a count."""
    resp = client.post("/api/v1/search/reindex")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert isinstance(data["count"], int)
