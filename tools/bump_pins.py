#!/usr/bin/env python3
"""Show, and with --apply write, updates for the version pins in
containers/runtime/Containerfile: the Arch base-image digest and the
Sunshine release (tag + asset sha256).

Stdlib only. After --apply: `podstage runtime build`, `podstage doctor`,
then stream once against a real client before committing.
"""

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

CONTAINERFILE = Path(__file__).resolve().parents[1] / "containers/runtime/Containerfile"
UA = {"User-Agent": "podstage-bump-pins"}


def fetch(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def gh_latest(repo: str) -> dict:
    return json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))


def arch_digest() -> str:
    token = json.loads(fetch(
        "https://auth.docker.io/token?service=registry.docker.io"
        "&scope=repository:library/archlinux:pull"))["token"]
    req = urllib.request.Request(
        "https://registry-1.docker.io/v2/library/archlinux/manifests/latest",
        method="HEAD",
        headers={**UA, "Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.oci.image.index.v1+json,"
                           "application/vnd.docker.distribution.manifest.list.v2+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers["Docker-Content-Digest"]


def sunshine_latest() -> tuple[str, str]:
    rel = gh_latest("LizardByte/Sunshine")
    tag = rel["tag_name"]
    name = f"sunshine-{tag.lstrip('v')}-1-x86_64.pkg.tar.zst"
    for asset in rel["assets"]:
        if asset["name"] == name:
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                return tag, digest.removeprefix("sha256:")
            return tag, hashlib.sha256(fetch(asset["browser_download_url"])).hexdigest()
    raise SystemExit(f"Sunshine {tag}: asset {name} not found")


def main() -> int:
    apply = "--apply" in sys.argv
    text = CONTAINERFILE.read_text()
    pins = {
        "base": re.search(r"archlinux:latest@(sha256:[0-9a-f]+)", text).group(1),
        "sunshine": re.search(r"SUNSHINE_VERSION=(\S+)", text).group(1),
        "sunshine_sha": re.search(r"SUNSHINE_SHA256=([0-9a-f]+)", text).group(1),
    }
    new_base = arch_digest()
    sun_tag, sun_sha = sunshine_latest()

    rows = [
        ("base image", pins["base"][:19], new_base[:19], pins["base"] != new_base),
        ("sunshine", pins["sunshine"], sun_tag, pins["sunshine"] != sun_tag),
    ]
    for name, cur, new, changed in rows:
        print(f"{name:12} {cur:22} -> {new:22} {'UPDATE' if changed else 'current'}")
    if not apply:
        print("\nDry run; --apply writes the Containerfile.")
        return 0

    text = text.replace(pins["base"], new_base)
    text = text.replace(f"SUNSHINE_VERSION={pins['sunshine']}",
                        f"SUNSHINE_VERSION={sun_tag}")
    text = text.replace(f"SUNSHINE_SHA256={pins['sunshine_sha']}",
                        f"SUNSHINE_SHA256={sun_sha}")
    CONTAINERFILE.write_text(text)
    print("\nContainerfile updated. Next: podstage runtime build && podstage doctor, "
          "then stream once before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
