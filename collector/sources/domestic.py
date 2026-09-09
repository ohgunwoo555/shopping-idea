"""국내 신호 세 가지를 한 번에 모아 키워드별 한 행으로 합친다.

실행:
    python -m sources.domestic --keyword "실리콘 주걱"
    python -m sources.domestic --all --limit 5
    python -m sources.domestic --all --save
    python -m sources.domestic --all --only searchad,coupang   # 일부만

각 소스가 실패해도 나머지는 계속 진행하고, 어떤 소스가 왜 실패했는지 로그로 남긴다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from sources._common import category_meta, load_pilot_keywords, pct, won
from sources.base import RunOptions
from sources.coupang_partners import CoupangPartnersCollector
from sources.naver_datalab import NaverDatalabCollector
from sources.naver_searchad import NaverSearchAdCollector

logger = logging.getLogger(__name__)

ALL_SOURCES = ("searchad", "coupang", "datalab")


def collect_domestic(
    targets: list[tuple[str | None, str]],
    *,
    only: tuple[str, ...] = ALL_SOURCES,
    save: bool = False,
) -> list[dict[str, Any]]:
    """[(category, keyword)] → 키워드별 합쳐진 행 목록. save=True 면 keyword_snapshots 에 upsert."""
    options = RunOptions(dry_run=True)   # 합친 뒤 한 번만 저장하므로 개별 수집기는 저장 안 함
    keywords = [kw for _, kw in targets]
    cat_of = {kw: cat for cat, kw in targets}
    merged: dict[str, dict[str, Any]] = {
        kw: {"keyword": kw, "category": cat_of[kw], "collected_at": options.today.isoformat()} for kw in keywords
    }

    def absorb(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            merged[r["keyword"]].update({k: v for k, v in r.items() if k not in ("category",)})

    if "searchad" in only:
        try:
            absorb(NaverSearchAdCollector(options).collect_many(keywords))
        except Exception as exc:
            logger.error("[searchad] 실패: %s", exc)

    if "coupang" in only:
        collector = CoupangPartnersCollector(options)
        for kw in keywords:
            try:
                absorb(collector.run(kw))
            except Exception as exc:
                logger.error("[coupang] '%s' 실패: %s", kw, exc)

    if "datalab" in only:
        by_cat: dict[str | None, list[str]] = {}
        for cat, kw in targets:
            by_cat.setdefault(cat, []).append(kw)
        for cat, kws in by_cat.items():
            cid = category_meta(cat).get("naver_shopping_cid")
            try:
                absorb(NaverDatalabCollector(options, shopping_cid=cid).collect_many(kws))
            except Exception as exc:
                logger.error("[datalab] 카테고리 %s 실패: %s", cat, exc)

    rows = list(merged.values())
    if save:
        from db.client import upsert_rows

        n = upsert_rows("keyword_snapshots", rows, on_conflict="keyword,collected_at")
        logger.info("keyword_snapshots 에 %d행 저장", n)
    return rows


def format_row(r: dict[str, Any]) -> str:
    g = r.get
    search_total = (g("ad_monthly_search_pc") or 0) + (g("ad_monthly_search_mobile") or 0)
    lines = [f"키워드: {r['keyword']}"]
    if "ad_comp_idx" in r:
        lines.append(f"  [경쟁] 월간 검색수 {search_total:,} · 광고 클릭 {g('ad_monthly_clicks'):,} · 경쟁정도 {g('ad_comp_idx')}")
    else:
        lines.append("  [경쟁] (검색광고 결과 없음)")
    if "coupang_avg_price_krw" in r:
        lines.append(
            f"  [가격] 쿠팡 최저 {won(g('coupang_min_price_krw'))} · 평균 {won(g('coupang_avg_price_krw'))} "
            f"· 중앙값 {won(g('coupang_median_price_krw'))} (상위 {g('coupang_sample_size')}개)"
        )
    else:
        lines.append("  [가격] (쿠팡 결과 없음)")
    if "search_trend_30d" in r:
        lines.append(f"  [수요] 검색 추이 {pct(g('search_trend_30d'))} · 쇼핑 클릭 추이 {pct(g('shopping_click_trend_30d'))}")
    else:
        lines.append("  [수요] (데이터랩 결과 없음)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="국내 신호(경쟁·가격·수요) 한 번에 수집")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keyword", "-k")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", help="searchad,coupang,datalab 중 일부만 (쉼표 구분)")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만 (기본값)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.keyword:
        targets = [(args.category, args.keyword)]
    else:
        targets = load_pilot_keywords(args.category)
        if args.limit:
            targets = targets[: args.limit]

    only = tuple(s.strip() for s in args.only.split(",")) if args.only else ALL_SOURCES
    bad = [s for s in only if s not in ALL_SOURCES]
    if bad:
        parser.error(f"--only 에 알 수 없는 값: {bad}. 가능: {', '.join(ALL_SOURCES)}")

    rows = collect_domestic(targets, only=only, save=args.save)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(format_row(r), end="\n\n")
        if not args.save:
            print("(--save 를 붙이면 Supabase 의 keyword_snapshots 테이블에 저장됩니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
