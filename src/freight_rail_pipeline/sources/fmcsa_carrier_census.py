from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sodapy import Socrata
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import MotorCarrierCensus
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult, retry_if_transient

log = logging.getLogger(__name__)

# FMCSA's own data-dissemination pages (ai.fmcsa.dot.gov, www.fmcsa.dot.gov) are
# behind an Akamai bot-detection WAF that 403s automated requests -- confirmed
# live 2026-08-03, not a login/auth wall, just blocked at the edge. The same
# carrier census is mirrored on Socrata under datahub.transportation.gov (the
# same domain FRA Safety already uses), which is publicly queryable.
DOMAIN = "datahub.transportation.gov"
RESOURCE_ID = "kjg3-diqy"  # SMS Input - Motor Carrier Census Information

# PII SAFETY: only ever select these non-identity columns. The source dataset
# also has legal_name/dba_name/phy_street/mailing_*/email_address/telephone for
# 2M+ individual carriers (many are sole proprietors) -- server-side $select
# means that data never leaves Socrata's servers for this pipeline. User
# decision 2026-08-03: strip PII entirely rather than filter client-side.
# Do not widen this column list without re-checking that decision.
SELECT_COLUMNS = (
    "dot_number,carrier_operation,phy_state,nbr_power_unit,"
    "driver_total,recent_mileage,recent_mileage_year,mcs150_date"
)


class FMCSACarrierCensusSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._client: Socrata | None = None

    @property
    def name(self) -> str:
        return "fmcsa_carrier_census"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            client = self._get_client()
            client.get(RESOURCE_ID, select=SELECT_COLUMNS, limit=1)
            self.log.info("FMCSA carrier census resource %s verified", RESOURCE_ID)
        except Exception as exc:
            warnings.append(f"FMCSA carrier census resource {RESOURCE_ID} failed: {exc}")
        finally:
            self._close_client()
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[MotorCarrierCensus]:
        self.log.info("Fetching motor carrier census from FMCSA (PII columns excluded)...")
        raw_results = self._fetch_carriers()

        normalizer = DataNormalizer()
        normalized: list[MotorCarrierCensus] = []
        for raw in raw_results:
            record = normalizer.normalize_motor_carrier_census(raw, snapshot_date=snapshot_date)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "raw_count": len(raw_results),
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        retry=retry_if_transient,
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_carriers(self) -> list[dict[str, Any]]:
        client = self._get_client()
        try:
            results: list[dict[str, Any]] = []
            page = 0
            limit = 5000
            while True:
                batch = client.get(
                    RESOURCE_ID,
                    select=SELECT_COLUMNS,
                    limit=limit,
                    offset=page * limit,
                    order="dot_number",
                )
                if not batch:
                    break
                results.extend(batch)
                page += 1
                if len(batch) < limit:
                    break

            self.log.info("Fetched %d raw carrier census records from FMCSA", len(results))
            return results
        finally:
            self._close_client()

    def _get_client(self) -> Socrata:
        if self._client is None:
            app_token = self.get_credential("FRA_SOCRATA_APP_TOKEN")
            self._client = Socrata(
                DOMAIN,
                app_token=app_token or None,
                timeout=self.config.request_timeout_seconds,
            )
        return self._client

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                log.debug("Error closing Socrata client", exc_info=True)
            self._client = None
