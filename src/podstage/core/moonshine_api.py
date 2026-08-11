"""Thin client for the moonshine backend's HTTP endpoints.

The counterpart to :mod:`podstage.core.sunshine_api`, and deliberately much
smaller, because moonshine exposes much less: pairing is
``POST http://…:<base>/submit-pin`` over plain HTTP with no auth and a form
body (sunshine: TLS + basic auth, JSON, ``…:47990/api/pin``); a failed attempt
returns ``400 Failed to register PIN.`` where sunshine returns true anyway
(hence ``pair_verified``); there is no config endpoint, settings live in
config.toml and need a restart (sunshine applies them live via
``POST /api/config`` + ``/api/restart``); paired state is state.toml in the
sandbox HOME, sunshine's is state.json.

There is nothing to authenticate against here: the endpoint sits on the same
port moonlight talks to and takes anyone's PIN. That is moonshine's model, not
a setting podstage can tighten. It is the reason ``Backend.live_config`` is
False and why quality settings are not wired for this backend.

``pair_verified`` still confirms against the sandbox state rather than trusting
the response, so the CLI and GUI report the same kind of truth on both
backends.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import sandbox

# moonlight identifies itself with this fixed id, so nothing has to be
# scraped out of a running session to complete a pairing.
MOONLIGHT_CLIENT_ID = "0123456789ABCDEF"


class MoonshineApiError(RuntimeError):
    pass


def _post(path: str, port: int, form: dict[str, str],
          timeout: float = 5.0) -> tuple[int, str]:
    """``(http_status, body)``. Raises MoonshineApiError if unreachable."""
    req = urllib.request.Request(
        f"http://localhost:{port}{path}",
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        # A 400 is a real answer here ("no pairing attempt pending"), not a
        # transport failure, so hand it back instead of raising.
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise MoonshineApiError(f"moonshine unreachable on port {port} ({e})") from e


def pair(pin: str, port: int, unique_id: str = MOONLIGHT_CLIENT_ID) -> bool:
    """Submit the 4-digit PIN moonlight is showing. False when moonshine has
    no pairing attempt pending (it answers an honest 400 for that, unlike
    sunshine); raises MoonshineApiError if it cannot be reached at all."""
    status, body = _post("/submit-pin", port, {"uniqueid": unique_id, "pin": pin})
    if status == 400:
        return False
    if status >= 300:
        raise MoonshineApiError(f"pairing failed (http {status}): {body[:200]}")
    return True


def pair_verified(pin: str, home: Path, port: int,
                  unique_id: str = MOONLIGHT_CLIENT_ID,
                  timeout: float = 10.0) -> bool:
    """Submit a PIN and wait for a new entry in the sandbox pairing state.

    A wrong PIN is accepted by the endpoint and only fails during the
    handshake, so the persisted certificate is the reliable signal, the same
    approach as ``sunshine_api.pair_verified``. Compared by certificate, so
    re-pairing an already known client counts as success.

    False: never completed. Raises: unreachable, or no attempt pending.
    """
    before = sandbox.paired_device_ids(home, backend="moonshine")
    if not pair(pin, port, unique_id):
        raise MoonshineApiError("no pairing attempt pending; start it in "
                                "moonlight first")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sandbox.paired_device_ids(home, backend="moonshine") - before:
            return True
        time.sleep(0.5)
    return False
