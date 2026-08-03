from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Generic, TypeVar

import requests
from tenacity import retry_if_exception

from ..config import PipelineConfig

log = logging.getLogger(__name__)

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    """Retry only transient failures -- network errors, timeouts, 429/5xx.

    Matches DECISION-007 ("fail fast on 4xx"): a 4xx response must not be
    retried. Covers requests.HTTPError and sodapy.SocrataError (which carries
    the failing status on `status`/`status_code`) plus IOError raised by the
    FBX source for a 429.
    """
    if isinstance(exc, (ConnectionError, TimeoutError, IOError)):
        return True
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    else:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return isinstance(status, int) and status >= 500


retry_if_transient = retry_if_exception(_is_retryable)


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

    def get_credential(self, key: str) -> str | None:
        import os

        return os.getenv(key)

    def validate(self) -> list[str]:
        warnings: list[str] = []
        return warnings
