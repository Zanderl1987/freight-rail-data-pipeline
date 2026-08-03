from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PipelineConfig:
    output_dir: Path = Path(os.getenv("FREIGHT_PIPELINE_OUTPUT_DIR", "data"))
    log_dir: Path = Path(os.getenv("FREIGHT_PIPELINE_LOG_DIR", "logs"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "log_dir", Path(self.log_dir))

    log_level: str = os.getenv("FREIGHT_PIPELINE_LOG_LEVEL", "INFO")
    log_json: bool = os.getenv("FREIGHT_PIPELINE_LOG_JSON", "false").lower() == "true"

    output_format: str = os.getenv("FREIGHT_PIPELINE_OUTPUT_FORMAT", "parquet")
    partition_by: str = os.getenv("FREIGHT_PIPELINE_PARTITION_BY", "date")

    max_retries: int = int(os.getenv("FREIGHT_PIPELINE_MAX_RETRIES", "3"))
    request_timeout_seconds: int = int(os.getenv("FREIGHT_PIPELINE_REQUEST_TIMEOUT", "30"))

    usda_socrata_resource_ids: dict[str, str] = field(
        default_factory=lambda: {
            "rail_carloadings": "tb7q-kn5i",
            "rail_service_metrics": "axkm-yjzy",
        }
    )

    fbx_base_url: str = "https://api.freightos.com/fd_external_apis/price_stats"
    fbx_api_key: str = os.getenv("FREIGHTOS_FBX_API_KEY", "")

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls()

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
