"""네이버 쇼핑 검색 API (공식) — 키워드 1개 → 상품 수·최저가·평균가·판매처 수.

실행:
    python -m sources.naver_shopping --keyword "실리콘 주걱"
    python -m sources.naver_shopping --keyword "실리콘 주걱" --json
    python -m sources.naver_shopping --all --dry-run          # categories.yaml 전체 키워드
    python -m sources.naver_shopping --all --limit 5 --save   # 5개만 조회해 Supabase 저장

API 문서: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
- 하루 25,000회 무료. 키워드당 최대 3회 호출(100개씩 3페이지)하므로 넉넉하다.
- '판매처 수'는 API가 직접 주지 않는다. 검색 결과 상위 N개의 서로 다른 mallName 수로 추정한다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import httpx
import yaml

from config.settings import settings
from sources.base import BaseCollector, ParseError, RunOptions

logger = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# productType: 1~3 = 일반 판매 상품, 4~6 = 중고, 7~9 = 단종, 10~12 = 판매예정
# 경쟁 분석에는 실제 팔리고 있는 일반 상품만 센다.
ACTIVE_PRODUCT_TYPES = {"1", "2", "3"}

# 가격비교 묶음 상품은 mallName 이 "네이버" 로 오며 개별 판매처가 아니다.
PRICE_COMPARE_MALL_NAMES = {"네이버", "네이버쇼핑"}

_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(text: str) -> str:
    """API가 <b>키워드</b> 처럼 굵게 표시를 넣어 보내므로 태그를 벗긴다."""
    return _TAG_RE.sub("", text or "").strip()


@dataclass
class KeywordSnapshot:
    keyword: str
    collected_at: str
    naver_product_count: int           # API 의 total (검색 결과 전체 상품 수)
    naver_seller_count: int            # 상위 N개에서 관찰된 서로 다른 판매처 수
    naver_min_price_krw: int | None
    naver_avg_price_krw: int | None
    naver_median_price_krw: int | None
    sample_size: int                   # 판매처 수 추정에 쓴 상품 수
    category: str | None = None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


class NaverShoppingCollector(BaseCollector):
    name = "naver_shopping"

    def __init__(
        self,
        options: RunOptions | None = None,
        client: httpx.Client | None = None,
        max_items: int | None = None,
    ) -> None:
        super().__init__(options)
        self.max_items = max_items or settings.naver_max_items
        self.page_size = settings.naver_page_size
        self._client = client  # 테스트에서 가짜 클라이언트를 넣을 수 있게

    # ---------- fetch ----------
    def _headers(self) -> dict[str, str]:
        settings.require_naver()
        return {
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        }

    def fetch(self, query: str) -> list[dict[str, Any]]:
        """최대 max_items 개까지 100개 단위로 페이지를 돌며 응답 JSON 목록을 모은다."""
        client = self._client or httpx.Client(timeout=10.0)
        pages: list[dict[str, Any]] = []
        start = 1
        try:
            while start <= self.max_items:
                display = min(self.page_size, self.max_items - start + 1)
                params = {"query": query, "display": display, "start": start, "sort": "sim"}
                resp = client.get(API_URL, params=params, headers=self._headers())
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"네이버 API 오류 {resp.status_code}: {resp.text[:200]}\n"
                        "(401/403 이면 .env 의 NAVER_CLIENT_ID/SECRET 을 확인하세요. "
                        "429 면 하루 호출 한도 초과입니다.)"
                    )
                data = resp.json()
                pages.append(data)
                items = data.get("items") or []
                total = int(data.get("total", 0))
                logger.debug("page start=%d got=%d total=%d", start, len(items), total)
                if not items or start + len(items) > min(total, self.max_items):
                    break
                start += len(items)
        finally:
            if self._client is None:
                client.close()
        return pages

    # ---------- parse ----------
    def parse(self, raw: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        if not raw:
            raise ParseError("응답 페이지가 비어 있습니다")
        first = raw[0]
        if "total" not in first or "items" not in first:
            raise ParseError(f"응답에 'total'/'items' 키가 없습니다. 받은 키: {list(first)}")

        total = int(first["total"])
        items: list[dict[str, Any]] = []
        for page in raw:
            items.extend(page.get("items") or [])

        active = [it for it in items if str(it.get("productType", "")) in ACTIVE_PRODUCT_TYPES]
        malls = {
            strip_tags(it.get("mallName", ""))
            for it in active
            if strip_tags(it.get("mallName", "")) not in PRICE_COMPARE_MALL_NAMES | {""}
        }
        prices = []
        for it in active:
            try:
                p = int(it.get("lprice") or 0)
            except (TypeError, ValueError):
                raise ParseError(f"lprice 를 숫자로 읽지 못함: {it.get('lprice')!r}")
            if p > 0:
                prices.append(p)

        snapshot = KeywordSnapshot(
            keyword=query,
            collected_at=self.options.today.isoformat(),
            naver_product_count=total,
            naver_seller_count=len(malls),
            naver_min_price_krw=min(prices) if prices else None,
            naver_avg_price_krw=round(statistics.mean(prices)) if prices else None,
            naver_median_price_krw=round(statistics.median(prices)) if prices else None,
            sample_size=len(active),
        )
        return [snapshot.to_row()]

    # ---------- save ----------
    def save(self, rows: list[dict[str, Any]]) -> int:
        from db.client import upsert_rows

        return upsert_rows("keyword_snapshots", rows, on_conflict="keyword,collected_at")


# ---------- 편의 함수 ----------
def lookup(keyword: str, max_items: int | None = None) -> dict[str, Any]:
    """키워드 1개를 조회해 dict 로 돌려준다. DB 저장은 하지 않는다."""
    collector = NaverShoppingCollector(RunOptions(dry_run=True), max_items=max_items)
    return collector.run(keyword)[0]


def load_pilot_keywords(category: str | None = None) -> list[tuple[str, str]]:
    """categories.yaml 에서 (카테고리 id, 키워드) 목록을 읽는다."""
    with open(settings.categories_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    out: list[tuple[str, str]] = []
    for cat in cfg.get("categories", []):
        if category and cat["id"] != category:
            continue
        for kw in cat.get("keywords", []):
            out.append((cat["id"], kw["ko"] if isinstance(kw, dict) else str(kw)))
    return out


def _format_row(row: dict[str, Any]) -> str:
    def won(v: int | None) -> str:
        return f"{v:,}원" if v is not None else "-"

    return (
        f"키워드: {row['keyword']}\n"
        f"  상품 수(전체)     : {row['naver_product_count']:,}\n"
        f"  판매처 수(추정)   : {row['naver_seller_count']}  (상위 {row['sample_size']}개 기준)\n"
        f"  최저가            : {won(row['naver_min_price_krw'])}\n"
        f"  평균가 / 중앙값   : {won(row['naver_avg_price_krw'])} / {won(row['naver_median_price_krw'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 쇼핑 검색 API로 키워드 경쟁 상황 조회")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keyword", "-k", help="조회할 키워드 1개")
    group.add_argument("--all", action="store_true", help="config/categories.yaml 의 모든 키워드")
    parser.add_argument("--category", help="--all 일 때 특정 카테고리 id 만")
    parser.add_argument("--limit", type=int, help="--all 일 때 앞에서 N개 키워드만")
    parser.add_argument("--max-items", type=int, help=f"판매처 추정에 쓸 상품 수 (기본 {settings.naver_max_items})")
    parser.add_argument("--save", action="store_true", help="Supabase keyword_snapshots 에 저장")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만 (기본값)")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    dry_run = not args.save
    options = RunOptions(dry_run=dry_run)
    collector = NaverShoppingCollector(options, max_items=args.max_items)

    if args.keyword:
        targets = [(None, args.keyword)]
    else:
        targets = load_pilot_keywords(args.category)
        if args.limit:
            targets = targets[: args.limit]

    results: list[dict[str, Any]] = []
    for category, keyword in targets:
        try:
            row = collector.run(keyword)[0]
        except Exception as exc:  # 어떤 키워드에서 왜 실패했는지 남기고 계속 진행
            logger.error("키워드 '%s' 실패: %s", keyword, exc)
            if len(targets) == 1:
                return 1
            continue
        row["category"] = category
        if not dry_run:
            collector.save([row])
        results.append(row)
        if not args.json:
            print(_format_row(row))
            print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    if dry_run and not args.json:
        print("(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
