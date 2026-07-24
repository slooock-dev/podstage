"""Live telemetry for the running session — game and resource load.

Everything here is readable as the plain user (the container is rootless):

  * CPU/RAM come from the container's cgroup v2 files (``cpu.stat`` /
    ``memory.current``), located via the world-readable cmdline of the cage
    process.
  * GPU/NVENC come from ``nvidia-smi`` on NVIDIA, or the amdgpu sysfs
    (``gpu_busy_percent`` + ``mem_info_vram_*``) on AMD — both unprivileged.
  * The active game from the running ``SteamLaunch AppId=`` process.

There is deliberately NO connected-client detection: Sunshine's media path is
unconnected UDP (no socket peer to read), and every heuristic tried around
that (conntrack remnants, send-queue sampling, NVENC attribution) flickered —
complexity without real value. The NVENC session count in the GPU stats is
the honest "something is encoding" signal.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import provisioner, runtime

_APPID_RE = re.compile(r"SteamLaunch AppId=(\d+)")


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
    None on AMD. Intel (i915/xe) has no comparable sysfs interface
    (``intel_gpu_top`` needs perf privileges), so no stats there."""
    vendor = runtime.gpu_vendor()
    if vendor == "amd":
        return _amd_gpu_stats()
    if vendor == "intel":
        return None
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


# -- container CPU / RAM via cgroup v2 --------------------------------------

def _cage_pid() -> int | None:
    rc, out = _run(["pgrep", "-af", "cage -d"])
    if rc != 0:
        return None
    for line in out.splitlines():
        pid_str = line.split(maxsplit=1)[0]
        if pid_str.isdigit():
            return int(pid_str)
    return None


def _cgroup_dir(pid: int) -> Path | None:
    """The cgroup v2 directory for a PID (the whole container shares it)."""
    try:
        for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
            # cgroup v2 line: "0::/machine.slice/libpod-<id>.scope/container"
            if line.startswith("0::"):
                rel = line.split("::", 1)[1].lstrip("/")
                # Resource accounting sits on the parent scope, not the leaf.
                base = Path("/sys/fs/cgroup") / rel
                for cand in (base, base.parent):
                    if (cand / "cpu.stat").exists():
                        return cand
    except OSError:
        return None
    return None


def _read_cpu_usec(cgroup: Path) -> int | None:
    try:
        for line in (cgroup / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def _read_mem_bytes(cgroup: Path) -> int | None:
    try:
        return int((cgroup / "memory.current").read_text().strip())
    except (OSError, ValueError):
        return None


@dataclass
class ContainerStats:
    cpu_pct: float | None = None
    mem_used_mb: int | None = None


def container_stats(sample_interval: float = 0.4) -> ContainerStats | None:
    """CPU% (over ``sample_interval``) and RAM of the whole container cgroup.
    Blocks for ``sample_interval`` to take two CPU samples — call off the UI
    thread. Returns None if the container isn't running."""
    pid = _cage_pid()
    if pid is None:
        return None
    cgroup = _cgroup_dir(pid)
    if cgroup is None:
        return None
    mem = _read_mem_bytes(cgroup)
    cpu1 = _read_cpu_usec(cgroup)
    if cpu1 is None:
        return ContainerStats(None, mem // (1 << 20) if mem else None)
    t1 = time.monotonic()
    time.sleep(sample_interval)
    cpu2 = _read_cpu_usec(cgroup)
    dt = time.monotonic() - t1
    cpu_pct = None
    if cpu2 is not None and dt > 0:
        cpu_pct = round((cpu2 - cpu1) / (dt * 1e6) * 100, 1)  # 100% = one core
    return ContainerStats(cpu_pct, mem // (1 << 20) if mem else None)


# -- one-shot snapshot for the GUI -----------------------------------------

@dataclass
class Snapshot:
    running: bool
    client_profile: str | None = None  # which podstage profile owns it
    detail: str = ""
    game: ActiveGame | None = None
    gpu: GpuStats | None = None
    container: ContainerStats | None = None


def snapshot() -> Snapshot:
    """Full status for one GUI refresh. Blocks ~0.4s (CPU sampling)."""
    st = runtime.status()
    if not st.running:
        return Snapshot(False, detail=st.detail)
    return Snapshot(
        running=True,
        client_profile=st.client,
        detail=st.detail,
        game=active_game(),
        gpu=gpu_stats(),
        container=container_stats(),
    )
