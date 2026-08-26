from __future__ import annotations

import io
import logging
import re
from datetime import date
from typing import Any

import pandas as pd
import requests
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models.normalizer import DataNormalizer
from ..models.schemas import FMCContainerStats
from .base import BaseSource, SourceResult, retry_if_transient

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

# The landing page links workbooks as /wp-content/uploads/YYYY/MM/CFS_<year>_Data.xlsx
# (optionally "-updated"); the upload month is unpredictable, so URLs are always
# discovered from the page rather than constructed.
_XLSX_LINK_RE = re.compile(r'href="([^"]*?CFS_(\d{4})_Data(?:-updated)?\.xlsx)"')

_SHEETS: dict[str, str] = {
    "US Ports": "port",
    "Ocean Carriers": "carrier",
}


class FMCContainerizedSource(BaseSource):
    """Federal Maritime Commission Containerized Freight Statistics: quarterly
    US port and ocean-carrier (VOCC) laden/empty TEU plus tonnage, self-reported
    under OSRA 2022 (46 U.S.C. 41110). Coverage starts Q1 2024; FMC posts one
    XLSX per year on fmc.gov with a substantial publication lag."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._session: requests.Session | None = None

    @property
    def name(self) -> str:
        return "fmc"

    def fetch(self, snapshot_date: date | None = None, **kwargs: Any) -> SourceResult[Any]:
        self.log.info("Fetching FMC containerized freight statistics...")
        normalizer = DataNormalizer()
        records: list[FMCContainerStats] = []
        files: dict[str, int] = {}

        for year, xlsx_url in sorted(self._discover_workbook_urls().items()):
            content = self._download(xlsx_url)
            if content is None:
                continue
            year_records = self._parse_workbook(content, year, normalizer)
            files[xlsx_url.rsplit("/", 1)[-1]] = len(year_records)
            records.extend(year_records)

        if not records:
            log.warning("FMC: no workbook rows parsed; check %s", self.config.fmc_stats_page_url)

        return SourceResult(
            records=records,
            source_name=self.name,
            record_count=len(records),
            metadata={"files": files, "snapshot_date": str(snapshot_date or date.today())},
        )

    def _discover_workbook_urls(self) -> dict[int, str]:
        """Scrape the CFS landing page for per-year workbook URLs. When both a
        plain and an '-updated' revision exist for a year, keep the revision."""
        page = self._get(self.config.fmc_stats_page_url)
        found: dict[int, str] = {}
        for url, year_str in _XLSX_LINK_RE.findall(page):
            year = int(year_str)
            existing = found.get(year)
            if existing is None or ("-updated" in url and "-updated" not in existing):
                found[year] = url
        self.log.info("FMC: discovered %d workbook(s): %s", len(found), sorted(found))
        return found

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_transient,
    )
    def _get(self, url: str) -> str:
        response = self._http().get(
            url, headers=BROWSER_HEADERS, timeout=self.config.request_timeout_seconds
        )
        response.raise_for_status()
        return str(response.text)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_transient,
    )
    def _download(self, url: str) -> bytes | None:
        response = self._http().get(
            url, headers=BROWSER_HEADERS, timeout=self.config.request_timeout_seconds
        )
        response.raise_for_status()
        return bytes(response.content)

    def _parse_workbook(
        self, content: bytes, year: int, normalizer: DataNormalizer
    ) -> list[FMCContainerStats]:
        try:
            xl = pd.ExcelFile(io.BytesIO(content))
        except Exception as exc:
            log.warning("FMC %d workbook unreadable: %s", year, exc)
            return []
        records: list[FMCContainerStats] = []
        for sheet, entity_type in _SHEETS.items():
            if sheet not in xl.sheet_names:
                log.warning("FMC %d workbook missing sheet %r", year, sheet)
                continue
            frame = xl.parse(sheet, header=0, dtype=object)
            frame.columns = [str(c).strip() for c in frame.columns]
            for row in frame.to_dict(orient="records"):
                record = normalizer.normalize_fmc_container(row, entity_type)
                if record is not None:
                    records.append(record)
        self.log.info("FMC %d workbook: %d usable rows", year, len(records))
        return records

    def _http(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session
