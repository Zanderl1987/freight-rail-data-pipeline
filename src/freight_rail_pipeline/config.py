from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline configuration.

    Dataclass defaults are static literals. Use `from_env()` to read
    environment variables / `.env` at call time -- constructing
    `PipelineConfig(...)` directly deliberately ignores the environment.
    """

    output_dir: Path = Path("data")
    log_dir: Path = Path("logs")
    log_level: str = "INFO"
    log_json: bool = False
    output_format: str = "parquet"
    partition_by: str = "date"
    max_retries: int = 3
    request_timeout_seconds: int = 30
    usda_socrata_resource_ids: dict[str, str] = field(
        default_factory=lambda: {
            "rail_carloadings": "tb7q-kn5i",
            "rail_service_metrics": "axkm-yjzy",
            "grain_rail_carloads": "27k8-utc2",
            "grain_rail_tariff_rates": "idbx-qf4w",
        }
    )
    fbx_base_url: str = "https://api.freightos.com/fd_external_apis/price_stats"
    fbx_api_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "log_dir", Path(self.log_dir))

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls(
            output_dir=Path(os.getenv("FREIGHT_PIPELINE_OUTPUT_DIR", "data")),
            log_dir=Path(os.getenv("FREIGHT_PIPELINE_LOG_DIR", "logs")),
            log_level=os.getenv("FREIGHT_PIPELINE_LOG_LEVEL", "INFO"),
            log_json=os.getenv("FREIGHT_PIPELINE_LOG_JSON", "false").lower() == "true",
            output_format=os.getenv("FREIGHT_PIPELINE_OUTPUT_FORMAT", "parquet"),
            partition_by=os.getenv("FREIGHT_PIPELINE_PARTITION_BY", "date"),
            max_retries=int(os.getenv("FREIGHT_PIPELINE_MAX_RETRIES", "3")),
            request_timeout_seconds=int(os.getenv("FREIGHT_PIPELINE_REQUEST_TIMEOUT", "30")),
            fbx_api_key=os.getenv("FREIGHTOS_FBX_API_KEY", ""),
        )

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
