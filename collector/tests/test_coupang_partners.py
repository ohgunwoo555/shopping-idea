from __future__ import annotations

import hashlib
import hmac
from datetime import date

import httpx
import pytest

from sources.base import ParseError, RunOptions
from sources.coupang_partners import SEARCH_PATH, CoupangPartnersCollector, build_authorization, format_row, signed_datetime


def _product(price: int, rocket: bool = False):
    return {"productId": 1, "productName": "x", "productPrice": price, "isRocket": rocket, "rank": 1}


def test_signed_datetime_format():
    assert signed_datetime(0) == "700101T000000Z"


def test_authorization_header_matches_spec():
    auth = build_authorization("GET", SEARCH_PATH, "keyword=a&limit=5", now=0)
    msg = "700101T000000Z" + "GET" + SEARCH_PATH + "keyword=a&limit=5"
    sig = hmac.new(b"cp-secret", msg.encode(), hashlib.sha256).hexdigest()
    assert auth == f"CEA algorithm=HmacSHA256, access-key=cp-access, signed-date=700101T000000Z, signature={sig}"


def test_price_stats_and_rocket_ratio():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers["Authorization"]
        return httpx.Response(
            200,
            json={"rCode": "0", "rMessage": "", "data": {"landingUrl": "u", "productData": [
                _product(3000, True), _product(5000), _product(4000, True), _product(0)]}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    c = CoupangPartnersCollector(RunOptions(dry_run=True, collected_at=date(2026, 9, 9)), client=client, max_items=50)
    row = c.run("실리콘 주걱")[0]
    assert "limit=50" in captured["url"] and "keyword=" in captured["url"]
    assert captured["auth"].startswith("CEA algorithm=HmacSHA256")
    assert row["coupang_sample_size"] == 4
    assert row["coupang_min_price_krw"] == 3000
    assert row["coupang_avg_price_krw"] == 4000
    assert row["coupang_median_price_krw"] == 4000
    assert row["coupang_rocket_ratio"] == 0.5
    assert "50%" in format_row(row)


def test_max_items_capped_at_100():
    assert CoupangPartnersCollector(RunOptions(dry_run=True), max_items=500).max_items == 100


def test_empty_result_gives_none_prices():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"rCode": "0", "data": {"productData": []}})))
    row = CoupangPartnersCollector(RunOptions(dry_run=True), client=client).run("x")[0]
    assert row["coupang_avg_price_krw"] is None and row["coupang_rocket_ratio"] is None
    assert "-" in format_row(row)


def test_rcode_error_and_parse_error():
    c = CoupangPartnersCollector(RunOptions(dry_run=True))
    with pytest.raises(RuntimeError, match="rCode"):
        c.parse({"rCode": "400", "rMessage": "bad"}, "x")
    with pytest.raises(ParseError, match="productData"):
        c.parse({"rCode": "0", "data": {}}, "x")
