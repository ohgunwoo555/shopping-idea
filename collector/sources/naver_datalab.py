"""네이버 데이터랩 (NAVER API HUB) — 키워드 → 검색어트렌드·쇼핑인사이트 30일 변화율.

실행:
    python -m sources.naver_datalab --keyword "실리콘 주걱"
    python -m sources.naver_datalab --all --limit 5
    python -m sources.naver_datalab --all --save

- 검색어트렌드: 통합검색에서 그 키워드를 얼마나 검색했는지 (상대 지수, 최대 100)
- 쇼핑인사이트: 네이버쇼핑 안에서 그 키워드가 얼마나 클릭됐는지 (카테고리 지정 필요)
- 두 API 모두 지수(ratio)만 주므로 '최근 30일 평균 / 직전 30일 평균 − 1' 로 변화율을 만든다.
- 한 요청에 키워드 5개까지.

※ 주소·경로를 모르면 먼저 이렇게 찾는다:
    python -m sources.naver_datalab --probe
  후보 경로를 차례로 호출해 200 이 나오는 경로를 알려 준다. 그 값을 .env 의
  NAVER_HUB_SEARCH_PATH / NAVER_HUB_SHOPPING_PATH 에 넣으면 이후 호출은 그 경로를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from datetime import date, timedelta
from typing import Any

import httpx

from config.settings import settings
from sources._common import category_meta, chunked, load_pilot_keywords, pct
from sources.base import BaseCollector, ParseError, RunOptions

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_REQUEST = 5

# 인증 방식별 주소·헤더
AUTH_STYLES: dict[str, dict[str, str]] = {
    # NAVER API HUB (네이버클라우드) 기본
    "ncp": {
        "search": "/datalab/v1/search",
        "shopping": "/datalab/v1/shopping/category/keywords",
        "id_header": "X-NCP-APIGW-API-KEY-ID",
        "secret_header": "X-NCP-APIGW-API-KEY",
    },
    # 개발자센터 이관 유예 사용자 (2027-06-30 까지)
    "openapi": {
        "search": "/v1/datalab/search",
        "shopping": "/v1/datalab/shopping/category/keywords",
        "id_header": "X-Naver-Client-Id",
        "secret_header": "X-Naver-Client-Secret",
    },
}


def trend_change(points: list[float], window: int) -> float | None:
    """최근 window 일 평균 / 직전 window 일 평균 − 1. 데이터가 모자라면 None."""
    if len(points) < window * 2:
        return None
    recent = statistics.mean(points[-window:])
    previous = statistics.mean(points[-window * 2 : -window])
    if previous <= 0:
        return None
    return round(recent / previous - 1, 4)


class NaverDatalabCollector(BaseCollector):
    name = "naver_datalab"

    def __init__(
        self,
        options: RunOptions | None = None,
        client: httpx.Client | None = None,
        shopping_cid: str | None = None,
    ) -> None:
        super().__init__(options)
        self._client = client
        self.shopping_cid = shopping_cid
        style = AUTH_STYLES.get(settings.naver_hub_auth_style)
        if style is None:
            raise RuntimeError(f"NAVER_HUB_AUTH_STYLE 은 ncp 또는 openapi 여야 합니다: {settings.naver_hub_auth_style!r}")
        self.style = dict(style)
        if settings.naver_hub_search_path:
            self.style["search"] = settings.naver_hub_search_path
        if settings.naver_hub_shopping_path:
            self.style["shopping"] = settings.naver_hub_shopping_path
        self.window = settings.trend_window_days

    def _headers(self) -> dict[str, str]:
        settings.require_naver_hub()
        return {
            self.style["id_header"]: settings.naver_hub_client_id,
            self.style["secret_header"]: settings.naver_hub_client_secret,
            "Content-Type": "application/json",
        }

    def _date_range(self) -> tuple[str, str]:
        end = self.options.today - timedelta(days=1)          # 어제까지 (당일은 집계 전)
        start = end - timedelta(days=self.window * 2 - 1)
        return start.isoformat(), end.isoformat()

    def _post(self, client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = settings.naver_hub_base_url + path
        resp = client.post(url, json=body, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(
                f"데이터랩 API 오류 {resp.status_code} ({url}): {resp.text[:300]}\n"
                "(401 이면 NAVER_HUB_CLIENT_ID/SECRET, 404 면 NAVER_HUB_BASE_URL·NAVER_HUB_AUTH_STYLE 을 "
                "HUB 콘솔의 API 가이드와 맞춰 보세요.)"
            )
        return resp.json()

    # ---------- fetch ----------
    def fetch(self, query: str) -> dict[str, Any]:
        return self.fetch_many([query])

    def fetch_many(self, keywords: list[str]) -> dict[str, Any]:
        """{'search': [results...], 'shopping': [results...]} 형태로 모은다."""
        client = self._client or httpx.Client(timeout=15.0)
        start, end = self._date_range()
        out: dict[str, list[dict[str, Any]]] = {"search": [], "shopping": []}
        try:
            for group in chunked(keywords, MAX_KEYWORDS_PER_REQUEST):
                body = {
                    "startDate": start,
                    "endDate": end,
                    "timeUnit": "date",
                    "keywordGroups": [{"groupName": k, "keywords": [k]} for k in group],
                }
                out["search"].extend(self._results(self._post(client, self.style["search"], body), "search"))

                if self.shopping_cid:
                    body = {
                        "startDate": start,
                        "endDate": end,
                        "timeUnit": "date",
                        "category": self.shopping_cid,
                        "keyword": [{"name": k, "param": [k]} for k in group],
                        "device": "",
                        "gender": "",
                        "ages": [],
                    }
                    out["shopping"].extend(self._results(self._post(client, self.style["shopping"], body), "shopping"))
                else:
                    logger.warning("[%s] 쇼핑인사이트 카테고리(cid)가 없어 검색어트렌드만 조회합니다", self.name)
        finally:
            if self._client is None:
                client.close()
        return out

    @staticmethod
    def _results(data: dict[str, Any], which: str) -> list[dict[str, Any]]:
        if "results" not in data:
            raise ParseError(f"{which} 응답에 'results' 가 없습니다. 받은 키: {list(data)}")
        return data["results"]

    # ---------- parse ----------
    def parse(self, raw: dict[str, Any], query: str) -> list[dict[str, Any]]:
        return self.parse_many(raw, [query])

    def parse_many(self, raw: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
        search_map = {r.get("title"): r for r in raw.get("search", [])}
        shop_map = {r.get("title"): r for r in raw.get("shopping", [])}
        rows = []
        for kw in keywords:
            rows.append(
                {
                    "keyword": kw,
                    "collected_at": self.options.today.isoformat(),
                    "search_trend_30d": self._trend(search_map.get(kw), kw, "search"),
                    "shopping_click_trend_30d": self._trend(shop_map.get(kw), kw, "shopping") if shop_map else None,
                }
            )
        return rows

    def _trend(self, result: dict[str, Any] | None, keyword: str, which: str) -> float | None:
        if result is None:
            logger.warning("[%s] '%s' %s 결과 없음", self.name, keyword, which)
            return None
        data = result.get("data")
        if data is None:
            raise ParseError(f"{which} 결과에 'data' 가 없습니다: {list(result)}")
        try:
            points = [float(d["ratio"]) for d in data]
        except (KeyError, TypeError, ValueError):
            raise ParseError(f"{which} data 항목에 'ratio' 숫자가 없습니다: {data[:2]!r}")
        return trend_change(points, self.window)

    # ---------- save ----------
    def save(self, rows: list[dict[str, Any]]) -> int:
        from db.client import upsert_rows

        return upsert_rows("keyword_snapshots", rows, on_conflict="keyword,collected_at")

    def collect_many(self, keywords: list[str], categories: dict[str, str | None] | None = None) -> list[dict[str, Any]]:
        raw = self.fetch_many(keywords)
        rows = self.parse_many(raw, keywords)
        for row in rows:
            row["category"] = (categories or {}).get(row["keyword"])
        if not self.options.dry_run:
            self.save(rows)
        return rows


# --probe 가 시험해 볼 후보 경로. 200 이 나오는 첫 경로를 채택한다.
PROBE_CANDIDATES: dict[str, list[str]] = {
    "search": ["/datalab/v1/search", "/datalab/v1/search/trend", "/v1/datalab/search"],
    "shopping": [
        "/datalab/v1/shopping/category/keywords",
        "/datalab/v1/shopping/keywords",
        "/v1/datalab/shopping/category/keywords",
    ],
}


def probe(cid: str | None = "50000008", client: httpx.Client | None = None) -> dict[str, str | None]:
    """후보 경로에 실제 요청을 보내 어떤 경로가 살아 있는지 찾는다. 키워드 1개, 3일치만 요청한다."""
    settings.require_naver_hub()
    style = AUTH_STYLES[settings.naver_hub_auth_style]
    headers = {
        style["id_header"]: settings.naver_hub_client_id,
        style["secret_header"]: settings.naver_hub_client_secret,
        "Content-Type": "application/json",
    }
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=2)
    bodies = {
        "search": {
            "startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
            "keywordGroups": [{"groupName": "주걱", "keywords": ["주걱"]}],
        },
        "shopping": {
            "startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
            "category": cid or "50000008", "keyword": [{"name": "주걱", "param": ["주걱"]}],
            "device": "", "gender": "", "ages": [],
        },
    }
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    found: dict[str, str | None] = {"search": None, "shopping": None}
    try:
        for which, paths in PROBE_CANDIDATES.items():
            print(f"[{which}] 기본 주소 {settings.naver_hub_base_url} · 헤더 {style['id_header']}")
            for path in paths:
                try:
                    resp = client.post(settings.naver_hub_base_url + path, json=bodies[which], headers=headers)
                except httpx.HTTPError as exc:
                    print(f"   {path:45s} → 연결 실패: {exc}")
                    continue
                ok = resp.status_code == 200 and "results" in resp.text
                mark = "✔ 사용 가능" if ok else f"✘ {resp.status_code}"
                print(f"   {path:45s} → {mark}  {resp.text[:80].replace(chr(10), ' ') if not ok else ''}")
                if ok and found[which] is None:
                    found[which] = path
    finally:
        if own:
            client.close()
    print()
    if found["search"] or found["shopping"]:
        print(".env 에 아래 두 줄을 넣으세요:")
        print(f"NAVER_HUB_SEARCH_PATH={found['search'] or ''}")
        print(f"NAVER_HUB_SHOPPING_PATH={found['shopping'] or ''}")
    else:
        print("살아 있는 경로를 못 찾았습니다. 401 이면 키, 403 이면 Application 에 데이터랩 API 가 체크됐는지,")
        print("전부 404 면 NAVER_HUB_BASE_URL 이 콘솔 안내와 같은지 확인한 뒤 응답 내용을 그대로 보내 주세요.")
    return found


def format_row(row: dict[str, Any]) -> str:
    return (
        f"키워드: {row['keyword']}\n"
        f"  검색어트렌드 30일 변화 : {pct(row['search_trend_30d'])}\n"
        f"  쇼핑클릭 30일 변화     : {pct(row['shopping_click_trend_30d'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="네이버 데이터랩으로 키워드 수요 추이 조회")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keyword", "-k")
    group.add_argument("--all", action="store_true")
    group.add_argument("--probe", action="store_true", help="후보 경로를 시험해 살아 있는 API 주소를 찾는다")
    parser.add_argument("--category", help="categories.yaml 의 카테고리 id (쇼핑인사이트 cid 를 여기서 가져옴)")
    parser.add_argument("--cid", help="네이버쇼핑 카테고리 코드 직접 지정 (예: 50000008)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만 (기본값)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.probe:
        try:
            found = probe(args.cid)
        except Exception as exc:
            logger.error("실패: %s", exc)
            return 1
        return 0 if any(found.values()) else 1

    if args.keyword:
        targets = [(args.category, args.keyword)]
    else:
        targets = load_pilot_keywords(args.category)
        if args.limit:
            targets = targets[: args.limit]

    # 카테고리별로 cid 가 다를 수 있으니 카테고리 단위로 묶어 조회
    by_cat: dict[str | None, list[str]] = {}
    for cat, kw in targets:
        by_cat.setdefault(cat, []).append(kw)

    rows: list[dict[str, Any]] = []
    for cat, kws in by_cat.items():
        cid = args.cid or category_meta(cat).get("naver_shopping_cid")
        collector = NaverDatalabCollector(RunOptions(dry_run=not args.save), shopping_cid=cid)
        try:
            rows.extend(collector.collect_many(kws, {k: cat for k in kws}))
        except Exception as exc:
            logger.error("카테고리 %s 실패: %s", cat, exc)
            if len(by_cat) == 1:
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
