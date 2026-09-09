"""수집기들이 함께 쓰는 작은 도구 모음."""
from __future__ import annotations

import statistics
from typing import Any, Iterable

import yaml

from config.settings import settings


def price_stats(prices: Iterable[int]) -> dict[str, int | None]:
    """가격 목록 → 최저·평균·중앙값. 비어 있으면 전부 None."""
    ps = [p for p in prices if p and p > 0]
    if not ps:
        return {"min": None, "avg": None, "median": None}
    return {
        "min": min(ps),
        "avg": round(statistics.mean(ps)),
        "median": round(statistics.median(ps)),
    }


def load_categories() -> list[dict[str, Any]]:
    with open(settings.categories_path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("categories", [])


def load_pilot_keywords(category: str | None = None) -> list[tuple[str, str]]:
    """categories.yaml 에서 (카테고리 id, 한글 키워드) 목록을 읽는다."""
    out: list[tuple[str, str]] = []
    for cat in load_categories():
        if category and cat["id"] != category:
            continue
        for kw in cat.get("keywords", []):
            out.append((cat["id"], kw["ko"] if isinstance(kw, dict) else str(kw)))
    return out


def category_meta(category_id: str | None) -> dict[str, Any]:
    for cat in load_categories():
        if cat["id"] == category_id:
            return cat
    return {}


def won(v: int | None) -> str:
    return f"{v:,}원" if v is not None else "-"


def pct(v: float | None) -> str:
    return f"{v * 100:+.1f}%" if v is not None else "-"


def chunked(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
