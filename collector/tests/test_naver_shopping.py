"""네트워크 없이 파싱 로직만 검증한다. 실행: cd collector && pytest"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from sources.base import ParseError, RunOptions
from sources.naver_shopping import NaverShoppingCollector, load_pilot_keywords, strip_tags


def _item(mall: str, price: int, ptype: str = "2") -> dict:
    return {
        "title": "<b>실리콘</b> 주걱",
        "link": "https://example.com",
        "lprice": str(price),
        "hprice": "",
        "mallName": mall,
        "productId": "1",
        "productType": ptype,
    }


def _fake_client(pages: list[dict]) -> httpx.Client:
    """start 파라미터에 따라 미리 준비한 페이지를 돌려주는 가짜 서버."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Naver-Client-Id"] == "test-id"
        start = int(request.url.params["start"])
        calls.append(start)
        index = (start - 1) // 100
        return httpx.Response(200, json=pages[index])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls  # type: ignore[attr-defined]
    return client


@pytest.fixture(autouse=True)
def _naver_keys(monkeypatch):
    from config import settings as s

    # settings 는 frozen dataclass 라 object.__setattr__ 로 우회한다.
    original = (s.settings.naver_client_id, s.settings.naver_client_secret)
    object.__setattr__(s.settings, "naver_client_id", "test-id")
    object.__setattr__(s.settings, "naver_client_secret", "test-secret")
    yield
    object.__setattr__(s.settings, "naver_client_id", original[0])
    object.__setattr__(s.settings, "naver_client_secret", original[1])


def test_strip_tags():
    assert strip_tags("<b>실리콘</b> 주걱") == "실리콘 주걱"


def test_single_page_summary():
    page = {
        "total": 5,
        "items": [
            _item("A마트", 3000),
            _item("B스토어", 5000),
            _item("A마트", 4000),          # 같은 판매처 → 1개로 센다
            _item("네이버", 2500, "1"),    # 가격비교 묶음 → 판매처로 안 셈, 가격은 셈
            _item("C중고", 1000, "4"),     # 중고 → 완전히 제외
        ],
    }
    collector = NaverShoppingCollector(
        RunOptions(dry_run=True, collected_at=date(2026, 9, 9)),
        client=_fake_client([page]),
        max_items=100,
    )
    row = collector.run("실리콘 주걱")[0]
    assert row["keyword"] == "실리콘 주걱"
    assert row["collected_at"] == "2026-09-09"
    assert row["naver_product_count"] == 5
    assert row["naver_seller_count"] == 2
    assert row["naver_min_price_krw"] == 2500
    assert row["naver_avg_price_krw"] == round((3000 + 5000 + 4000 + 2500) / 4)
    assert row["naver_median_price_krw"] == 3500
    assert row["sample_size"] == 4


def test_pagination_stops_at_max_items():
    page1 = {"total": 1000, "items": [_item(f"m{i}", 1000 + i) for i in range(100)]}
    page2 = {"total": 1000, "items": [_item(f"n{i}", 2000 + i) for i in range(100)]}
    client = _fake_client([page1, page2])
    collector = NaverShoppingCollector(RunOptions(dry_run=True), client=client, max_items=200)
    row = collector.run("x")[0]
    assert client.calls == [1, 101]
    assert row["naver_seller_count"] == 200
    assert row["sample_size"] == 200


def test_pagination_stops_when_total_is_small():
    page1 = {"total": 3, "items": [_item("a", 1), _item("b", 2), _item("c", 3)]}
    client = _fake_client([page1])
    collector = NaverShoppingCollector(RunOptions(dry_run=True), client=client, max_items=300)
    collector.run("x")
    assert client.calls == [1]


def test_parse_error_names_missing_key():
    collector = NaverShoppingCollector(RunOptions(dry_run=True))
    with pytest.raises(ParseError, match="total"):
        collector.parse([{"unexpected": 1}], "x")


def test_api_error_is_explained():
    def handler(request):
        return httpx.Response(401, json={"errorMessage": "bad key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = NaverShoppingCollector(RunOptions(dry_run=True), client=client)
    with pytest.raises(RuntimeError, match="401"):
        collector.run("x")


def test_pilot_keywords_has_20():
    keywords = load_pilot_keywords("kitchen_living")
    assert len(keywords) == 20
    assert all(cat == "kitchen_living" and ko for cat, ko in keywords)
