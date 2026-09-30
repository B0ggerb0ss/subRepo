"""Collection lookup helpers shared by search and the correction commands."""
from __future__ import annotations

from services.library.repository import Repository


def resolve_collection_id(repo: Repository, key_or_id: str) -> str | None:
    """Resolve a collection by id, key or label, following merge/split aliases."""
    r = repo.query_one(
        "SELECT id FROM collections WHERE retired_at IS NULL AND (id=? OR key=? OR lower(COALESCE(user_label,''))=?"
        " OR lower(suggested_label)=?) ORDER BY pinned DESC, updated_at DESC LIMIT 1",
        (key_or_id, key_or_id, key_or_id.lower(), key_or_id.lower()))
    if r:
        return r["id"]
    seen = set()
    cur = key_or_id
    while cur not in seen:
        seen.add(cur)
        a = repo.query_one("SELECT new_id FROM collection_aliases WHERE old_id=? ORDER BY created_at DESC LIMIT 1",
                           (cur,))
        if a is None:
            return None
        live = repo.query_one("SELECT id FROM collections WHERE id=? AND retired_at IS NULL", (a["new_id"],))
        if live:
            return live["id"]
        cur = a["new_id"]
    return None


def collection_members_for_filter(repo: Repository, key_or_id: str) -> set[str]:
    cid = resolve_collection_id(repo, key_or_id)
    if cid is None:
        from services.search.service import SearchError

        raise SearchError(f"collection:{key_or_id} not found")
    return {r["asset_id"] for r in repo.query(
        "SELECT asset_id FROM memberships WHERE collection_id=? AND state!='excluded'", (cid,))}
