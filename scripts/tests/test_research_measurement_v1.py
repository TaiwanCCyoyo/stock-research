"""Phase differences preserve the meaning of process lifetime/native counters."""

from research_core.research_measurement_v1 import phase_receipt, resource_sample


def test_phase_reports_wall_cpu_and_logical_transfer_differences() -> None:
    before = {
        "wall": 10.0,
        "cpu": 3.0,
        "native": {
            "working_set_bytes": 100,
            "peak_working_set_lifetime_bytes": 900,
            "io": {"ReadTransferCount": 50, "WriteTransferCount": 70, "ReadOperationCount": 2},
        },
    }
    after = {
        "wall": 12.5,
        "cpu": 3.75,
        "native": {
            "working_set_bytes": 120,
            "peak_working_set_lifetime_bytes": 950,
            "io": {"ReadTransferCount": 80, "WriteTransferCount": 77, "ReadOperationCount": 5},
        },
    }
    receipt = phase_receipt("invented", before, after)
    assert receipt["phase"] == "invented"
    assert receipt["wall_seconds"] == 2.5
    assert receipt["cpu_seconds"] == 0.75
    native = receipt["native"]
    assert native["working_set_after_bytes"] == 120
    assert native["peak_working_set_process_lifetime_bytes"] == 950
    assert native["io_delta"] == {"ReadTransferCount": 30, "WriteTransferCount": 7, "ReadOperationCount": 3}
    assert "lifetime peak" in native["memory_scope"]
    assert "not an isolated phase peak" in native["memory_scope"]
    assert "transfer counters" in native["io_scope"] and "cached I/O" in native["io_scope"]
    assert "not physical disk throughput" in native["io_scope"]


def test_missing_native_sample_preserves_portable_differences() -> None:
    before = {"wall": 1.0, "cpu": 0.25, "native": None}
    after = {"wall": 2.0, "cpu": 0.5, "native": None}
    assert phase_receipt("portable", before, after) == {"phase": "portable", "wall_seconds": 1.0, "cpu_seconds": 0.25, "native": None}


def test_live_samples_report_nonnegative_elapsed_counters() -> None:
    before, after = resource_sample(), resource_sample()
    receipt = phase_receipt("sample", before, after)
    assert receipt["wall_seconds"] >= 0
    assert receipt["cpu_seconds"] >= 0
    if receipt["native"] is not None:
        assert receipt["native"]["peak_working_set_process_lifetime_bytes"] >= receipt["native"]["working_set_after_bytes"] >= 0
        assert all(value >= 0 for value in receipt["native"]["io_delta"].values())
