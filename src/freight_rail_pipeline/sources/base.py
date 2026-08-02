from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Generic, TypeVar

from tenacity import (
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import PipelineConfig

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class SourceResult(Generic[T]):
    records: list[T]
    source_name: str
    record_count: int = 0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.record_count == 0:
            self.record_count = len(self.records)


class BaseSource(ABC):
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def fetch(self, snapshot_date: date | None = None, **kwargs: Any) -> SourceResult[Any]: ...

    def _build_retry_decorator(self) -> dict[str, Any]:
        return {
            "stop": stop_after_attempt(self.config.max_retries),
            "wait": wait_exponential_jitter(initial=2, max=60, jitter=2),
            "retry": retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
            "before_sleep": before_sleep_log(log, logging.WARNING),
            "reraise": True,
        }

    def get_credential(self, key: str) -> str | None:
        import os

        return os.getenv(key)

    def validate(self) -> list[str]:
        warnings: list[str] = []
        return warnings
