"""Lightweight translation layer for the management GUI.

English is the source language: every user-facing string in ``ui.*`` is written
in English and wrapped in :func:`tr`. Translations live in ``ui/translations/``
as plain ``{english: translated}`` dicts — no build step, no binary catalogs,
no external tooling. A missing entry falls back to the (readable) English
source, so a half-finished translation never shows blanks.

Deliberately dependency-free (stdlib only, no PyQt6) so the whole i18n layer is
importable and unit-testable under the system Python, unlike the rest of ``ui``.

Language selection, highest priority first:

1. an explicit code passed to :func:`set_language` (the GUI reads it from
   ``config.toml``); ``"auto"`` / empty means "fall through"
2. the ``PS_LANG`` environment variable
3. the system locale (``LC_ALL`` / ``LC_MESSAGES`` / ``LANG`` / ``LANGUAGE``)
4. English

Runtime language switching is intentionally not supported — the GUI reads the
choice once at startup and applies a new one on the next launch. That keeps
:func:`tr` a trivial dict lookup and avoids re-translating a live widget tree.
"""

from __future__ import annotations

import os

from .translations import TABLES

DEFAULT = "en"
# Languages we ship a catalog for (English is implicit — it is the source).
AVAILABLE = ("en", *sorted(TABLES))

_active = DEFAULT


def _normalize(value: str | None) -> str | None:
    """Reduce a locale/override string to a supported 2-letter code, or None.

    Accepts ``de``, ``de_DE.UTF-8``, ``de-DE``, ``de:en`` … Returns None for
    empty, ``"auto"``, or anything we do not have a catalog for (so the caller
    keeps looking down the priority chain)."""
    if not value:
        return None
    code = value.strip().lower()
    if code in ("", "auto"):
        return None
    for sep in (":", ".", "_", "-"):
        code = code.split(sep)[0]
    return code if code in AVAILABLE else None


def detect(override: str | None = None) -> str:
    """Resolve the active language following the documented priority chain."""
    candidates = [override, os.environ.get("PS_LANG")]
    candidates += [os.environ.get(v) for v in
                   ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    for cand in candidates:
        code = _normalize(cand)
        if code:
            return code
    return DEFAULT


def set_language(override: str | None = None) -> str:
    """Set (and return) the active language. ``override`` is usually the
    persisted ``config.language`` (``"auto"`` to follow env/locale)."""
    global _active
    _active = detect(override)
    return _active


def current() -> str:
    return _active


def tr(text: str, /, **kwargs: object) -> str:
    """Translate ``text`` into the active language, then ``str.format`` it.

    ``text`` is the English source and doubles as the lookup key. Interpolate
    with named fields so both languages share one call site::

        tr("Profile '{name}' created.", name=sc.name)
    """
    table = TABLES.get(_active)
    out = table.get(text, text) if table else text
    return out.format(**kwargs) if kwargs else out
