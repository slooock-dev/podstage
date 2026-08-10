"""Streaming backends: what actually differs between sunshine and moonshine.

podstage streams a sandboxed Steam Big Picture to a moonlight client. *How*
that picture is composited, captured and encoded is the backend's job, and
there are two:

``sunshine``
    The original chain: labwc (headless) → gamescope (nested) → Steam, with
    sunshine capturing labwc through wlr-screencopy and encoding via
    NVENC/VAAPI. Runs on every GPU podstage supports, and is the only path
    with a live config API (sunshine's web UI).

``moonshine``
    `moonshine <https://github.com/hgaiser/moonshine>`_ is a GameStream server
    that brings its *own* headless compositor (smithay) and encodes with
    Vulkan Video. It replaces compositor, capture and server in one process,
    so labwc, the seat-shim, the keeper and the host-side mDNS publisher all
    fall away. In exchange it needs a GPU with a Vulkan video-encode queue
    (NVIDIA RTX, AMD RDNA2+, Intel Arc). Every older GPU that streams fine
    through sunshine's VAAPI path cannot use this backend at all.

Everything backend-specific is a field here; ``core/runtime.py`` reads them
and stays the single source of truth for the ``podman run`` invocation. The
per-profile choice lives in ``config.SessionConfig.backend``.
"""

from dataclasses import dataclass

DEFAULT = "sunshine"

# moonlight derives its whole port block from one base port with fixed
# offsets, so shifting the base moves every port with it and a client still
# reaches the set by entering "IP:<base>". Both backends use these offsets,
# they are moonlight's, not the server's.
PORT_OFFSETS: dict[str, int] = {
    "https": -5,     # 47984
    "http": 0,       # 47989  (the base port moonlight is pointed at)
    "video": 9,      # 47998/udp
    "control": 10,   # 47999/udp
    "audio": 11,     # 48000/udp
    "rtsp": 21,      # 48010
}


def ports(base: int) -> dict[str, int]:
    """The moonlight port block for a base port."""
    return {name: base + off for name, off in PORT_OFFSETS.items()}


# An underscore in the announced name makes moonlight-qt drop the session, and
# it does so silently at every layer: the service is announced correctly, the
# client queries, receives PTR, SRV, TXT and A in one packet within 0.1 s,
# caches them, and lists no host. Nothing on either side logs a word, so the
# session simply looks absent. moonlight-android is NOT affected, it resolves
# the SRV explicitly, so a phone that finds the session proves nothing about
# the desktop clients.
#
# A profile name plausibly carries an underscore ("sandbox_steam"), so a safe
# separator is not enough, the whole name has to pass through here. The kept
# set is deliberately narrow: the failure mode is invisible and a plainer
# label costs nothing. `isalnum` keeps non-ASCII letters, so "Wohnzimmer-Süd"
# survives. Established by A/B/A measurement, see the commit that added this.
_NAME_KEEP = "-"


def safe_name(name: str) -> str:
    """A session name moonlight will list. See above for why this is narrow."""
    kept = "".join(c if (c.isalnum() or c in _NAME_KEEP) else "-" for c in name)
    while "--" in kept:
        kept = kept.replace("--", "-")
    return kept.strip("-") or "podstage"


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
    port_env      container env var carrying the moonlight base port
    name_env      container env var carrying the advertised session name
    web_port_off  offset of a management web UI from the base port; None for
                  a backend without one
    host_mdns     needs runtime.start_publisher (the host's avahi) to be
                  discoverable. moonshine answers mDNS itself
    live_config   has an API that applies config changes to a running session
    res_locked    with dynamic resolution, renders at the FIRST client's mode
                  and keeps it until the container restarts. moonshine
                  relaunches compositor and app per session, so there the mode
                  follows every reconnect
    full_dev      needs the host /dev bound wholesale (inputtino creates its
                  gamepads through /dev/uhid and Steam Input needs the
                  /dev/hidraw* node appearing with them, which cannot be
                  pre-mounted)
    vulkan_video  requires a Vulkan video-encode queue on the GPU
    needs_kcmp    needs kcmp(2), which podman's default seccomp profile blocks;
                  moonshine validates every cached Vulkan DMA-BUF import with
                  it and panics on the first cache hit without it.
                  core/runtime.py answers this with a derived profile, not with
                  CAP_SYS_PTRACE (see there)
    summary       one line for `podstage sandbox list` / the GUI
    """

    name: str
    label: str
    image: str
    src_subdir: str
    derives_from: str | None
    port_env: str
    name_env: str
    web_port_off: int | None
    host_mdns: bool
    live_config: bool
    res_locked: bool
    full_dev: bool
    vulkan_video: bool
    needs_kcmp: bool
    summary: str

    def web_port(self, base: int) -> int | None:
        return None if self.web_port_off is None else base + self.web_port_off

    def advertised_name(self, profile: str = "") -> str:
        """What moonlight shows for this profile on this backend.

        The backend belongs in the name because the two are separate servers
        with separate pairings, kept in different state files: a client paired
        to a profile's sunshine session is NOT paired to its moonshine one.
        Two entries called the same thing would be indistinguishable in the
        client, and the wrong one silently fails to connect.

        Runs through `safe_name`, which is not cosmetic: a name moonlight
        rejects makes the whole session undiscoverable. See there.

        The suffix is lower-cased so both backends read the same way in the
        client list ("-sunshine", "-moonshine"), whatever `label` carries.
        """
        return safe_name(f"{profile or 'podstage'}-{self.label.lower()}")


SUNSHINE = Backend(
    name="sunshine",
    label="sunshine",
    image="podstage-runtime:latest",
    src_subdir="containers/runtime",
    derives_from=None,
    port_env="PS_SUNSHINE_PORT",
    name_env="PS_SUNSHINE_NAME",
    web_port_off=1,          # sunshine's web UI, 47990 by default
    host_mdns=True,          # no avahi in the container
    live_config=True,        # POST /api/config + /api/restart
    res_locked=True,         # the first client's mode, until the container restarts
    full_dev=False,          # /dev/uinput + /dev/input suffice
    vulkan_video=False,
    needs_kcmp=False,
    summary="labwc + gamescope + sunshine (NVENC/VAAPI), works on every supported GPU",
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
    name_env="PS_MOONSHINE_NAME",
    web_port_off=None,       # config.toml on disk, no management UI
    host_mdns=False,         # built-in mDNS responder (--network host)
    live_config=False,       # config changes need a session restart
    res_locked=False,        # compositor and app are relaunched per session
    full_dev=True,           # inputtino: /dev/uhid + the hidraw node
    vulkan_video=True,
    needs_kcmp=True,         # kcmp(2) for the DMA-BUF import cache
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


def get_or_default(name: str = "") -> Backend:
    """Like :func:`get`, but an unknown name silently yields the default,
    for read paths (status lines, GUI lists) that must not crash on a config
    from a newer or older podstage."""
    return BACKENDS.get(name) or BACKENDS[DEFAULT]
