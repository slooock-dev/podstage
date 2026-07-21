"""Graphical privilege elevation via pkexec.

The GUI must never ask the user to copy sudo commands into a terminal. Every
root-gated setup step (udev rules, CDI spec, firewalld) runs through
:func:`run_root`, which shows the desktop polkit password dialog. polkit's
default for pkexec is ``auth_admin_keep`` — consecutive actions within a few
minutes need only one password entry.

Nothing here elevates silently: every call pops the dialog (or fails), and the
exact shell that will run as root is always available for display beforehand.
"""

from __future__ import annotations

import shutil
import subprocess

# pkexec exit codes (from its man page) — everything else comes from the command.
PKEXEC_DISMISSED = 126  # user closed the auth dialog
PKEXEC_NOT_AUTHORIZED = 127


def available() -> bool:
    return shutil.which("pkexec") is not None


def run_root(shell: str, timeout: int = 600) -> tuple[int, str]:
    """Run ``shell`` as root via pkexec (polkit GUI auth dialog).

    Returns (returncode, combined output). Never raises on failure — the
    caller renders the outcome.
    """
    try:
        p = subprocess.run(
            ["pkexec", "/bin/sh", "-c", shell],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (p.stdout + p.stderr).strip()
        if p.returncode == PKEXEC_DISMISSED:
            out = out or "Autorisierung abgebrochen"
        elif p.returncode == PKEXEC_NOT_AUTHORIZED:
            out = out or "Autorisierung fehlgeschlagen"
        return p.returncode, out
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def fix_shell(fix: str) -> tuple[str, bool]:
    """Turn a doctor fix command line into (shell, needs_root).

    Doctor fixes are written for copy/paste and prefix root-gated steps with
    ``sudo``. For pkexec the whole line runs as root already, so every
    ``sudo `` is stripped. Mixed user/root pipelines (``user-cmd | sudo
    root-cmd``) must NOT go through here — running the user half as root
    changes its meaning; callers special-case those.
    """
    if "|" in fix and "sudo" in fix:
        raise ValueError(f"mixed user/root pipeline needs special handling: {fix}")
    needs_root = "sudo " in fix
    return fix.replace("sudo ", ""), needs_root
