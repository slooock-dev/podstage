"""Streaming backends: what actually differs between Sunshine and moonshine.

podstage streams a sandboxed Steam Big Picture to a Moonlight client. *How*
that picture is composited, captured and encoded is the backend's job, and
there are two:

``sunshine``
    The original chain: labwc (headless) → gamescope (nested) → Steam, with
    Sunshine capturing labwc through wlr-screencopy and encoding via
    NVENC/VAAPI. Runs on every GPU podstage supports, and is the only path
    with a live config API (Sunshine's web UI).

``moonshine``
    `moonshine <https://github.com/hgaiser/moonshine>`_ is a GameStream server
    that brings its *own* headless compositor (smithay) and encodes with
    Vulkan Video. It replaces compositor, capture and server in one process,
    so labwc, the seat-shim, the keeper and the host-side mDNS publisher all
    fall away. In exchange it needs a GPU with a Vulkan video-encode queue
    (NVIDIA RTX, AMD RDNA2+, Intel Arc). Every older GPU that streams fine
    through Sunshine's VAAPI path cannot use this backend at all.

Everything backend-specific is a field here; ``core/runtime.py`` reads them
and stays the single source of truth for the ``podman run`` invocation. The
per-profile choice lives in ``config.SessionConfig.backend``.
"""

from dataclasses import dataclass

DEFAULT = "sunshine"

# Moonlight derives its whole port block from one base port with fixed
# offsets, so shifting the base moves every port with it and a client still
# reaches the set by entering "IP:<base>". Both backends use these offsets,
# they are Moonlight's, not the server's.
PORT_OFFSETS: dict[str, int] = {
    "https": -5,     # 47984
    "http": 0,       # 47989  (the base port Moonlight is pointed at)
    "video": 9,      # 47998/udp
    "control": 10,   # 47999/udp
    "audio": 11,     # 48000/udp
    "rtsp": 21,      # 48010
}


def ports(base: int) -> dict[str, int]:
    """The Moonlight port block for a base port."""
    return {name: base + off for name, off in PORT_OFFSETS.items()}


@dataclass(frozen=True)
class Backend:
    """One streaming backend and the handful of host-side decisions it drives.

    name          key in the config and on the CLI
    label         human-facing name (GUI/CLI output)
    image         podman image tag
    src_subdir    repo-relative image sources, hashed into the image label so
                  doctor and session start can flag a forgotten rebuild
    derives_from  image this one is built FROM, so a build can bring the base
                  up first; None for a self-contained image
    port_env      container env var carrying the Moonlight base port
    web_port_off  offset of a management web UI from the base port; None for
                  a backend without one
    host_mdns     needs runtime.start_publisher (the host's avahi) to be
                  discoverable. moonshine answers mDNS itself
    live_config   has an API that applies config changes to a running session
    full_dev      needs the host /dev bound wholesale (inputtino creates its
                  gamepads through /dev/uhid and Steam Input needs the
                  /dev/hidraw* node appearing with them, which cannot be
                  pre-mounted)
    vulkan_video  requires a Vulkan video-encode queue on the GPU
    summary       one line for `podstage session list` / the GUI
    """

    name: str
    label: str
    image: str
    src_subdir: str
    derives_from: str | None
    port_env: str
    web_port_off: int | None
    host_mdns: bool
    live_config: bool
    full_dev: bool
    vulkan_video: bool
    summary: str

    def web_port(self, base: int) -> int | None:
        return None if self.web_port_off is None else base + self.web_port_off


SUNSHINE = Backend(
    name="sunshine",
    label="Sunshine",
    image="podstage-runtime:latest",
    src_subdir="containers/runtime",
    derives_from=None,
    port_env="PS_SUNSHINE_PORT",
    web_port_off=1,          # Sunshine's web UI, 47990 by default
    host_mdns=True,          # no avahi in the container
    live_config=True,        # POST /api/config + /api/restart
    full_dev=False,          # /dev/uinput + /dev/input suffice
    vulkan_video=False,
    summary="labwc + gamescope + Sunshine (NVENC/VAAPI), works on every supported GPU",
)

MOONSHINE = Backend(
    name="moonshine",
    label="moonshine",
    image="podstage-moonshine:latest",
    src_subdir="containers/moonshine",
    # Built FROM the runtime image: same base, same CDI GPU injection, same
    # rootless user, and Steam/gamescope/the focus-nudge binary come along.
    derives_from=SUNSHINE.image,
    port_env="PS_MOONSHINE_PORT",
    web_port_off=None,       # config.toml on disk, no management UI
    host_mdns=False,         # built-in mDNS responder (--network host)
    live_config=False,       # config changes need a session restart
    full_dev=True,           # inputtino: /dev/uhid + the hidraw node
    vulkan_video=True,
    summary="moonshine's own compositor + Vulkan Video, needs NVIDIA RTX, AMD RDNA2+ or Intel Arc",
)

BACKENDS: dict[str, Backend] = {b.name: b for b in (SUNSHINE, MOONSHINE)}


def names() -> list[str]:
    return list(BACKENDS)


def get(name: str = "") -> Backend:
    """Look a backend up by name; empty falls back to the default.

    Raises ValueError for an unknown name. Callers that must not fail on a
    config written by a newer podstage should use :func:`get_or_default`.
    """
    if not name:
        return BACKENDS[DEFAULT]
    try:
        return BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"unknown streaming backend {name!r}, use one of: "
            + ", ".join(names())
        ) from None


def base_of(spec: Backend) -> Backend | None:
    """The backend whose image ``spec`` is built FROM, if any."""
    if not spec.derives_from:
        return None
    return next((b for b in BACKENDS.values() if b.image == spec.derives_from),
                None)


def with_bases(names_in_use: set[str]) -> set[str]:
    """``names_in_use`` plus every backend they are built on top of.

    A moonshine-only install still depends on the runtime image, so its
    checks and its build have to stay in the picture.
    """
    out = set(names_in_use)
    for name in names_in_use:
        spec = BACKENDS.get(name)
        while spec is not None:
            spec = base_of(spec)
            if spec is None:
                break
            out.add(spec.name)
    return out


def get_or_default(name: str = "") -> Backend:
    """Like :func:`get`, but an unknown name silently yields the default,
    for read paths (status lines, GUI lists) that must not crash on a config
    from a newer or older podstage."""
    return BACKENDS.get(name) or BACKENDS[DEFAULT]
