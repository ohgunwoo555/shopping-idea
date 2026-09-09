"""네이버 검색광고 API 키워드도구 (공식) — 키워드 → 월간 검색수·광고 클릭수·경쟁정도.

실행:
    python -m sources.naver_searchad --keyword "실리콘 주걱"
    python -m sources.naver_searchad --all --limit 5
    python -m sources.naver_searchad --all --save

문서: https://naver.github.io/searchad-apidoc/  (키워드도구: GET /keywordstool)
- 광고를 실제로 집행하지 않아도 검색광고 계정만 있으면 무료로 쓸 수 있다.
- 한 번에 키워드 5개까지 묶어 조회한다. 키워드의 공백은 API 규칙상 제거해 보낸다.
- 검색수는 10 미만이면 "< 10" 이라는 글자로 오므로 0으로 처리한다.
- 경쟁정도(compIdx: 낮음/중간/높음)를 경쟁 점수의 핵심 재료로 쓴다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import sys
import time
from typing import Any

import httpx

from config.settings import settings
from sources._common import chunked, load_pilot_keywords
from sources.base import BaseCollector, ParseError, RunOptions

logger = logging.getLogger(__name__)

KEYWORD_TOOL_PATH = "/keywordstool"
MAX_HINT_KEYWORDS = 5

COMP_IDX_SCORE = {"낮음": 0.0, "중간": 0.5, "높음": 1.0}


def normalize_keyword(keyword: str) -> str:
    """API 가 공백 포함 키워드를 거부하므로 공백을 없앤다. '실리콘 주걱' → '실리콘주걱'"""
    return keyword.replace(" ", "")


def parse_count(value: Any) -> int:
    """'< 10' 같은 문자열은 0, 숫자는 그대로."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.startswith("<"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        raise ParseError(f"검색수/클릭수를 숫자로 읽지 못함: {value!r}")


