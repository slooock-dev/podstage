"""Thin client for the runtime container's sunshine web API.

sunshine's web UI (https://localhost:<web_port>) exposes a JSON API guarded by
basic auth (the per-install random credentials from
``config.sunshine_web_credentials``, seeded headlessly by the entrypoint) and a
self-signed TLS cert — hence the unverified SSL context. Config changes via
``POST /api/config`` land in the tmpfs sunshine.conf and apply after
``POST /api/restart`` (the stream drops for a moment; pairing survives — it
lives in the persistent state dir). Persistent quality settings additionally
go through the profile's ``sunshine_extra`` → ``PS_SUNSHINE_EXTRA``.
"""

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config
from . import sandbox

DEFAULT_WEB_PORT = 47990

# POST /api/pin answers only once the pairing handshake resolved (sunshine
# >= v2026.914, upstream #5680): success, wrong PIN, cancellation or the
# client's own timeout. The default request timeout would turn a mistyped PIN
# into "API unreachable".
PIN_TIMEOUT = 30.0

# GET /api/config decorates the config with read-only metadata that the POST
# endpoint must not receive back.
_METADATA_KEYS = {"platform", "version", "restart_supported"}


class SunshineApiError(RuntimeError):
    pass


def _request(path: str, web_port: int, payload: dict | None = None,
             timeout: float = 5.0) -> dict:
    user = os.environ.get("PS_WEB_USER")
    password = os.environ.get("PS_WEB_PASS")
    if not user or not password:
        stored_user, stored_pass = config.sunshine_web_credentials()
        user = user or stored_user
        password = password or stored_pass
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(
        f"https://localhost:{web_port}{path}",
        headers={"Authorization": f"Basic {token}",
                 "Content-Type": "application/json"},
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST" if payload is not None else "GET",
    )
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            body = resp.read().decode()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise SunshineApiError(f"sunshine API unreachable ({e})") from e
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as e:
        raise SunshineApiError(f"unexpected response: {body[:200]}") from e


def get_config(web_port: int = DEFAULT_WEB_PORT) -> dict:
    return _request("/api/config", web_port)


def set_options(changes: dict[str, str], web_port: int = DEFAULT_WEB_PORT) -> None:
    """Merge ``changes`` into the live config and write it back.

    POST /api/config replaces the whole config file, so the current config is
    fetched first and metadata keys are stripped.
    """
    cfg = {k: v for k, v in get_config(web_port).items() if k not in _METADATA_KEYS}
    cfg.update({k: str(v) for k, v in changes.items()})
    _request("/api/config", web_port, payload=cfg)


def pending_pairings(web_port: int = DEFAULT_WEB_PORT) -> list[dict]:
    """The pairing requests sunshine is waiting on: ``id`` (32 hex chars),
    ``name`` and ``address`` of the asking client. Empty when no client has
    asked yet or the request timed out."""
    pairings = _request("/api/pin", web_port).get("pairings")
    if not isinstance(pairings, list):
        return []
    return [p for p in pairings if isinstance(p, dict)]


def pair(pin: str, name: str, web_port: int = DEFAULT_WEB_PORT) -> bool:
    """Complete a moonlight pairing: the client shows a 4-digit PIN, this
    submits it (what the web UI's PIN form does). sunshine must be running.

    POST /api/pin carries the pending request's ``pairing_id`` next to the PIN;
    without it sunshine answers 400 ("pairing_id must contain exactly 32
    hexadecimal characters") and no pairing can ever complete. An API without
    GET /api/pin is an older image than this code: fall back to the old
    pin + name payload.

    Nothing pending means no POST at all. The endpoint answers 400 without a
    pairing_id, and that error would replace the caller's "start it in
    moonlight first" with an HTTP code. Several pending requests raise instead
    of guessing: the PIN belongs to exactly one of them, and a miss costs that
    client its attempt.
    """
    payload = {"pin": pin, "name": name}
    try:
        pending = pending_pairings(web_port)
    except SunshineApiError:
        resp = _request("/api/pin", web_port, payload=payload)
        return str(resp.get("status", "")).lower() == "true"
    if not pending:
        return False
    if len(pending) > 1:
        waiting = ", ".join(f"{p.get('name') or '?'} ({p.get('address') or '?'})"
                            for p in pending)
        raise SunshineApiError(
            f"{len(pending)} clients are waiting to pair ({waiting}); a PIN "
            "belongs to one of them and the API needs that request picked "
            "explicitly — do it in sunshine's web UI, or retry with a single "
            "client waiting")
    try:
        resp = _request("/api/pin", web_port, timeout=PIN_TIMEOUT,
                        payload={**payload, "pairing_id": str(pending[0].get("id", ""))})
    except SunshineApiError as e:
        if "timed out" not in str(e):
            raise
        raise SunshineApiError(
            "pairing did not complete in time; the PIN is wrong or the client "
            "stopped waiting (sunshine answers only once the handshake "
            "resolved)") from e
    return str(resp.get("status", "")).lower() == "true"


def pair_verified(pin: str, name: str, home: Path,
                  web_port: int = DEFAULT_WEB_PORT, timeout: float = 10.0) -> bool:
    """Submit a PIN and wait for a new device in the sandbox pairing state.

    sunshine >= v2026.914 reports the real pairing result, so ``pair`` returning
    true already means the handshake completed; the state poll additionally
    proves the device reached the sandbox's persistent state, which is what
    survives a session restart. False: never completed. Raises: unreachable /
    no attempt pending. Compared by device id (uuid/cert), so a re-pairing
    under an existing name counts as success too."""
    before = sandbox.paired_device_ids(home)
    if not pair(pin, name, web_port):
        raise SunshineApiError("no pairing attempt pending; start it in "
                               "moonlight first")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sandbox.paired_device_ids(home) - before:
            return True
        time.sleep(0.5)
    return False


def restart(web_port: int = DEFAULT_WEB_PORT) -> None:
    """Apply a posted config: sunshine restarts itself (stream drops briefly).
    The API often closes the connection mid-restart — that is success."""
    try:
        _request("/api/restart", web_port, payload={})
    except SunshineApiError:
        pass
