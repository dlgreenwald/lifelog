"""Smoke tests for the search feature against the live Meilisearch instance.

These tests override auth to bypass OIDC JWT validation and hit the real
Meilisearch index running at MEILI_HOST.  They require a live PostgreSQL
connection (app lifespan) so are skipped when the DB is unreachable.
"""

import os

import pytest
from fastapi.testclient import TestClient

FAKE_USER = {"id": 1, "name": "Smoke Test User"}


def _db_reachable() -> bool:
    try:
        import asyncpg

        async def check():
            pool = await asyncpg.create_pool(
                host=os.environ.get("PGHOST", "localhost"),
                port=int(os.environ.get("PGPORT", "5432")),
                user=os.environ.get("PGUSER", "lifelog"),
                password=os.environ.get("PGPASSWORD", "devpassword"),
                database=os.environ.get("PGDATABASE", "lifelog"),
                min_size=1,
                max_size=1,
            )
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            await pool.close()

        import asyncio

        asyncio.run(check())
        return True
    except Exception:
        return False


skip_no_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="PostgreSQL not reachable — smoke tests require live DB",
)


@pytest.fixture
def client():
    from lifelog.auth import validate_oidc_token
    from lifelog.main import app

    async def fake_oidc():
        return FAKE_USER

    app.dependency_overrides[validate_oidc_token] = fake_oidc
    with TestClient(app, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@skip_no_db
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


@skip_no_db
def test_search_kind_filter(client):
    """Kind filter restricts results to that kind."""
    resp = client.get(
        "/api/v1/search", params={"q": "the", "kind": "summary", "limit": 5}
    )
    assert resp.status_code == 200
    data = resp.json()
    for hit in data["hits"]:
        assert hit["kind"] == "summary", f"Expected kind=summary, got {hit['kind']}"


@skip_no_db
def test_search_facets(client):
    """Facets endpoint returns facet lists."""
    resp = client.get("/api/v1/search/facets")
    assert resp.status_code == 200
    data = resp.json()
    assert "kinds" in data
    assert "speakers" in data
    assert isinstance(data["kinds"], list)


@skip_no_db
def test_search_empty_query_returns_error(client):
    """Empty query is rejected."""
    resp = client.get("/api/v1/search", params={"q": ""})
    assert resp.status_code == 422  # validation error


@skip_no_db
def test_search_reindex(client):
    """Reindex endpoint returns a count."""
    resp = client.post("/api/v1/search/reindex")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert isinstance(data["count"], int)
