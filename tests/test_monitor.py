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


# -- host CPU / RAM ---------------------------------------------------------
#
# Whole machine on purpose: the session's own cgroup used to be located
# through the labwc command line, which the moonshine backend never runs, so
# both meters simply stayed empty there.

_STAT = ("cpu  100 20 30 400 50 0 0 0 0 0\n"
         "cpu0 50 10 15 200 25 0 0 0 0 0\n"
         "intr 1234\n")

_MEMINFO = ("MemTotal:       32432124 kB\n"
            "MemFree:         1000000 kB\n"
            "MemAvailable:   17000000 kB\n"
            "Buffers:          123456 kB\n")


def _patch_proc(monkeypatch, stat: str, meminfo: str):
    real = monitor.Path

    class _P(type(real("/"))):
        def read_text(self, *a, **kw):
            if str(self) == "/proc/stat":
                return stat
            if str(self) == "/proc/meminfo":
                return meminfo
            return real(str(self)).read_text(*a, **kw)

    monkeypatch.setattr(monitor, "Path", _P)


def test_proc_stat_cpu_counts_iowait_as_idle(monkeypatch):
    """iowait is not the CPU doing work; counting it busy would show a machine
    waiting on disk as saturated. Only the aggregate ``cpu`` line counts, the
    per-core lines below it would double everything."""
    _patch_proc(monkeypatch, _STAT, _MEMINFO)
    total = 100 + 20 + 30 + 400 + 50
    assert monitor._proc_stat_cpu() == (100 + 20 + 30, total)


def test_proc_stat_cpu_rejects_a_garbage_first_line(monkeypatch):
    _patch_proc(monkeypatch, "not a cpu line\n", _MEMINFO)
    assert monitor._proc_stat_cpu() is None


def test_meminfo_used_excludes_reclaimable_cache(monkeypatch):
    """"In use" means MemTotal - MemAvailable: page cache is reclaimable and
    counting it as used would show every idle machine as nearly full."""
    _patch_proc(monkeypatch, _STAT, _MEMINFO)
    used, total = monitor._meminfo_mb()
    assert total == 32432124 >> 10
    assert used == (32432124 - 17000000) >> 10


def test_host_stats_survives_unreadable_proc(monkeypatch):
    """A missing reading must blank one meter, not raise into the poll thread."""
    monkeypatch.setattr(monitor, "_proc_stat_cpu", lambda: None)
    monkeypatch.setattr(monitor, "_meminfo_mb", lambda: (None, None))
    stats = monitor.host_stats(sample_interval=0)
    assert (stats.cpu_pct, stats.mem_used_mb, stats.mem_total_mb) == (None, None, None)


def test_host_stats_cpu_percentage_over_the_interval(monkeypatch):
    """Two samples, busy grew by 50 of 100 total jiffies."""
    samples = iter([(100, 1000), (150, 1100)])
    monkeypatch.setattr(monitor, "_proc_stat_cpu", lambda: next(samples))
    monkeypatch.setattr(monitor, "_meminfo_mb", lambda: (8, 16))
    stats = monitor.host_stats(sample_interval=0)
    assert stats.cpu_pct == 50.0
    assert (stats.mem_used_mb, stats.mem_total_mb) == (8, 16)
