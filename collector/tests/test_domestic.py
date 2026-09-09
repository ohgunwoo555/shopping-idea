from __future__ import annotations

from datetime import date

import httpx

from sources import domestic


def test_merge_three_sources_and_survive_one_failure(monkeypatch, caplog):
    """검색광고·데이터랩은 성공, 쿠팡은 401 → 실패해도 나머지 두 소스 값은 합쳐진다."""
    import json

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/keywordstool":
            hints = req.url.params["hintKeywords"].split(",")
            return httpx.Response(200, json={"keywordList": [
                {"relKeyword": h, "monthlyPcQcCnt": "100", "monthlyMobileQcCnt": "900",
                 "monthlyAvePcClkCnt": 1, "monthlyAveMobileClkCnt": 9, "plAvgDepth": 8, "compIdx": "낮음"} for h in hints]})
        if p.startswith("/v2/providers"):
            return httpx.Response(401, text="unauthorized")
        body = json.loads(req.content)
        names = [g["groupName"] for g in body.get("keywordGroups", [])] or [k["name"] for k in body["keyword"]]
        return httpx.Response(200, json={"results": [
            {"title": n, "data": [{"period": "x", "ratio": 10}] * 30 + [{"period": "y", "ratio": 11}] * 30} for n in names]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real_client(transport=transport))
    monkeypatch.setattr(domestic, "category_meta", lambda cat: {"naver_shopping_cid": "50000008"})

    rows = domestic.collect_domestic([("kitchen_living", "실리콘 주걱"), ("kitchen_living", "채소 다지기")])
    assert len(rows) == 2
    r = rows[0]
    assert r["keyword"] == "실리콘 주걱" and r["category"] == "kitchen_living"
    assert r["ad_comp_idx"] == "낮음" and r["ad_monthly_clicks"] == 10
    assert r["search_trend_30d"] == 0.1 and r["shopping_click_trend_30d"] == 0.1
    assert "coupang_avg_price_krw" not in r
    assert "[coupang]" in caplog.text and "401" in caplog.text
    text = domestic.format_row(r)
    assert "쿠팡 결과 없음" in text and "낮음" in text
