"""Tests for the telemetry parsers (no hardware, no subprocesses)."""

import json
import os
import time

from podstage.core import monitor

# intel_gpu_top -J streams an array of period samples; the first one right
# after startup is typically all zeros.
_IGT_STREAM = """[
{
  "period": {"duration": 300.1, "unit": "ms"},
  "engines": {
    "Render/3D/0": {"busy": 0.0, "sema": 0.0, "wait": 0.0, "unit": "%"},
    "Video/0": {"busy": 0.0, "sema": 0.0, "wait": 0.0, "unit": "%"}
  }
},
{
  "period": {"duration": 300.0, "unit": "ms"},
  "engines": {
    "Render/3D/0": {"busy": 42.6, "sema": 0.0, "wait": 0.0, "unit": "%"},
    "Video/0": {"busy": 12.0, "sema": 0.0, "wait": 0.0, "unit": "%"}
  }
}
"""


def test_parse_intel_gpu_top_uses_last_sample():
    stats = monitor._parse_intel_gpu_top(_IGT_STREAM)
    assert stats is not None
    assert stats.util_pct == 43  # 42.6 rounded, from the LAST sample
    assert stats.name == "Intel GPU"
    assert stats.mem_used_mb is None  # i915/xe expose no VRAM counters
    assert stats.encoder_sessions is None


def test_parse_intel_gpu_top_tolerates_truncated_tail():
    # The sampling timeout usually kills the tool mid-object; the trailing
    # fragment must be ignored, not crash the parser.
    truncated = _IGT_STREAM + ',\n{\n  "period": {"duration": 3'
    stats = monitor._parse_intel_gpu_top(truncated)
    assert stats is not None and stats.util_pct == 43


def test_parse_intel_gpu_top_empty_or_garbage():
    assert monitor._parse_intel_gpu_top("") is None
    assert monitor._parse_intel_gpu_top("intel_gpu_top: PMU failed") is None
    assert monitor._parse_intel_gpu_top('{"engines": {}}') is None


# -- game perf (the in-container probe's JSON in the shared tmpfs) ----------

def _write_perf(tmp_path, payload: str, age_s: float = 0.0):
    path = tmp_path / "perf.json"
    path.write_text(payload)
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


def test_game_perf_reads_probe_sample(tmp_path):
    _write_perf(tmp_path, json.dumps({
        "schema": 1, "source": "gamescope_control", "ts": 1, "app_id": 620,
        "samples": 59, "fps": 59.4}))
    perf = monitor.game_perf(tmp_path / "perf.json")
    assert perf is not None
    assert perf.app_id == 620 and perf.samples == 59 and perf.fps == 59.4


def test_game_perf_idle_window_is_not_an_error(tmp_path):
    # Probe alive, nothing presented: a real answer, distinct from "no probe".
    _write_perf(tmp_path, json.dumps({"schema": 1, "app_id": 769, "samples": 0}))
    perf = monitor.game_perf(tmp_path / "perf.json")
    assert perf is not None
    assert perf.samples == 0 and perf.fps is None and perf.app_id == 769


def test_game_perf_stale_file_is_dropped(tmp_path):
    _write_perf(tmp_path, json.dumps({"samples": 60, "fps": 60.0}),
                age_s=monitor.PERF_MAX_AGE_S + 5)
    assert monitor.game_perf(tmp_path / "perf.json") is None


def test_game_perf_missing_or_garbage(tmp_path):
    assert monitor.game_perf(tmp_path / "perf.json") is None  # probe never ran
    _write_perf(tmp_path, '{"samples": 12, "fps":')  # caught mid-write
    assert monitor.game_perf(tmp_path / "perf.json") is None
    _write_perf(tmp_path, "[1, 2, 3]")  # valid JSON, wrong shape
    assert monitor.game_perf(tmp_path / "perf.json") is None


def test_game_perf_ignores_nonsense_values(tmp_path):
    _write_perf(tmp_path, json.dumps({"app_id": 0, "samples": 3, "fps": 0}))
    perf = monitor.game_perf(tmp_path / "perf.json")
    assert perf is not None
    assert perf.app_id is None and perf.fps is None
