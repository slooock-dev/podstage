"""Tests for the telemetry parsers (no hardware, no subprocesses)."""

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
