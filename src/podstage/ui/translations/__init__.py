"""Translation catalogs, keyed by 2-letter language code.

Each catalog is a plain ``{english_source: translation}`` dict. English is the
source language and has no catalog. To add a language, drop a ``<code>.py``
module here that exposes ``TEXTS`` and register it in ``TABLES`` below.
"""

from __future__ import annotations

from . import de

TABLES: dict[str, dict[str, str]] = {"de": de.TEXTS}
