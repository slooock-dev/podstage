"""Live telemetry for the running session — game and resource load.

Everything here is readable as the plain user (the container is rootless):

  * CPU/RAM are the whole machine's (``/proc/stat`` and ``/proc/meminfo``),
    not the session's cgroup: the panel exists to answer whether this box
    still has room to encode and stream, and the desktop's own load counts.
    It is also the only reading that works on both backends.
  * GPU/NVENC come from ``nvidia-smi`` on NVIDIA, the amdgpu sysfs
    (``gpu_busy_percent`` + ``mem_info_vram_*``) on AMD, or one
    ``intel_gpu_top -J`` sample on Intel (needs a readable GPU PMU).
  * The active game from the running ``SteamLaunch AppId=`` process.
  * Game FPS comes from the in-container perf probe, which asks gamescope for
    the presented frametime of the focused app and drops the current rate into
    the tmpfs both sides share (``config.RUNTIME_SHARE_DIR``).
    Compositor-side, so it is the one performance number that reads the same on
    NVIDIA, AMD and Intel.

There is deliberately NO connected-client detection: sunshine's media path is
unconnected UDP (no socket peer to read), and every heuristic tried around
that (conntrack remnants, send-queue sampling, NVENC attribution) flickered —
complexity without real value. The NVENC session count in the GPU stats is
the honest "something is encoding" signal.
"""

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import provisioner, runtime

_APPID_RE = re.compile(r"SteamLaunch AppId=(\d+)")


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


# -- active game ------------------------------------------------------------

@dataclass
class ActiveGame:
    app_id: int
    name: str


def active_game() -> ActiveGame | None:
    """The Steam AppID currently launched in the sandbox (or None in the UI /
    Big Picture menu). Read from the running reaper's ``SteamLaunch AppId=``."""
    rc, out = _run(["pgrep", "-af", "SteamLaunch AppId="])
    if rc != 0:
        return None
    for line in out.splitlines():
        m = _APPID_RE.search(line)
        if not m:
            continue
        app_id = int(m.group(1))
        if app_id == 0:
            continue
        app = provisioner.find_app(app_id)
        name = provisioner._manifest_value(app.manifest, "name") if app else None
        return ActiveGame(app_id, name or str(app_id))
    return None


# -- GPU / encoder telemetry ------------------------------------------------

@dataclass
class GpuStats:
    name: str = ""
    util_pct: int | None = None
    mem_used_mb: int | None = None
    mem_total_mb: int | None = None
    encoder_sessions: int | None = None  # NVENC only; AMD exposes no counter


def gpu_stats() -> GpuStats | None:
    """GPU utilization + VRAM for the Load card, dispatched by GPU vendor.

    NVIDIA reads ``nvidia-smi`` (including the NVENC session count). AMD reads
    the amdgpu sysfs (``gpu_busy_percent`` + ``mem_info_vram_*``); the kernel
    exposes no per-encoder session count there, so ``encoder_sessions`` stays
    None on AMD. Intel (i915/xe) has no sysfs interface at all — the busy
    percentage comes from one ``intel_gpu_top`` sample where available."""
    vendor = runtime.gpu_vendor()
    if vendor == "amd":
        return _amd_gpu_stats()
    if vendor == "intel":
        return _intel_gpu_stats()
    return _nvidia_gpu_stats()


def _nvidia_gpu_stats() -> GpuStats | None:
    rc, out = _run([
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,encoder.stats.sessionCount",
        "--format=csv,noheader,nounits",
    ])
    if rc != 0 or not out:
        return None
    parts = [p.strip() for p in out.splitlines()[0].split(",")]

    def _int(i: int) -> int | None:
        try:
            return int(parts[i])
        except (ValueError, IndexError):
            return None

    return GpuStats(
        name=parts[0] if parts else "",
        util_pct=_int(1), mem_used_mb=_int(2), mem_total_mb=_int(3),
        encoder_sessions=_int(4),
    )


_CARD_RE = re.compile(r"^card\d+$")


def _sysfs_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _amd_card_dir() -> Path | None:
    """The amdgpu device dir (PCI vendor 0x1002) whose sysfs exposes
    ``gpu_busy_percent`` / ``mem_info_vram_*``. First AMD DRM card wins."""
    for card in sorted(Path("/sys/class/drm").glob("card*")):
        if not _CARD_RE.match(card.name):
            continue  # skip connector dirs like card0-DP-1
        dev = card / "device"
        try:
            if dev.joinpath("vendor").read_text().strip().lower() == "0x1002":
                return dev
        except OSError:
            continue
    return None


def _amd_gpu_stats() -> GpuStats | None:
    dev = _amd_card_dir()
    if dev is None:
        return None
    # gpu_busy_percent is unsupported on some parts (read errors); the VRAM
    # counters are near-universal. On an APU, mem_info_vram_* is the small
    # BIOS-reserved carve-out — GTT (system RAM) carries the rest. Report what
    # is readable; a single missing file must not blank the whole row.
    busy = _sysfs_int(dev / "gpu_busy_percent")     # 0..100
    used = _sysfs_int(dev / "mem_info_vram_used")   # bytes
    total = _sysfs_int(dev / "mem_info_vram_total")  # bytes
    if busy is None and used is None and total is None:
        return None
    return GpuStats(
        name="AMD GPU",
        util_pct=busy,
        mem_used_mb=used // (1 << 20) if used is not None else None,
        mem_total_mb=total // (1 << 20) if total is not None else None,
        encoder_sessions=None,
    )


