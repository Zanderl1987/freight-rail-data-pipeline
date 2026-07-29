from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PipelineConfig:
    output_dir: Path = Path(
        os.getenv("FREIGHT_PIPELINE_OUTPUT_DIR", "data")
    )
    log_dir: Path = Path(
        os.getenv("FREIGHT_PIPELINE_LOG_DIR", "logs")
    )
    log_level: str = os.getenv("FREIGHT_PIPELINE_LOG_LEVEL", "INFO")
    log_json: bool = os.getenv("FREIGHT_PIPELINE_LOG_JSON", "false").lower() == "true"

    output_format: str = os.getenv("FREIGHT_PIPELINE_OUTPUT_FORMAT", "parquet")
    partition_by: str = os.getenv("FREIGHT_PIPELINE_PARTITION_BY", "date")

    max_retries: int = int(os.getenv("FREIGHT_PIPELINE_MAX_RETRIES", "3"))
    request_timeout_seconds: int = int(
        os.getenv("FREIGHT_PIPELINE_REQUEST_TIMEOUT", "30")
    )

    usda_socrata_resource_ids: dict[str, str] = field(default_factory=lambda: {
        "rail_carloadings": "swcm-ytjc",
        "rail_service_metrics": "jvfn-6e7j",
    })

    fbx_base_url: str = "https://api.freightos.com/fd_external_apis/price_stats"

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls()

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
