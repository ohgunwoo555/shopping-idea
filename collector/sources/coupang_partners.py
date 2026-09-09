"""쿠팡 파트너스 API (공식) — 키워드 → 검색 결과 상품들의 가격 통계.

실행:
    python -m sources.coupang_partners --keyword "실리콘 주걱"
    python -m sources.coupang_partners --all --limit 5
    python -m sources.coupang_partners --all --save

문서: https://partners.coupang.com  (링크 생성 > API > 상품 검색 API)
- 판매처 수는 주지 않는다. 대신 검색 상위 N개의 최저가·평균가·중앙값과 로켓배송 비율을 계산한다.
- 이 평균가가 스펙 6절 마진 계산의 '국내 평균가' 가 된다.
- 서명: HMAC-SHA256(secret, '{yyMMddTHHmmssZ}{METHOD}{path}{query}') 의 hex.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import sys
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from config.settings import settings
from sources._common import load_pilot_keywords, price_stats, won
from sources.base import BaseCollector, ParseError, RunOptions

logger = logging.getLogger(__name__)

SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"


def signed_datetime(now: float | None = None) -> str:
    """쿠팡이 요구하는 UTC 시각 문자열. 예: 260909T031500Z"""
    t = time.gmtime(now if now is not None else time.time())
    return time.strftime("%y%m%d", t) + "T" + time.strftime("%H%M%S", t) + "Z"


def build_authorization(method: str, path: str, query: str, *, now: float | None = None) -> str:
    settings.require_coupang()
    dt = signed_datetime(now)
    message = dt + method.upper() + path + query
    signature = hmac.new(settings.coupang_secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={settings.coupang_access_key}, "
        f"signed-date={dt}, signature={signature}"
    )


class CoupangPartnersCollector(BaseCollector):
    name = "coupang_partners"

    def __init__(
        self,
        options: RunOptions | None = None,
        client: httpx.Client | None = None,
        max_items: int | None = None,
    ) -> None:
        super().__init__(options)
        self._client = client
        self.max_items = min(max_items or settings.coupang_max_items, 100)

    # ---------- fetch ----------
    def fetch(self, query: str) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=15.0)
        qs = urlencode({"keyword": query, "limit": self.max_items})
        url = f"{settings.coupang_base_url}{SEARCH_PATH}?{qs}"
        headers = {
            "Authorization": build_authorization("GET", SEARCH_PATH, qs),
            "Content-Type": "application/json;charset=UTF-8",
        }
        try:
            resp = client.get(url, headers=headers)
        finally:
            if self._client is None:
                client.close()
        if resp.status_code != 200:
            raise RuntimeError(
                f"쿠팡 파트너스 API 오류 {resp.status_code}: {resp.text[:300]}\n"
                "(401 이면 .env 의 COUPANG_ACCESS_KEY/SECRET_KEY 와 파트너스 승인 상태를 확인하세요.)"
            )
        return resp.json()

    # ---------- parse ----------
    def parse(self, raw: dict[str, Any], query: str) -> list[dict[str, Any]]:
        if str(raw.get("rCode", "0")) != "0":
            raise RuntimeError(f"쿠팡 API 응답 오류 rCode={raw.get('rCode')}: {raw.get('rMessage')}")
        data = raw.get("data")
        if not isinstance(data, dict) or "productData" not in data:
            raise ParseError(f"응답에 data.productData 가 없습니다. 받은 키: {list(raw)}")
        products = data["productData"] or []
        prices: list[int] = []
        rocket = 0
        for p in products:
            try:
                price = int(p.get("productPrice") or 0)
            except (TypeError, ValueError):
                raise ParseError(f"productPrice 를 숫자로 읽지 못함: {p.get('productPrice')!r}")
            if price > 0:
                prices.append(price)
            if p.get("isRocket"):
                rocket += 1
        stats = price_stats(prices)
        return [
            {
                "keyword": query,
                "collected_at": self.options.today.isoformat(),
                "coupang_sample_size": len(products),
                "coupang_min_price_krw": stats["min"],
                "coupang_avg_price_krw": stats["avg"],
                "coupang_median_price_krw": stats["median"],
                "coupang_rocket_ratio": round(rocket / len(products), 3) if products else None,
            }
        ]

    # ---------- save ----------
    def save(self, rows: list[dict[str, Any]]) -> int:
        from db.client import upsert_rows

        return upsert_rows("keyword_snapshots", rows, on_conflict="keyword,collected_at")


def format_row(row: dict[str, Any]) -> str:
    ratio = row["coupang_rocket_ratio"]
    rocket = f"{ratio * 100:.0f}%" if ratio is not None else "-"
    return (
        f"키워드: {row['keyword']}\n"
        f"  검색 상위 상품 수 : {row['coupang_sample_size']}\n"
        f"  최저가            : {won(row['coupang_min_price_krw'])}\n"
        f"  평균가 / 중앙값   : {won(row['coupang_avg_price_krw'])} / {won(row['coupang_median_price_krw'])}\n"
        f"  로켓배송 비율     : {rocket}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="쿠팡 파트너스 상품 검색으로 키워드 가격대 조회")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keyword", "-k")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, help="--all 일 때 앞에서 N개 키워드만")
    parser.add_argument("--max-items", type=int, help=f"가격 통계에 쓸 상품 수 (기본 {settings.coupang_max_items}, 최대 100)")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만 (기본값)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    targets = [(None, args.keyword)] if args.keyword else load_pilot_keywords(args.category)
    if args.limit and args.all:
        targets = targets[: args.limit]

    collector = CoupangPartnersCollector(RunOptions(dry_run=not args.save), max_items=args.max_items)
    rows = []
    for category, keyword in targets:
        try:
            row = collector.run(keyword)[0]
        except Exception as exc:
            logger.error("키워드 '%s' 실패: %s", keyword, exc)
            if len(targets) == 1:
                return 1
            continue
        row["category"] = category
        if args.save:
            collector.save([row])
        rows.append(row)
        if not args.json:
            print(format_row(row), end="\n\n")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not args.save:
        print("(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
