from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.pipeline import FreightPipeline
from freight_rail_pipeline.sources.base import SourceResult


class TestFreightPipeline:
    _test_dir = Path("tests/_test_pipeline")

    @classmethod
    def setup_class(cls) -> None:
        cls._test_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def teardown_class(cls) -> None:
        if cls._test_dir.exists():
            shutil.rmtree(cls._test_dir)

    def setup_method(self) -> None:
        if self._test_dir.exists():
            shutil.rmtree(self._test_dir)
        self._test_dir.mkdir(parents=True, exist_ok=True)

    def make_config(self) -> PipelineConfig:
        return PipelineConfig(
            output_dir=str(self._test_dir / "data"),
            log_dir=str(self._test_dir / "logs"),
        )

    def test_pipeline_initialization(self) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)
        assert pipeline is not None
        assert "usda" in pipeline._sources
        assert "fbx" in pipeline._sources

    def test_list_sources(self) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)
        sources = pipeline.list_sources()
        assert "usda" in sources
        assert "fbx" in sources

    def test_validate_sources(self) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)
        results = pipeline.validate_sources()
        assert "usda" in results
        assert "fbx" in results

    @patch("freight_rail_pipeline.pipeline.src.USDAgTransportSource.fetch")
    @patch("freight_rail_pipeline.pipeline.src.FreightosFBXSource.fetch")
    def test_run_with_no_data(self, mock_fbx: object, mock_usda: object) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)

        from freight_rail_pipeline.models.schemas import RailCarloading

        def usda_side_effect(*args, **kwargs):
            return SourceResult(
                records=[
                    RailCarloading(
                        snapshot_date=__import__("datetime").date(2026, 7, 15),
                        railroad="BNSF",
                        commodity="Grain",
                        carloads=1000,
                    )
                ],
                source_name="usda_agtransport",
            )

        mock_usda.side_effect = usda_side_effect  # type: ignore[attr-defined]

        mock_fbx.side_effect = lambda *a, **kw: SourceResult(  # type: ignore[attr-defined]
            records=[], source_name="freightos_fbx"
        )

        result = pipeline.run(sources=["usda"])
        assert result.success is True
        assert result.total_records == 1
        assert "usda" in result.source_results

    @patch("freight_rail_pipeline.pipeline.src.USDAgTransportSource.fetch")
    @patch("freight_rail_pipeline.pipeline.src.FreightosFBXSource.fetch")
    def test_run_with_source_failure(self, mock_fbx: object, mock_usda: object) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)

        mock_usda.side_effect = RuntimeError("API unavailable")  # type: ignore[attr-defined]
        mock_fbx.side_effect = lambda *a, **kw: SourceResult(  # type: ignore[attr-defined]
            records=[], source_name="freightos_fbx"
        )

        result = pipeline.run(sources=["usda", "fbx"])
        assert result.success is False
        assert "usda" in result.failed_sources

    def test_pipeline_output_dir_created(self) -> None:
        config = self.make_config()
        pipeline = FreightPipeline(config)
        assert config.output_dir.exists()
        assert config.log_dir.exists()
