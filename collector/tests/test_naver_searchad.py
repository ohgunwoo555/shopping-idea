from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import date

import httpx
import pytest

from sources.base import ParseError, RunOptions
from sources.naver_searchad import (
    KEYWORD_TOOL_PATH,
    NaverSearchAdCollector,
    build_headers,
    normalize_keyword,
    parse_count,
)


def _item(rel: str, comp: str = "중간", pc="1200", mo="8800", **extra):
    base = {
        "relKeyword": rel,
        "monthlyPcQcCnt": pc,
        "monthlyMobileQcCnt": mo,
        "monthlyAvePcClkCnt": 3.5,
        "monthlyAveMobileClkCnt": 40.2,
        "plAvgDepth": 15,
        "compIdx": comp,
    }
    base.update(extra)
    return base


def test_normalize_and_parse_count():
    assert normalize_keyword("실리콘 주걱") == "실리콘주걱"
    assert parse_count("< 10") == 0
    assert parse_count("1,200".replace(",", "")) == 1200
    assert parse_count(55) == 55
    with pytest.raises(ParseError):
        parse_count("abc")


def test_signature_matches_spec():
    h = build_headers("GET", KEYWORD_TOOL_PATH, timestamp_ms=1700000000000)
    msg = f"1700000000000.GET.{KEYWORD_TOOL_PATH}"
    expected = base64.b64encode(hmac.new(b"ad-secret", msg.encode(), hashlib.sha256).digest()).decode()
    assert h["X-Signature"] == expected
    assert h["X-Customer"] == "12345"
    assert h["X-API-KEY"] == "license"


def test_batches_of_five_and_merges():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hints = req.url.params["hintKeywords"].split(",")
        seen.append(req.url.params["hintKeywords"])
        assert len(hints) <= 5
        return httpx.Response(200, json={"keywordList": [_item(h) for h in hints] + [_item("연관키워드", "높음")]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    kws = [f"키워드 {i}" for i in range(7)]
    c = NaverSearchAdCollector(RunOptions(dry_run=True, collected_at=date(2026, 9, 9)), client=client)
    rows = c.collect_many(kws, {k: "kitchen_living" for k in kws})
    assert len(seen) == 2
    assert [r["keyword"] for r in rows] == kws            # 연관키워드는 섞이지 않는다
    r = rows[0]
    assert r["collected_at"] == "2026-09-09"
    assert r["category"] == "kitchen_living"
    assert r["ad_monthly_search_pc"] == 1200
    assert r["ad_monthly_search_mobile"] == 8800
    assert r["ad_monthly_clicks"] == 43.7
    assert r["ad_comp_idx"] == "중간" and r["ad_comp_score"] == 0.5
    assert r["ad_pl_avg_depth"] == 15


def test_missing_keyword_is_skipped_with_warning(caplog):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"keywordList": [_item("있음")]})))
    c = NaverSearchAdCollector(RunOptions(dry_run=True), client=client)
    rows = c.collect_many(["있음", "없음"])
    assert [r["keyword"] for r in rows] == ["있음"]
    assert "없음" in caplog.text


def test_unknown_comp_idx_raises():
    c = NaverSearchAdCollector(RunOptions(dry_run=True))
    with pytest.raises(ParseError, match="compIdx"):
        c.parse({"keywordList": [_item("x", comp="???")]}, "x")


def test_http_error_explains():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="forbidden")))
    c = NaverSearchAdCollector(RunOptions(dry_run=True), client=client)
    with pytest.raises(RuntimeError, match="403"):
        c.run("x")
