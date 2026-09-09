"""테스트 공통: 가짜 API 키를 넣어 키 검사(require_*)를 통과시킨다."""
from __future__ import annotations

import pytest

from config import settings as s

FAKE = {
    "naver_hub_client_id": "hub-id",
    "naver_hub_client_secret": "hub-secret",
    "naver_ad_customer_id": "12345",
    "naver_ad_access_license": "license",
    "naver_ad_secret_key": "ad-secret",
    "coupang_access_key": "cp-access",
    "coupang_secret_key": "cp-secret",
}


@pytest.fixture(autouse=True)
def _fake_keys():
    # settings 는 frozen dataclass 라 object.__setattr__ 로 우회한다.
    original = {k: getattr(s.settings, k) for k in FAKE}
    for k, v in FAKE.items():
        object.__setattr__(s.settings, k, v)
    yield
    for k, v in original.items():
        object.__setattr__(s.settings, k, v)