def _parse_intel_gpu_top(out: str) -> GpuStats | None:
    """Last complete JSON object from the ``-J`` stream (the first sample is
    often zero). Busy % = Render/3D engine; no VRAM counters on i915/xe."""
    samples = []
    depth, start = 0, None
    for i, ch in enumerate(out):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    samples.append(json.loads(out[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    for data in reversed(samples):
        engines = data.get("engines") or {}
        for name, vals in engines.items():
            if not name.lower().startswith("render"):
                continue
            try:
                busy = round(float(vals.get("busy")))
            except (TypeError, ValueError):
                continue
            return GpuStats(name="Intel GPU", util_pct=busy)
    return None


def _intel_gpu_stats() -> GpuStats | None:
    """One short ``intel_gpu_top -J`` sample; needs CAP_PERFMON or a relaxed
    perf_event_paranoid, else None (no GPU load shown)."""
    if shutil.which("intel_gpu_top") is None:
        return None
    try:
        p = subprocess.run(["intel_gpu_top", "-J", "-s", "300"],
                           capture_output=True, text=True, timeout=1.2,
                           check=False)
        out = p.stdout or ""
    except subprocess.TimeoutExpired as e:
        # -J streams until killed; the timeout IS the normal exit path.
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_intel_gpu_top(out)


# -- host CPU / RAM ---------------------------------------------------------
#
# Whole machine, not the session's cgroup. Two reasons. It answers the question
# the panel is there for, namely whether this box still has room to encode and
# stream, and the desktop's own load counts towards that. And it needs nothing
# from the container, so it works on both backends: locating the cgroup means
# finding the session compositor, and moonshine runs none.

def _proc_stat_cpu() -> tuple[int, int] | None:
    """``(busy, total)`` jiffies from the aggregate ``cpu`` line."""
    try:
        first = Path("/proc/stat").read_text().split("\n", 1)[0].split()
    except OSError:
        return None
    if not first or first[0] != "cpu":
        return None
    try:
        fields = [int(f) for f in first[1:]]
    except ValueError:
        return None
    if len(fields) < 4:
        return None
    total = sum(fields)
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return total - idle, total


def _meminfo_mb() -> tuple[int | None, int | None]:
    """``(used_mb, total_mb)``. Used is total minus MemAvailable, which is what
    a user means by "in use": it counts reclaimable cache as free."""
    want = {"MemTotal:": 0, "MemAvailable:": 0}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key = line.split(maxsplit=1)[0]
            if key in want:
                want[key] = int(line.split()[1])  # kB
    except (OSError, ValueError, IndexError):
        return None, None
    total_kb, avail_kb = want["MemTotal:"], want["MemAvailable:"]
    if not total_kb:
        return None, None
    return (total_kb - avail_kb) >> 10, total_kb >> 10


@dataclass
class HostStats:
    cpu_pct: float | None = None      # 0..100 across all cores
    mem_used_mb: int | None = None
    mem_total_mb: int | None = None


def host_stats(sample_interval: float = 0.4) -> HostStats:
    """CPU% over ``sample_interval`` and RAM of the whole machine. Blocks for
    ``sample_interval`` to take two CPU samples, so call it off the UI thread."""
    used_mb, total_mb = _meminfo_mb()
    first = _proc_stat_cpu()
    if first is None:
        return HostStats(None, used_mb, total_mb)
    time.sleep(sample_interval)
    second = _proc_stat_cpu()
    cpu_pct = None
    if second is not None:
        d_busy, d_total = second[0] - first[0], second[1] - first[1]
        if d_total > 0:
            cpu_pct = round(max(0.0, min(100.0, d_busy * 100 / d_total)), 1)
    return HostStats(cpu_pct, used_mb, total_mb)


# -- game FPS from the in-container perf probe ------------------------------

# The probe rewrites this once per interval (default 1s) in the host tmpfs both
# sides share; a few missed intervals mean the probe or the session is gone, so
# stop trusting the numbers.
PERF_FILE = config.RUNTIME_SHARE_DIR / "perf.json"
PERF_MAX_AGE_S = 6.0


@dataclass
class GamePerf:
    """One perf-probe window. ``samples == 0`` is a real answer: the probe is
    alive and nothing presented a frame (paused game, static menu)."""

    app_id: int | None = None
    samples: int = 0
    fps: float | None = None


def game_perf(path: Path = PERF_FILE) -> GamePerf | None:
    """The probe's latest sample window, or None when there is nothing to
    trust: probe disabled (experimental feature off), a gamescope without the
    perf query, or a file older than ``PERF_MAX_AGE_S``."""
    try:
        stat = path.stat()
        if time.time() - stat.st_mtime > PERF_MAX_AGE_S:
            return None
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    app_id = data.get("app_id")
    samples = data.get("samples")
    fps = data.get("fps")
    return GamePerf(
        app_id=app_id if isinstance(app_id, int) and app_id > 0 else None,
        samples=samples if isinstance(samples, int) and samples > 0 else 0,
        fps=float(fps) if isinstance(fps, (int, float)) and fps > 0 else None,
    )


# -- one-shot snapshot for the GUI -----------------------------------------

@dataclass
class Snapshot:
    running: bool
    client_profile: str | None = None  # which podstage profile owns it
    detail: str = ""
    backend: str = ""  # streaming backend of the running session
    game: ActiveGame | None = None
    gpu: GpuStats | None = None
    host: HostStats | None = None
    perf: GamePerf | None = None


def snapshot() -> Snapshot:
    """Full status for one GUI refresh. Blocks ~0.4s (CPU sampling)."""
    st = runtime.status()
    if not st.running:
        return Snapshot(False, detail=st.detail)
    return Snapshot(
        running=True,
        client_profile=st.client,
        detail=st.detail,
        backend=st.backend,
        game=active_game(),
        gpu=gpu_stats(),
        host=host_stats(),
        perf=game_perf(),
    )
