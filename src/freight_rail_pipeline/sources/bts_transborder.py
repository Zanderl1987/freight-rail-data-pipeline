from __future__ import annotations

import csv
import io
import logging
import re
import time
import zipfile
from datetime import date
from typing import Any

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import PipelineConfig
from ..models import TransBorderFreight
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

# BTS publishes monthly raw TransBorder files (US-Canada/Mexico trade by mode,
# port, and commodity) as zips linked from this page. The 403s we hit on
# bursts are Akamai rate-limit protection, not auth -- pacing requests and
# sending a Referer header resolves them (verified live 2026-08-12).
RAW_DATA_PAGE = "https://www.bts.gov/topics/transborder-raw-data"
ZIP_RE = re.compile(r'href="(/sites/bts\.dot\.gov/files/transborder-raw/\d{4}/[^"]+\.zip)"', re.I)

_MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bts.gov/",
}

# Akamai burst protection: space requests out even when they fail and retry.
_PACE_SECONDS = 3.0
_last_request_at = 0.0


def _pace() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _PACE_SECONDS:
        time.sleep(_PACE_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def _is_retryable_transborder(exc: BaseException) -> bool:
    status = None
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    elif isinstance(exc, requests.RequestException):
        return True
    if isinstance(exc, (requests.RequestException, TimeoutError, ConnectionError)):
        return True
    return isinstance(status, int) and (status == 403 or status == 429 or status >= 500)


class BTSTransBorderSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._normalizer = DataNormalizer()

    @property
    def name(self) -> str:
        return "bts_transborder"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            links = self._list_zip_links()
            if not links:
                warnings.append(f"No TransBorder monthly zips found on {RAW_DATA_PAGE}")
            else:
                self.log.info("Found %d TransBorder monthly zip links", len(links))
        except requests.RequestException as exc:
            warnings.append(f"Cannot reach TransBorder raw-data page: {exc}")
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[TransBorderFreight]:
        self.log.info("Fetching TransBorder monthly raw files...")
        links = self._list_zip_links()
        if not links:
            return SourceResult(
                records=[],
                source_name=self.name,
                success=False,
                error=f"No TransBorder monthly zip links found on {RAW_DATA_PAGE}",
            )

        target = self._select_zip(links, snapshot_date)
        if target is None:
            return SourceResult(
                records=[],
                source_name=self.name,
                success=False,
                error=f"No TransBorder zip found for {snapshot_date or 'latest month'}",
            )

        year, month, url = target
        self.log.info("Selected TransBorder zip: %s (%d-%02d)", url, year, month)
        records = self._fetch_month_zip(url)
        self.log.info("Parsed %d TransBorder rows from %d-%02d", len(records), year, month)

        return SourceResult(
            records=records,
            source_name=self.name,
            record_count=len(records),
            metadata={
                "year": year,
                "month": month,
                "url": url,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    def _list_zip_links(self) -> list[tuple[int, int, str]]:
        _pace()
        resp = requests.get(
            RAW_DATA_PAGE, timeout=self.config.request_timeout_seconds, headers=_UA
        )
        resp.raise_for_status()
        links: list[tuple[int, int, str]] = []
        for href in ZIP_RE.findall(resp.text):
            url = "https://www.bts.gov" + href
            parsed = self._parse_month_year(href)
            if parsed is None:
                continue
            links.append((parsed[0], parsed[1], url))
        return sorted(set(links), reverse=True)

    def _select_zip(
        self, links: list[tuple[int, int, str]], snapshot_date: date | None
    ) -> tuple[int, int, str] | None:
        ordered = sorted(links, reverse=True)
        if snapshot_date is None:
            return ordered[0] if ordered else None
        for year, month, url in ordered:
            if (year, month) <= (snapshot_date.year, snapshot_date.month):
                return (year, month, url)
        # Every published zip is newer than the snapshot; fetching newer data
        # would violate the snapshot semantics, so signal no target.
        return None

    def _parse_month_year(self, href: str) -> tuple[int, int] | None:
        m = re.search(r"transborder-raw/(\d{4})/([^/]+)\.zip$", href, re.I)
        if not m:
            return None
        year = int(m.group(1))
        name = m.group(2).lower()
        for idx, month_name in enumerate(_MONTH_NAMES, start=1):
            if month_name in name or month_name[:3] in name:
                return (year, idx)
        return None

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=3, max=60, jitter=3),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_exception(_is_retryable_transborder),
    )
    def _fetch_month_zip(self, url: str) -> list[TransBorderFreight]:
        _pace()
        resp = requests.get(url, timeout=self.config.request_timeout_seconds, headers=_UA)
        resp.raise_for_status()
        if resp.headers.get("Content-Type", "").startswith("text/html"):
            # Akamai serves an HTML challenge page instead of the zip on burst
            # rate limits; treat it as a retryable failure.
            raise requests.HTTPError(
                f"Akamai page returned instead of zip for {url}", response=resp
            )

        records: list[TransBorderFreight] = []
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        for name in sorted(zf.namelist()):
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
                file_tag = name.rsplit(".", 1)[0].split("_", 1)[0]
                for row in csv.DictReader(text):
                    record = self._normalizer.normalize_transborder_freight(
                        dict(row), source_file=file_tag
                    )
                    if record is not None:
                        records.append(record)
        return records
