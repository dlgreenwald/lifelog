"""
Search API routes.

GET  /api/v1/search           — full-text search with optional filters
GET  /api/v1/search/facets   — distinct facet values for filter dropdowns
POST /api/v1/search/reindex  — trigger a full re-index for the authenticated user
"""

import structlog
from fastapi import APIRouter, Depends, Query

from lifelog import ingest
from lifelog import search as search_module
from lifelog.auth import validate_oidc_token

logger = structlog.get_logger()

router = APIRouter()


@router.get("/search")
async def search_route(
    q: str = Query(..., min_length=1, max_length=500),
    kind: str | None = None,
    status: str | None = None,
    speaker: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    participants: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(validate_oidc_token),
) -> dict:
    """
    Full-text search across transcript turns, summaries, decisions, and todos.

    Typo tolerance is always active (minWordSizeForTypos: default=4, prefix=2).
    """
    result = search_module.search(
        q=q,
        user_id=user["id"],
        kind=kind,
        status=status,
        speaker=speaker,
        date_from=date_from,
        date_to=date_to,
        participants=participants,
        limit=limit,
        offset=offset,
    )
    return {
        "hits": result["hits"],
        "total": result.get("estimatedTotalHits", 0),
        "limit": limit,
        "offset": offset,
        "processingTimeMs": result["processingTimeMs"],
        "query": q,
    }


@router.get("/search/facets")
async def facets_route(
    user: dict = Depends(validate_oidc_token),
) -> dict:
    """Return distinct facet values for the current user's index."""
    return search_module.get_facets(user_id=user["id"])


@router.post("/search/reindex")
async def reindex_route(
    user: dict = Depends(validate_oidc_token),
) -> dict:
    """Trigger a full re-index of all recordings for the authenticated user."""
    count = await ingest.ingest_all(user["id"])
    logger.info("reindex_done", user_id=user["id"], doc_count=count)
    return {"count": count}
