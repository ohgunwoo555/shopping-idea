"""Supabase 읽기/쓰기 얇은 래퍼.

사용 예:
    from db.client import get_client, upsert_rows
    upsert_rows("keyword_snapshots", [row], on_conflict="keyword,collected_at")
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from config.settings import settings


@lru_cache(maxsize=1)
def get_client():
    """Supabase 클라이언트를 한 번만 만들어 재사용한다."""
    settings.require_supabase()
    from supabase import create_client  # 지연 import: 키가 없을 때 불필요한 로딩 방지

    return create_client(settings.supabase_url, settings.supabase_service_key)


def upsert_rows(table: str, rows: list[dict[str, Any]], on_conflict: str | None = None) -> int:
    """행 목록을 넣는다. 같은 키가 이미 있으면 덮어쓴다. 넣은 행 수를 돌려준다."""
    if not rows:
        return 0
    client = get_client()
    query = client.table(table)
    resp = query.upsert(rows, on_conflict=on_conflict).execute() if on_conflict else query.upsert(rows).execute()
    return len(resp.data or [])


def select_rows(table: str, **filters: Any) -> list[dict[str, Any]]:
    """단순 동등 조건으로 조회한다. 예: select_rows("clusters", category="kitchen")"""
    client = get_client()
    query = client.table(table).select("*")
    for column, value in filters.items():
        query = query.eq(column, value)
    return query.execute().data or []
