from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.models.schemas import (
    FMCContainerStats,
    FMCContainerStatsBatch,
    GrainTransportObservation,
    GrainTransportObservationBatch,
    OceanFreightRate,
    OceanFreightRateBatch,
    RailCarloading,
    RailCarloadingBatch,
    TransBorderLegacy,
    TransBorderLegacyBatch,
    WaybillShipment,
    WaybillShipmentBatch,
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

        batch = RailCarloadingBatch(
            records=[
                RailCarloading(
                    snapshot_date=date(2026, 7, 15),
                    railroad="BNSF",
                    commodity="Grain",
                    carloads=1500,
                ),
                RailCarloading(
                    snapshot_date=date(2026, 7, 15), railroad="UP", commodity="Coal", carloads=3200
                ),
            ]
        )

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

        batch = OceanFreightRateBatch(
            records=[
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
            ]
        )

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

        batch = RailCarloadingBatch(
            records=[
                RailCarloading(
                    snapshot_date=date(2026, 7, 15),
                    railroad="CSX",
                    commodity="Chemicals",
                    carloads=500,
                ),
            ]
        )
        writer.write_carloadings(batch, dt=date(2026, 7, 15))

        expected_path = (
            self._test_dir / "freight" / "rail_carloadings" / "year=2026" / "month=07" / "day=15"
        )
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

        batch = RailCarloadingBatch(
            records=[
                RailCarloading(
                    snapshot_date=date(2026, 7, 15),
                    railroad="NS",
                    commodity="Intermodal",
                    carloads=800,
                ),
            ]
        )
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

        batch = RailCarloadingBatch(
            records=[
                RailCarloading(
                    snapshot_date=date(2020, 1, 15),
                    railroad="BNSF",
                    commodity="Grain",
                    carloads=1500,
                ),
                RailCarloading(
                    snapshot_date=date(2021, 6, 1), railroad="UP", commodity="Coal", carloads=3200
                ),
            ]
        )
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

        batch = RailCarloadingBatch(
            records=[
                RailCarloading(
                    snapshot_date=date(2026, 7, 15),
                    railroad="BNSF",
                    commodity="Grain",
                    carloads=1500,
                ),
            ]
        )
        with pytest.raises(ValueError, match="Unknown table"):
            writer._write_table("no_such_table", batch.records, dt=date(2026, 7, 15))

    def test_year_partition_merges_snapshots_in_same_year(self) -> None:
        # STB waybill regression: snapshots carry per-shipment waybill dates, so
        # many groups collapse into one year= partition. The writer used to emit
        # each group to the same year=YYYY/<table>.parquet, so every write
        # overwrote the previous one and only the last group survived (2.77k of
        # 2.17M rows made it to disk). Now all snapshots in a year merge into a
        # single file.
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        def waybill(dt: date, stcc: str) -> WaybillShipment:
            return WaybillShipment(
                snapshot_date=dt,
                accounting_period="03/24",
                carloads=1,
                stcc=stcc,
            )

        batch = WaybillShipmentBatch(
            records=[
                waybill(date(2024, 1, 10), "01121"),
                waybill(date(2024, 5, 20), "01411"),
                waybill(date(2024, 12, 5), "01122"),
            ]
        )
        count = writer.write_waybills(batch, dt=date(2026, 7, 15))
        assert count == 3

        files = list(self._test_dir.rglob("waybill_shipments.parquet"))
        assert len(files) == 1, "one merged file per year partition"
        assert "year=2024" in str(files[0])
        df = pd.read_parquet(files[0])
        assert len(df) == 3
        assert sorted(df["stcc"]) == ["01121", "01122", "01411"]
        # no CSV fallback for the annual table
        assert not list(self._test_dir.rglob("waybill_shipments.csv"))

    def test_legacy_transborder_skips_the_csv_fallback(self) -> None:
        # The 1993-2006 DBF backfill writes 168 month partitions, each one
        # re-serializing the full JSON raw_record column. An uncompressed CSV
        # twin per month roughly doubles the store for no query benefit --
        # same reasoning as write_waybills.
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        batch = TransBorderLegacyBatch(
            records=[
                TransBorderLegacy(
                    snapshot_date=date(1995, 1, 31),
                    year=1995,
                    month=1,
                    direction="export",
                    partner="MX",
                    emphasis="commodity",
                    source_table="d3a",
                    source_file="D3AJAN95.DBF",
                    statmoyr="0195",
                    raw_record={"DISAGMOT": "6", "VALUE": "24077"},
                )
            ]
        )
        assert writer.write_transborder_legacy(batch) == 1

        parquets = list(self._test_dir.rglob("transborder_legacy_1993_2006.parquet"))
        assert len(parquets) == 1
        assert not list(self._test_dir.rglob("transborder_legacy_1993_2006.csv"))

    def test_year_partition_merges_across_runs(self) -> None:
        # Cross-run variant of the waybill merge: a backfill run writes records
        # for years that already exist on disk (each STB sample year overlaps
        # prior waybill years). The writer must merge with the existing file,
        # not overwrite it, or backfilling silently deletes earlier samples'
        # rows.
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        def waybill(dt: date, stcc: str) -> WaybillShipment:
            return WaybillShipment(
                snapshot_date=dt,
                accounting_period="03/24",
                carloads=1,
                stcc=stcc,
            )

        first = WaybillShipmentBatch(
            records=[
                waybill(date(2024, 1, 10), "01121"),
                waybill(date(2024, 5, 20), "01411"),
            ]
        )
        assert writer.write_waybills(first, dt=date(2026, 7, 15)) == 2

        # Second "run" (a different sample year's backfill) also has 2024 rows.
        second = WaybillShipmentBatch(
            records=[
                waybill(date(2024, 3, 15), "01122"),
                waybill(date(2024, 12, 5), "01221"),
            ]
        )
        assert writer.write_waybills(second, dt=date(2026, 7, 16)) == 2

        files = list(self._test_dir.rglob("waybill_shipments.parquet"))
        assert len(files) == 1, "one merged file per year partition"
        df = pd.read_parquet(files[0])
        assert len(df) == 4, "second run merged into the existing file, not replaced it"
        assert sorted(df["stcc"]) == ["01121", "01122", "01221", "01411"]

    def test_year_partition_merge_dedups_duplicate_records(self) -> None:
        # A record re-fetched across runs (same identity, newer ingested_at)
        # must not double-count after the merge.
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)

        def waybill(dt: date, stcc: str) -> WaybillShipment:
            return WaybillShipment(
                snapshot_date=dt,
                accounting_period="03/24",
                carloads=1,
                stcc=stcc,
            )

        first = WaybillShipmentBatch(records=[waybill(date(2024, 4, 10), "01121")])
        assert writer.write_waybills(first, dt=date(2026, 7, 15)) == 1

        # Same record re-fetched with a newer ingest timestamp.
        dup = WaybillShipmentBatch(records=[waybill(date(2024, 4, 10), "01121")])
        assert writer.write_waybills(dup, dt=date(2026, 7, 16)) == 1

        df = pd.read_parquet(list(self._test_dir.rglob("waybill_shipments.parquet"))[0])
        assert len(df) == 1, "re-fetched record deduped to a single row"

    def test_write_grain_transport_creates_parquet_and_csv(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)
        batch = GrainTransportObservationBatch(
            records=[
                GrainTransportObservation(
                    snapshot_date=date(2026, 8, 18),
                    series="mississippi_barge_rates",
                    resource_id="7spn-fbua",
                    metric="barge_rate_per_ton",
                    location="La Crosse - Minneapolis",
                    value=47.3535,
                    units="$ per ton",
                ),
                GrainTransportObservation(
                    snapshot_date=date(2026, 7, 1),
                    series="vessel_rates",
                    resource_id="ehs5-yac3",
                    metric="ocean_vessel_rate",
                    location="Gulf to Japan",
                    value=68.95,
                    units="$ per metric ton",
                ),
            ]
        )
        written = writer.write_grain_transport(batch, dt=date(2026, 8, 25))
        assert written == 2

        files = list(self._test_dir.rglob("grain_transport.parquet"))
        assert len(files) == 2, "one day partition per distinct snapshot_date"
        barge_file = next(
            f
            for f in files
            if f.parts[-4] == "year=2026"
            and f.parent.name == "day=18"
        )
        df = pd.read_parquet(barge_file)
        assert len(df) == 1
        assert df["series"].iloc[0] == "mississippi_barge_rates"
        assert list(self._test_dir.rglob("grain_transport.csv")), "CSV fallback written"

    def test_write_grain_transport_empty_batch_does_nothing(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)
        assert writer.write_grain_transport(GrainTransportObservationBatch(records=[])) == 0
        assert not list(self._test_dir.rglob("grain_transport.parquet"))

    def test_write_fmc_containerized_creates_parquet_and_csv(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)
        batch = FMCContainerStatsBatch(
            records=[
                FMCContainerStats(
                    snapshot_date=date(2024, 3, 31),
                    quarter_label="Q1 2024",
                    year=2024,
                    quarter=1,
                    entity_type="port",
                    entity_name="Anchorage, Alaska",
                    laden_export_teu=3548,
                    empty_export_teu=132,
                    laden_import_teu=12,
                    empty_import_teu=5928,
                    export_tonnage=49266.0,
                    import_tonnage=5963.0,
                ),
                FMCContainerStats(
                    snapshot_date=date(2024, 6, 30),
                    quarter_label="Q2 2024",
                    year=2024,
                    quarter=2,
                    entity_type="carrier",
                    entity_name="CMACGM",
                    laden_export_teu=456525,
                ),
            ]
        )
        written = writer.write_fmc_containerized(batch, dt=date(2026, 8, 25))
        assert written == 2

        files = list(self._test_dir.rglob("fmc_containerized.parquet"))
        assert len(files) == 2, "one day partition per quarter-end snapshot_date"
        df = pd.read_parquet(files[0])
        assert df["entity_type"].iloc[0] in ("port", "carrier")
        assert list(self._test_dir.rglob("fmc_containerized.csv")), "CSV fallback written"

    def test_write_fmc_containerized_empty_batch_does_nothing(self) -> None:
        config = PipelineConfig(output_dir=str(self._test_dir))
        writer = StorageWriter(config)
        assert writer.write_fmc_containerized(FMCContainerStatsBatch(records=[])) == 0
        assert not list(self._test_dir.rglob("fmc_containerized.parquet"))
