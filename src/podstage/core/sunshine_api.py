"""Thin client for the runtime container's Sunshine web API.

Sunshine's web UI (https://localhost:<web_port>) exposes a JSON API guarded by
basic auth (the per-install random credentials from
``config.sunshine_web_credentials``, seeded headlessly by the entrypoint) and a
self-signed TLS cert — hence the unverified SSL context. Config changes via
``POST /api/config`` land in the tmpfs sunshine.conf and apply after
``POST /api/restart`` (the stream drops for a moment; pairing survives — it
lives in the persistent state dir). Persistent quality settings additionally
go through the profile's ``sunshine_extra`` → ``PS_SUNSHINE_EXTRA``.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request

from .. import config

DEFAULT_WEB_PORT = 47990

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
        raise SunshineApiError(f"Sunshine-API nicht erreichbar ({e})") from e
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as e:
        raise SunshineApiError(f"unerwartete Antwort: {body[:200]}") from e


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


def pair(pin: str, name: str, web_port: int = DEFAULT_WEB_PORT) -> bool:
    """Complete a Moonlight pairing: the client shows a 4-digit PIN, this
    submits it (what the web UI's PIN form does). Sunshine must be running."""
    resp = _request("/api/pin", web_port, payload={"pin": pin, "name": name})
    return str(resp.get("status", "")).lower() == "true"


def restart(web_port: int = DEFAULT_WEB_PORT) -> None:
    """Apply a posted config: Sunshine restarts itself (stream drops briefly).
    The API often closes the connection mid-restart — that is success."""
    try:
        _request("/api/restart", web_port, payload={})
    except SunshineApiError:
        pass
