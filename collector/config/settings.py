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


@dataclass(frozen=True)
class Settings:
    # --- 외부 서비스 키 ---
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_KEY"))
    naver_client_id: str = field(default_factory=lambda: _env("NAVER_CLIENT_ID"))
    naver_client_secret: str = field(default_factory=lambda: _env("NAVER_CLIENT_SECRET"))
    proxy_url: str = field(default_factory=lambda: _env("PROXY_URL"))

    # --- 환율 (나중에 API로 대체) ---
    usd_krw_rate: float = field(default_factory=lambda: float(_env("USD_KRW_RATE", "1380")))

    # --- 해외 스크래핑 예의 (Phase 2에서 사용) ---
    request_delay_min_sec: float = 2.0
    request_delay_max_sec: float = 5.0
    max_retries: int = 3

    # --- 네이버 API 호출 설정 ---
    naver_page_size: int = 100        # API 최대값
    naver_max_items: int = 300        # 판매처 수 추정에 쓸 최대 상품 수 (3페이지)

    # --- 기회 점수 가중치 (CLAUDE.md 6절) ---
    weight_demand: float = 0.4
    weight_competition: float = 0.35
    weight_margin: float = 0.25
    landed_cost_factor: float = 1.35  # 배송·관세·수수료 계수
    min_margin_rate: float = 0.25     # 이보다 낮으면 후보 제외
    margin_cap: float = 0.6

    # --- 경로 ---
    repo_root: Path = _REPO_ROOT
    collector_root: Path = _COLLECTOR_ROOT
    categories_path: Path = _COLLECTOR_ROOT / "config" / "categories.yaml"

    def require_naver(self) -> None:
        """네이버 키가 없으면 무엇을 해야 하는지 바로 알려준다."""
        if not self.naver_client_id or not self.naver_client_secret:
            raise RuntimeError(
                "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 비어 있습니다.\n"
                "1) https://developers.naver.com 에서 애플리케이션 등록\n"
                "2) '검색' 과 '데이터랩(쇼핑인사이트)' API 사용 설정\n"
                "3) 레포 루트의 .env.example 을 .env 로 복사한 뒤 키를 채우세요."
            )

    def require_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_KEY 가 비어 있습니다. "
                "Supabase 대시보드 > Project Settings > API 에서 복사해 .env 에 넣으세요."
            )


settings = Settings()
