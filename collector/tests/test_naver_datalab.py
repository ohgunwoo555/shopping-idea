from __future__ import annotations

from datetime import date

import httpx
import pytest

from config import settings as s
from sources.base import ParseError, RunOptions
from sources.naver_datalab import NaverDatalabCollector, trend_change


def _series(title: str, values: list[float]):
    return {"title": title, "keyword": [title], "data": [{"period": f"d{i}", "ratio": v} for i, v in enumerate(values)]}


def test_trend_change():
    assert trend_change([10] * 30 + [12] * 30, 30) == 0.2
    assert trend_change([10] * 59, 30) is None          # 데이터 부족
    assert trend_change([0] * 30 + [5] * 30, 30) is None  # 직전 구간이 0


def test_search_and_shopping_requests():
    calls: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(req.content)
        calls.append((req.url.path, body))
        assert req.headers["X-NCP-APIGW-API-KEY-ID"] == "hub-id"
        if "search" in req.url.path and "shopping" not in req.url.path:
            names = [g["groupName"] for g in body["keywordGroups"]]
            return httpx.Response(200, json={"results": [_series(n, [10] * 30 + [15] * 30) for n in names]})
        names = [k["name"] for k in body["keyword"]]
        assert body["category"] == "50000008"
        return httpx.Response(200, json={"results": [_series(n, [20] * 30 + [10] * 30) for n in names]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    c = NaverDatalabCollector(RunOptions(dry_run=True, collected_at=date(2026, 9, 9)), client=client, shopping_cid="50000008")
    rows = c.collect_many(["a", "b"], {"a": "kitchen_living", "b": "kitchen_living"})
    assert len(calls) == 2
    assert calls[0][0].endswith("/datalab/v1/search")
    assert calls[0][1]["startDate"] == "2026-07-11" and calls[0][1]["endDate"] == "2026-09-08"
    assert rows[0] == {
        "keyword": "a", "collected_at": "2026-09-09", "category": "kitchen_living",
        "search_trend_30d": 0.5, "shopping_click_trend_30d": -0.5,
    }


def test_without_cid_only_search_is_called(caplog):
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: (calls.append(r.url.path), httpx.Response(200, json={"results": [_series("a", [1] * 60)]}))[1]))
    rows = NaverDatalabCollector(RunOptions(dry_run=True), client=client).collect_many(["a"])
    assert calls == ["/datalab/v1/search"]
    assert rows[0]["shopping_click_trend_30d"] is None
    assert "cid" in caplog.text


def test_openapi_style_paths_and_headers():
    object.__setattr__(s.settings, "naver_hub_auth_style", "openapi")
    try:
        seen = {}

        def handler(req):
            seen["path"] = req.url.path
            seen["hdr"] = req.headers.get("X-Naver-Client-Id")
            return httpx.Response(200, json={"results": [_series("a", [1] * 60)]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        NaverDatalabCollector(RunOptions(dry_run=True), client=client).collect_many(["a"])
        assert seen == {"path": "/v1/datalab/search", "hdr": "hub-id"}
    finally:
        object.__setattr__(s.settings, "naver_hub_auth_style", "ncp")


def test_parse_errors_name_missing_field():
    c = NaverDatalabCollector(RunOptions(dry_run=True))
    with pytest.raises(ParseError, match="results"):
        c._results({"nope": 1}, "search")
    with pytest.raises(ParseError, match="ratio"):
        c._trend({"title": "a", "data": [{"period": "x"}]}, "a", "search")


def test_env_path_override_wins():
    object.__setattr__(s.settings, "naver_hub_search_path", "/custom/search")
    try:
        seen = []
        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: (seen.append(r.url.path), httpx.Response(200, json={"results": [_series("a", [1] * 60)]}))[1]))
        NaverDatalabCollector(RunOptions(dry_run=True), client=client).collect_many(["a"])
        assert seen == ["/custom/search"]
    finally:
        object.__setattr__(s.settings, "naver_hub_search_path", "")


def test_probe_reports_first_live_path(capsys):
    from sources.naver_datalab import probe

    def handler(req):
        if req.url.path == "/datalab/v1/search/trend":
            return httpx.Response(200, json={"results": []})
        if req.url.path == "/datalab/v1/shopping/category/keywords":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, text="not found")

    found = probe("50000008", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert found == {"search": "/datalab/v1/search/trend", "shopping": "/datalab/v1/shopping/category/keywords"}
    out = capsys.readouterr().out
    assert "NAVER_HUB_SEARCH_PATH=/datalab/v1/search/trend" in out
    assert "✘ 404" in out
