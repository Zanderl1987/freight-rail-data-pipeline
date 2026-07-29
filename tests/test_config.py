from __future__ import annotations

from pathlib import Path

from freight_rail_pipeline.config import PipelineConfig


class TestPipelineConfig:
    def test_default_config(self) -> None:
        config = PipelineConfig()
        assert config.output_dir == Path("data")
        assert config.log_level == "INFO"
        assert config.max_retries == 3
        assert config.request_timeout_seconds == 30
        assert config.output_format == "parquet"
        assert "rail_carloadings" in config.usda_socrata_resource_ids

    def test_from_env(self) -> None:
        config = PipelineConfig.from_env()
        assert config is not None

    def test_ensure_dirs_creates_directories(self, tmp_path: Path) -> None:
        config = PipelineConfig(
            output_dir=str(tmp_path / "output"),
            log_dir=str(tmp_path / "logs"),
        )
        config.ensure_dirs()
        assert (tmp_path / "output").exists()
        assert (tmp_path / "logs").exists()

    def test_custom_values(self) -> None:
        config = PipelineConfig(
            output_dir="/custom/path",
            log_level="DEBUG",
            max_retries=5,
            request_timeout_seconds=60,
        )
        assert config.output_dir == Path("/custom/path")
        assert config.log_level == "DEBUG"
        assert config.max_retries == 5
        assert config.request_timeout_seconds == 60