def build_headers(method: str, path: str, *, timestamp_ms: int | None = None) -> dict[str, str]:
    """검색광고 API 서명 헤더. 서명 = base64(HMAC-SHA256(secret, '{ts}.{METHOD}.{path}'))"""
    settings.require_naver_ad()
    ts = str(timestamp_ms if timestamp_ms is not None else round(time.time() * 1000))
    message = f"{ts}.{method.upper()}.{path}"
    digest = hmac.new(settings.naver_ad_secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return {
        "X-Timestamp": ts,
        "X-API-KEY": settings.naver_ad_access_license,
        "X-Customer": str(settings.naver_ad_customer_id),
        "X-Signature": base64.b64encode(digest).decode(),
        "Content-Type": "application/json; charset=UTF-8",
    }


class NaverSearchAdCollector(BaseCollector):
    name = "naver_searchad"

    def __init__(self, options: RunOptions | None = None, client: httpx.Client | None = None) -> None:
        super().__init__(options)
        self._client = client

    # ---------- fetch ----------
    def fetch(self, query: str) -> dict[str, Any]:
        return self.fetch_many([query])

    def fetch_many(self, keywords: list[str]) -> dict[str, Any]:
        """여러 키워드를 5개씩 묶어 조회하고 keywordList 를 하나로 합친다."""
        client = self._client or httpx.Client(timeout=15.0)
        merged: list[dict[str, Any]] = []
        try:
            for group in chunked(keywords, MAX_HINT_KEYWORDS):
                hints = ",".join(normalize_keyword(k) for k in group)
                params = {"hintKeywords": hints, "showDetail": "1"}
                resp = client.get(
                    settings.naver_ad_base_url + KEYWORD_TOOL_PATH,
                    params=params,
                    headers=build_headers("GET", KEYWORD_TOOL_PATH),
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"검색광고 API 오류 {resp.status_code}: {resp.text[:300]}\n"
                        "(401/403 이면 .env 의 NAVER_AD_* 세 값과 CUSTOMER_ID 를 확인하세요. "
                        "429 면 잠시 후 다시 시도하세요.)"
                    )
                data = resp.json()
                if "keywordList" not in data:
                    raise ParseError(f"응답에 'keywordList' 가 없습니다. 받은 키: {list(data)}")
                merged.extend(data["keywordList"])
        finally:
            if self._client is None:
                client.close()
        return {"keywordList": merged}

    # ---------- parse ----------
    def parse(self, raw: dict[str, Any], query: str) -> list[dict[str, Any]]:
        row = self._find_row(raw, query)
        if row is None:
            raise ParseError(f"'{query}' 에 해당하는 relKeyword 가 응답에 없습니다")
        return [self._to_snapshot(row, query)]

    def parse_many(self, raw: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
        out = []
        for kw in keywords:
            row = self._find_row(raw, kw)
            if row is None:
                logger.warning("[%s] '%s' 결과 없음 (검색량이 거의 없는 키워드일 수 있음)", self.name, kw)
                continue
            out.append(self._to_snapshot(row, kw))
        return out

    @staticmethod
    def _find_row(raw: dict[str, Any], keyword: str) -> dict[str, Any] | None:
        target = normalize_keyword(keyword)
        for item in raw.get("keywordList", []):
            if normalize_keyword(str(item.get("relKeyword", ""))) == target:
                return item
        return None

    def _to_snapshot(self, item: dict[str, Any], keyword: str) -> dict[str, Any]:
        comp_idx = str(item.get("compIdx", "")).strip()
        if comp_idx not in COMP_IDX_SCORE:
            raise ParseError(f"compIdx 값이 예상 밖입니다: {comp_idx!r} (낮음/중간/높음 이어야 함)")
        pc_clicks = float(item.get("monthlyAvePcClkCnt") or 0)
        mo_clicks = float(item.get("monthlyAveMobileClkCnt") or 0)
        return {
            "keyword": keyword,
            "collected_at": self.options.today.isoformat(),
            "ad_monthly_search_pc": parse_count(item.get("monthlyPcQcCnt")),
            "ad_monthly_search_mobile": parse_count(item.get("monthlyMobileQcCnt")),
            "ad_monthly_clicks": round(pc_clicks + mo_clicks, 1),
            "ad_comp_idx": comp_idx,
            "ad_comp_score": COMP_IDX_SCORE[comp_idx],
            "ad_pl_avg_depth": int(item.get("plAvgDepth") or 0),
        }

    # ---------- save ----------
    def save(self, rows: list[dict[str, Any]]) -> int:
        from db.client import upsert_rows

        return upsert_rows("keyword_snapshots", rows, on_conflict="keyword,collected_at")

    # ---------- 편의 ----------
    def collect_many(self, keywords: list[str], categories: dict[str, str | None] | None = None) -> list[dict[str, Any]]:
        raw = self.fetch_many(keywords)
        rows = self.parse_many(raw, keywords)
        for row in rows:
            row["category"] = (categories or {}).get(row["keyword"])
        if not self.options.dry_run:
            self.save(rows)
        return rows


def format_row(row: dict[str, Any]) -> str:
    total = row["ad_monthly_search_pc"] + row["ad_monthly_search_mobile"]
    return (
        f"키워드: {row['keyword']}\n"
        f"  월간 검색수      : {total:,}  (PC {row['ad_monthly_search_pc']:,} / 모바일 {row['ad_monthly_search_mobile']:,})\n"
        f"  월평균 광고 클릭 : {row['ad_monthly_clicks']:,}\n"
        f"  경쟁정도         : {row['ad_comp_idx']}  (점수 {row['ad_comp_score']})\n"
        f"  평균 노출 깊이   : {row['ad_pl_avg_depth']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 검색광고 키워드도구로 키워드 경쟁 지표 조회")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keyword", "-k")
    group.add_argument("--all", action="store_true", help="config/categories.yaml 의 모든 키워드")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--save", action="store_true", help="Supabase keyword_snapshots 에 저장")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만 (기본값)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.keyword:
        targets = [(None, args.keyword)]
    else:
        targets = load_pilot_keywords(args.category)
        if args.limit:
            targets = targets[: args.limit]

    collector = NaverSearchAdCollector(RunOptions(dry_run=not args.save))
    try:
        rows = collector.collect_many([kw for _, kw in targets], {kw: cat for cat, kw in targets})
    except Exception as exc:
        logger.error("실패: %s", exc)
        return 1
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(format_row(row), end="\n\n")
        if not args.save:
            print("(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
