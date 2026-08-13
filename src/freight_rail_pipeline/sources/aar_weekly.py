from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
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
from ..models import AARWeeklyTraffic
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

# AAR publishes a weekly rail-traffic press release (US/Canada/Mexico/North
# America carloads + intermodal units) as a 4-page PDF under
# wp-content/uploads/.../railtraffic.pdf. The latest release is linked from
# the weekly-traffic category feed (the site-wide feed only carries general
# news; verified live 2026-08-12). Backfill is rate-limit-gated, so this
# source is forward-only with a slow fallback to the archive list.
FEED_URL = "https://www.aar.org/aar_news/weekly-rail-traffic-data/feed/"
ARCHIVE_URL = "https://www.aar.org/aar_news/weekly-rail-traffic-data/"

REGION_MAP = {
    "U.S. Rail Traffic": "US",
    "Canadian Rail Traffic": "Canada",
    "Mexican Rail Traffic": "Mexico",
    "North American Rail Traffic": "North America",
}

_TITLE_RE = re.compile(
    r"^(U\.S\. Rail Traffic|Canadian Rail Traffic|Mexican Rail Traffic|"
    r"North American Rail Traffic)\d*$"
)
_WEEK_RE = re.compile(r"Week\s+(\d+),\s+(\d{4})")
_ENDED_RE = re.compile(r"Ended\s+([A-Za-z]+ \d{1,2}, \d{4})")
_INT_RE = re.compile(r"^\d[\d,]*$")
_HEADER_TOKENS = {"this week", "year-to-date", "cars", "vs 2025", "cumulative"}

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _is_retryable_aar(exc: BaseException) -> bool:
    if isinstance(exc, requests.RequestException):
        status: int | None = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None:
            return True
        return status == 403 or status == 429 or status >= 500
    return False


def _rows_start(lines: list[str]) -> int:
    for idx, line in enumerate(lines):
        if line.lower() != "this week":
            continue
        j = idx + 1
        while j < len(lines) - 1:
            token = lines[j].lower()
            if token in _HEADER_TOKENS or token.startswith("avg/wk"):
                j += 1
                continue
            if _INT_RE.match(lines[j + 1]):
                return j
            j += 1
        return -1
    return -1


