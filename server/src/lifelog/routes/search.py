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

    Results are deduplicated by conversation_id — multiple hits from the same
    recording (e.g. transcript + summary both match) are merged into a single
    result with all _matchesPosition combined. Ranking reflects total match
    count across all kinds.

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
        # Fetch more so consolidation doesn't leave holes in paginated results
        limit=min(limit * 4, 400),
        offset=offset,
    )

    hits = _consolidate_by_conversation(result["hits"])
    return {
        "hits": hits,
        "total": result.get("estimatedTotalHits", 0),
        "limit": limit,
        "offset": offset,
        "processingTimeMs": result["processingTimeMs"],
        "query": q,
    }


def _count_matches(matches: dict | None) -> int:
    """Total character-offset match count across all fields."""
    if not matches:
        return 0
    return sum(len(v) for v in matches.values())


def _merge_matches(all: list[dict]) -> dict:
    """Merge _matchesPosition dicts from multiple hits, deduplicating by field."""
    merged: dict[str, list[dict]] = {}
    for item in all:
        for field, positions in item.items():
            merged.setdefault(field, []).extend(positions)
    # Deduplicate within each field by (start, length)
    for field, positions in merged.items():
        seen: set[tuple[int, int]] = set()
        unique = []
        for pos in positions:
            key = (pos["start"], pos["length"])
            if key not in seen:
                seen.add(key)
                unique.append(pos)
        merged[field] = unique
    return merged


def _consolidate_by_conversation(hits: list[dict]) -> list[dict]:
    """
    Merge hits sharing the same conversation_id into a single result.

    The primary hit is the one with the most total _matchesPosition matches.
    All _matchesPosition from all kinds are merged into one dict so that
    every match in the recording is highlighted.
    """
    by_cid: dict[int, list[dict]] = {}
    for hit in hits:
        cid = hit.get("conversation_id")
        if cid is None:
            continue
        by_cid.setdefault(cid, []).append(hit)

    consolidated = []
    for cid, group in by_cid.items():
        if len(group) == 1:
            hit = group[0]
            # Add _totalMatches even for single-hit results so the frontend is consistent
            total = _count_matches(hit.get("_matchesPosition"))
            hit = {**hit, "_totalMatches": total}
            consolidated.append(hit)
            continue

        # Primary hit = most matches
        primary = max(group, key=lambda h: _count_matches(h.get("_matchesPosition")))
        all_matches = _merge_matches([h.get("_matchesPosition", {}) for h in group])
        total = _count_matches(all_matches)

        consolidated_hit = {
            **primary,
            "_matchesPosition": all_matches,
            "_totalMatches": total,
        }

        # If the primary hit's _formatted doesn't have 'text' but some other hit
        # in the group has _matchesPosition['text'] matches, attach that hit's
        # _formatted.text so the frontend can highlight transcript segments.
        primary_fmt = consolidated_hit.get("_formatted") or {}
        if "text" not in primary_fmt:
            for h in group:
                h_fmt = h.get("_formatted") or {}
                if h_fmt.get("text"):
                    # Found a hit with _formatted.text (e.g. transcript doc)
                    consolidated_hit["_formatted"] = {
                        **primary_fmt,
                        "text": h_fmt["text"],
                    }
                    break
        consolidated.append(consolidated_hit)

    # Re-sort by total match count (most matches first)
    consolidated.sort(key=lambda h: -_count_matches(h.get("_matchesPosition")))
    return consolidated


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
