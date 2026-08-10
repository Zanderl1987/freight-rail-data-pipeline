from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.models.schemas import (
    OceanFreightRate,
    OceanFreightRateBatch,
    RailCarloading,
    RailCarloadingBatch,
)
from freight_rail_pipeline.storage import StorageWriter


class TestStorageWriter:
    _test_dir = Path("tests/_test_storage")

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

    def test_write_carloadings_creates_parquet(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[
            RailCarloading(snapshot_date=date(2026, 7, 15), railroad="BNSF", commodity="Grain", carloads=1500),
            RailCarloading(snapshot_date=date(2026, 7, 15), railroad="UP", commodity="Coal", carloads=3200),
        ])

        count = writer.write_carloadings(batch, dt=date(2026, 7, 15))
        assert count == 2

        parquet_files = list(self._test_dir.rglob("*.parquet"))
        assert len(parquet_files) >= 1

        df = pd.read_parquet(parquet_files[0])
        assert len(df) == 2
        assert list(df["railroad"]) == ["BNSF", "UP"]

    def test_write_ocean_rates_creates_parquet_and_csv(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = OceanFreightRateBatch(records=[
            OceanFreightRate(
                snapshot_date=date(2026, 7, 28),
                route_code="FBX01",
                route_description="China → USWC",
                origin_port="CNSHA",
                destination_port="USLAX",
                trade_lane="Trans-Pacific",
                container_type="40GP",
                rate_usd=4500,
            ),
        ])

        count = writer.write_ocean_rates(batch, dt=date(2026, 7, 28))
        assert count == 1

        parquet_files = list(self._test_dir.rglob("ocean_freight_rates.parquet"))
        assert len(parquet_files) == 1

        df = pd.read_parquet(parquet_files[0])
        assert len(df) == 1
        assert df.iloc[0]["rate_usd"] == 4500

        csv_files = list(self._test_dir.rglob("ocean_freight_rates.csv"))
        assert len(csv_files) == 1

        df_csv = pd.read_csv(csv_files[0])
        assert len(df_csv) == 1

    def test_partition_path_format(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[
            RailCarloading(snapshot_date=date(2026, 7, 15), railroad="CSX", commodity="Chemicals", carloads=500),
        ])
        writer.write_carloadings(batch, dt=date(2026, 7, 15))

        expected_path = self._test_dir / "freight" / "rail_carloadings" / "year=2026" / "month=07" / "day=15"
        assert expected_path.exists()
        assert (expected_path / "rail_carloadings.parquet").exists()

    def test_write_empty_batch_does_nothing(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[])
        count = writer.write_carloadings(batch)
        assert count == 0
        assert len(list(self._test_dir.rglob("*.parquet"))) == 0

    def test_output_paths_tracked(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[
            RailCarloading(snapshot_date=date(2026, 7, 15), railroad="NS", commodity="Intermodal", carloads=800),
        ])
        writer.write_carloadings(batch)
        assert len(writer.list_written()) > 0

    def test_batch_partitions_per_record_date_not_first_record_date(self) -> None:
        # C1/R7: the batch used to be keyed entirely on records[0].snapshot_date,
        # so a multi-year history fetch landed every year under the first
        # record's date. Each record now writes to its own snapshot_date
        # partition. (This supersedes DECISION-002, which instead keyed the whole
        # batch on the ingestion date -- see the note in storage._write_table.)
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[
            RailCarloading(snapshot_date=date(2020, 1, 15), railroad="BNSF", commodity="Grain", carloads=1500),
            RailCarloading(snapshot_date=date(2021, 6, 1), railroad="UP", commodity="Coal", carloads=3200),
        ])
        writer.write_carloadings(batch, dt=date(2026, 7, 15))

        written = sorted(str(p) for p in self._test_dir.rglob("rail_carloadings.parquet"))
        assert len(written) == 2
        assert "year=2020" in written[0] and "month=01" in written[0]
        assert "year=2021" in written[1] and "month=06" in written[1]
        # dt must not override a record that carries its own snapshot_date
        assert not any("year=2026" in p for p in written)

    def test_unknown_table_raises(self) -> None:
        # I4: an unknown table used to write a 0-row parquet while logging
        # success -- now it fails loudly.
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = RailCarloadingBatch(records=[
            RailCarloading(snapshot_date=date(2026, 7, 15), railroad="BNSF", commodity="Grain", carloads=1500),
        ])
        with pytest.raises(ValueError, match="Unknown table"):
            writer._write_table("no_such_table", batch.records, dt=date(2026, 7, 15))
