"""모든 수집기의 공통 뼈대.

흐름: fetch(가져오기) → parse(읽어내기) → save(저장)
Phase 2에서 재시도·지연·User-Agent 로테이션이 여기에 추가된다.
"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """외부 응답 구조가 바뀌어 읽어내지 못했을 때. 어떤 필드/셀렉터가 실패했는지 메시지에 담는다."""


@dataclass
class RunOptions:
    limit: int | None = None   # 소량 테스트용 상한
    dry_run: bool = False      # True면 DB에 저장하지 않고 화면에만 출력
    collected_at: date | None = None

    @property
    def today(self) -> date:
        return self.collected_at or date.today()


class BaseCollector(ABC):
    """서브클래스는 fetch / parse / save 세 가지를 채우면 된다."""

    name: str = "base"

    def __init__(self, options: RunOptions | None = None) -> None:
        self.options = options or RunOptions()

    # ---- 서브클래스가 구현 ----
    @abstractmethod
    def fetch(self, query: str) -> Any: ...

    @abstractmethod
    def parse(self, raw: Any, query: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def save(self, rows: list[dict[str, Any]]) -> int: ...

    # ---- 공통 실행 ----
    def run(self, query: str) -> list[dict[str, Any]]:
        logger.info("[%s] fetch: %s", self.name, query)
        raw = self.fetch(query)
        rows = self.parse(raw, query)
        if self.options.limit is not None:
            rows = rows[: self.options.limit]
        if self.options.dry_run:
            logger.info("[%s] dry-run: %d rows (저장 안 함)", self.name, len(rows))
        else:
            saved = self.save(rows)
            logger.info("[%s] saved %d rows", self.name, saved)
        return rows

    # ---- 예의 있는 지연 (해외 스크래핑용) ----
    @staticmethod
    def polite_sleep() -> None:
        delay = random.uniform(settings.request_delay_min_sec, settings.request_delay_max_sec)
        time.sleep(delay)
