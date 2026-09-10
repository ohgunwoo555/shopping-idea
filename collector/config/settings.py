"""환경변수·공통 설정을 한 곳에서 읽는다.

.env 파일(레포 루트 또는 collector/)의 값을 읽어 온다.
다른 모듈은 `from config.settings import settings` 로 가져다 쓴다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# collector/config/settings.py → 레포 루트는 두 단계 위
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COLLECTOR_ROOT = Path(__file__).resolve().parents[1]

# 루트 .env 를 먼저, collector/.env 가 있으면 그것이 덮어쓴다.
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_COLLECTOR_ROOT / ".env", override=True)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _missing(*pairs: tuple[str, str]) -> list[str]:
    return [name for name, value in pairs if not value]


@dataclass(frozen=True)
class Settings:
    # --- Supabase ---
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_KEY"))

    # --- NAVER API HUB (데이터랩) ---
    naver_hub_client_id: str = field(default_factory=lambda: _env("NAVER_HUB_CLIENT_ID"))
    naver_hub_client_secret: str = field(default_factory=lambda: _env("NAVER_HUB_CLIENT_SECRET"))
    naver_hub_base_url: str = field(
        default_factory=lambda: _env("NAVER_HUB_BASE_URL", "https://naverapihub.apigw.ntruss.com").rstrip("/")
    )
    naver_hub_auth_style: str = field(default_factory=lambda: _env("NAVER_HUB_AUTH_STYLE", "ncp").lower())
    # --probe 로 찾은 경로를 여기 고정할 수 있다. 비우면 auth_style 의 기본 경로를 쓴다.
    naver_hub_search_path: str = field(default_factory=lambda: _env("NAVER_HUB_SEARCH_PATH"))
    naver_hub_shopping_path: str = field(default_factory=lambda: _env("NAVER_HUB_SHOPPING_PATH"))

    # --- 네이버 검색광고 API ---
    naver_ad_customer_id: str = field(default_factory=lambda: _env("NAVER_AD_CUSTOMER_ID"))
    naver_ad_access_license: str = field(default_factory=lambda: _env("NAVER_AD_ACCESS_LICENSE"))
    naver_ad_secret_key: str = field(default_factory=lambda: _env("NAVER_AD_SECRET_KEY"))
    naver_ad_base_url: str = "https://api.naver.com"

    # --- 쿠팡 파트너스 API ---
    coupang_access_key: str = field(default_factory=lambda: _env("COUPANG_ACCESS_KEY"))
    coupang_secret_key: str = field(default_factory=lambda: _env("COUPANG_SECRET_KEY"))
    coupang_base_url: str = "https://api-gateway.coupang.com"
    coupang_max_items: int = 50          # 가격 통계에 쓸 상품 수 (API 최대 100)

    proxy_url: str = field(default_factory=lambda: _env("PROXY_URL"))

    # --- 환율 (나중에 API로 대체) ---
    usd_krw_rate: float = field(default_factory=lambda: float(_env("USD_KRW_RATE", "1380")))

    # --- 해외 스크래핑 예의 (Phase 2에서 사용) ---
    request_delay_min_sec: float = 2.0
    request_delay_max_sec: float = 5.0
    max_retries: int = 3

    # --- 데이터랩 추이 계산 ---
    trend_window_days: int = 30          # 최근 30일 vs 직전 30일 비교

    # --- 기회 점수 가중치 (CLAUDE.md 6절) ---
    weight_demand: float = 0.4
    weight_competition: float = 0.35
    weight_margin: float = 0.25
    landed_cost_factor: float = 1.35     # 배송·관세·수수료 계수
    min_margin_rate: float = 0.25        # 이보다 낮으면 후보 제외
    margin_cap: float = 0.6
    # 경쟁 점수: 검색광고 경쟁정도(낮음0/중간0.5/높음1) 60% + 월간 광고클릭 로그 정규화 40%
    comp_idx_weight: float = 0.6
    comp_click_weight: float = 0.4

    # --- 경로 ---
    repo_root: Path = _REPO_ROOT
    collector_root: Path = _COLLECTOR_ROOT
    categories_path: Path = _COLLECTOR_ROOT / "config" / "categories.yaml"

    # --- 키 검사: 없으면 무엇을 해야 하는지 바로 알려준다 ---
    def require_naver_hub(self) -> None:
        missing = _missing(
            ("NAVER_HUB_CLIENT_ID", self.naver_hub_client_id),
            ("NAVER_HUB_CLIENT_SECRET", self.naver_hub_client_secret),
        )
        if missing:
            raise RuntimeError(
                f"{', '.join(missing)} 이 비어 있습니다.\n"
                "네이버클라우드 콘솔 > Services > Application Services > NAVER API HUB > Application 등록\n"
                "(데이터랩 검색어트렌드·쇼핑인사이트 선택) 후 인증 정보를 .env 에 넣으세요."
            )

    def require_naver_ad(self) -> None:
        missing = _missing(
            ("NAVER_AD_CUSTOMER_ID", self.naver_ad_customer_id),
            ("NAVER_AD_ACCESS_LICENSE", self.naver_ad_access_license),
            ("NAVER_AD_SECRET_KEY", self.naver_ad_secret_key),
        )
        if missing:
            raise RuntimeError(
                f"{', '.join(missing)} 이 비어 있습니다.\n"
                "https://searchad.naver.com 로그인 > 도구 > API 사용 관리 > 네이버 검색광고 API 서비스 신청 후\n"
                "액세스라이선스·비밀키와 화면 오른쪽 위 CUSTOMER_ID 를 .env 에 넣으세요."
            )

    def require_coupang(self) -> None:
        missing = _missing(
            ("COUPANG_ACCESS_KEY", self.coupang_access_key),
            ("COUPANG_SECRET_KEY", self.coupang_secret_key),
        )
        if missing:
            raise RuntimeError(
                f"{', '.join(missing)} 이 비어 있습니다.\n"
                "https://partners.coupang.com 로그인 > 링크 생성 > API > 키 발급 후 .env 에 넣으세요."
            )

    def require_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_KEY 가 비어 있습니다. "
                "Supabase 대시보드 > Project Settings > API 에서 복사해 .env 에 넣으세요."
            )


settings = Settings()