def parse_aar_page(text: str) -> list[dict[str, Any]]:
    """Extract one region's table from a page of the AAR weekly PDF text.

    The page layout is a fixed 7-line header ("This Week ... vs 2025") followed
    by 13 rows of (category, cars, yoy%, cumulative, avg/wk, yoy%) and a
    footnote. Returns raw dicts ready for DataNormalizer.normalize_aar_weekly."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    region = None
    for line in lines[:8]:
        match = _TITLE_RE.match(line)
        if match:
            region = REGION_MAP[match.group(1)]
            break
    week_match = _WEEK_RE.search(text)
    ended_match = _ENDED_RE.search(text)
    if region is None or week_match is None or ended_match is None:
        return []
    try:
        week_end = datetime.strptime(ended_match.group(1), "%B %d, %Y").date()
    except ValueError:
        return []

    start = _rows_start(lines)
    if start < 0:
        return []

    rows: list[dict[str, Any]] = []
    i = start
    while i + 5 < len(lines):
        label = lines[i]
        values = lines[i + 1 : i + 6]
        if not _INT_RE.match(values[0]):
            break
        rows.append(
            {
                "region": region,
                "week_number": int(week_match.group(1)),
                "year": int(week_match.group(2)),
                "week_end_date": week_end.isoformat(),
                "category": label,
                "this_week_cars": values[0].replace(",", ""),
                "this_week_yoy_pct": values[1],
                "ytd_cars": values[2].replace(",", ""),
                "ytd_avg_week_cars": values[3].replace(",", ""),
                "ytd_yoy_pct": values[4],
            }
        )
        i += 6
    return rows


class AARWeeklyTrafficSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._normalizer = DataNormalizer()

    @property
    def name(self) -> str:
        return "aar_weekly"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            release_url = self._latest_release_url()
            if not release_url:
                warnings.append("No weekly rail-traffic release found in the AAR feed")
            else:
                self.log.info("Latest AAR release: %s", release_url)
        except requests.RequestException as exc:
            warnings.append(f"Cannot reach AAR feed: {exc}")
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[AARWeeklyTraffic]:
        self.log.info("Fetching AAR weekly rail traffic...")
        release_url = self._latest_release_url()
        if not release_url:
            return SourceResult(
                records=[],
                source_name=self.name,
                success=False,
                error=f"No weekly rail-traffic release found in AAR feed {FEED_URL}",
            )

        pdf_url = self._release_pdf_url(release_url)
        if not pdf_url:
            return SourceResult(
                records=[],
                source_name=self.name,
                success=False,
                error=f"No PDF found on AAR release page {release_url}",
            )

        self.log.info("Parsing AAR PDF %s", pdf_url)
        records = self._parse_pdf(pdf_url)
        self.log.info("Parsed %d AAR weekly rows", len(records))

        return SourceResult(
            records=records,
            source_name=self.name,
            record_count=len(records),
            metadata={
                "release_url": release_url,
                "pdf_url": pdf_url,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_exception(_is_retryable_aar),
    )
    def _latest_release_url(self) -> str | None:
        resp = requests.get(FEED_URL, timeout=self.config.request_timeout_seconds, headers=_UA)
        resp.raise_for_status()
        try:
            # AAR's own RSS feed over HTTPS; not attacker-controlled input.
            root = ET.fromstring(resp.content)  # noqa: S314
        except ET.ParseError as exc:
            log.warning("AAR feed parse failed: %s", exc)
            return self._latest_release_url_from_archive()
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            if "weekly rail traffic" in title.lower() and link:
                return link
        return self._latest_release_url_from_archive()

    def _latest_release_url_from_archive(self) -> str | None:
        resp = requests.get(
            ARCHIVE_URL, timeout=self.config.request_timeout_seconds, headers=_UA
        )
        resp.raise_for_status()
        matches: list[str] = re.findall(
            r'href="(https://[^"]*aar-reports-weekly-rail-traffic[^"]*/)"',
            resp.text,
            re.I,
        )
        return matches[0] if matches else None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_exception(_is_retryable_aar),
    )
    def _release_pdf_url(self, release_url: str) -> str | None:
        resp = requests.get(
            release_url, timeout=self.config.request_timeout_seconds, headers=_UA
        )
        resp.raise_for_status()
        # The release page embeds the PDF as a bare URL (sometimes with
        # utm_* query params), not inside an href attribute.
        candidates: list[str] = re.findall(r"https?://[^\s\"'<>]+\.pdf", resp.text, re.I)
        candidates += re.findall(r'href="([^"]*\.pdf)"', resp.text, re.I)

        seen: set[str] = set()
        cleaned: list[str] = []
        for href in candidates:
            url = html.unescape(href).split("?", 1)[0]
            if url.lower().endswith(".pdf") and url not in seen:
                seen.add(url)
                cleaned.append(url)
        for url in cleaned:
            if "railtraffic" in url.lower():
                return url
        return cleaned[0] if cleaned else None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_exception(_is_retryable_aar),
    )
    def _parse_pdf(self, pdf_url: str) -> list[AARWeeklyTraffic]:
        time.sleep(1.0)
        resp = requests.get(pdf_url, timeout=self.config.request_timeout_seconds, headers=_UA)
        resp.raise_for_status()

        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is required for the AAR weekly source") from exc

        records: list[AARWeeklyTraffic] = []
        with fitz.open(stream=resp.content, filetype="pdf") as doc:
            for page in doc:
                if page.number >= 4:
                    break
                for raw in parse_aar_page(page.get_text()):
                    record = self._normalizer.normalize_aar_weekly(raw)
                    if record is not None:
                        records.append(record)
        return records
