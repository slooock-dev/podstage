"""Release update check against the public GitHub repository.

Strictly on demand: nothing here runs unless the user clicks the check button
(GUI Setup page) — podstage never phones home on its own. One anonymous GET
against the GitHub releases API, no telemetry attached.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import __version__

REPO = "slooock-dev/podstage"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"


@dataclass
class UpdateInfo:
    current: str
    latest: str            # latest release tag without the leading "v"
    is_newer: bool
    url: str               # release page of the latest version
    notes: str             # release body (markdown)
    mentions_image_rebuild: bool


def parse_version(tag: str) -> tuple[int, ...]:
    """"v0.1.3" / "0.1.3" → (0, 1, 3); non-numeric parts are ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", tag or "")) or (0,)


def _mentions_image_rebuild(notes: str) -> bool:
    """Heuristic: the CHANGELOG notes a required image rebuild explicitly
    (e.g. "Requires an image rebuild")."""
    text = notes.lower()
    return "rebuild" in text and "image" in text


def check_latest(timeout: float = 8.0) -> UpdateInfo:
    """Fetch the latest release and compare it against the running version.
    Raises RuntimeError on network/API failure (offline is a normal case the
    caller reports, not a crash)."""
    req = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"podstage/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        raise RuntimeError(f"update check failed: {e}") from e
    tag = str(data.get("tag_name") or "")
    if not tag:
        raise RuntimeError("update check failed: no release found")
    notes = str(data.get("body") or "")
    return UpdateInfo(
        current=__version__,
        latest=tag.lstrip("v"),
        is_newer=parse_version(tag) > parse_version(__version__),
        url=str(data.get("html_url") or RELEASES_URL),
        notes=notes,
        mentions_image_rebuild=_mentions_image_rebuild(notes),
    )
