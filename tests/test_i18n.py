"""Tests for the GUI translation layer (stdlib-only, no PyQt6 needed)."""

import ast
import pathlib
import string

import pytest

from podstage.ui import i18n
from podstage.ui.translations import de

UI_DIR = pathlib.Path(i18n.__file__).parent
LOCALE_VARS = ("PS_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


def _clear_locale(monkeypatch):
    for v in LOCALE_VARS:
        monkeypatch.delenv(v, raising=False)


def _source_keys() -> set[str]:
    """Every literal string passed as the first arg to tr() across the UI."""
    keys: set[str] = set()
    for p in UI_DIR.rglob("*.py"):
        if p.name == "i18n.py" or "translations" in p.parts:
            continue
        for node in ast.walk(ast.parse(p.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def _fields(s: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(s) if name}


@pytest.fixture(autouse=True)
def _restore_language():
    yield
    i18n.set_language("en")  # explicit override wins → deterministic reset


# -- language detection -----------------------------------------------------

def test_default_is_english(monkeypatch):
    _clear_locale(monkeypatch)
    assert i18n.detect() == "en"


def test_ds_lang_env_override(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("PS_LANG", "de")
    assert i18n.detect() == "de"


def test_explicit_override_beats_env(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("PS_LANG", "de")
    assert i18n.detect("en") == "en"


def test_auto_falls_through_to_locale(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detect("auto") == "de"


def test_locale_variants_normalize(monkeypatch):
    _clear_locale(monkeypatch)
    for value in ("de", "de_DE.UTF-8", "de-DE", "de:en"):
        monkeypatch.setenv("LANG", value)
        assert i18n.detect() == "de", value


def test_unknown_language_falls_back_to_english(monkeypatch):
    _clear_locale(monkeypatch)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.detect() == "en"


def test_set_language_and_current(monkeypatch):
    _clear_locale(monkeypatch)
    assert i18n.set_language("de") == "de"
    assert i18n.current() == "de"


# -- translation lookup -----------------------------------------------------

def test_tr_english_is_identity():
    i18n.set_language("en")
    assert i18n.tr("Preview") == "Preview"


def test_tr_german_lookup():
    i18n.set_language("de")
    assert i18n.tr("Preview") == "Vorschau"


def test_tr_missing_falls_back_to_source():
    i18n.set_language("de")
    assert i18n.tr("a string with no translation") == "a string with no translation"


def test_tr_formats_named_fields():
    i18n.set_language("de")
    assert i18n.tr("Profile '{name}' saved.", name="deck") == "Profil 'deck' gespeichert."
    i18n.set_language("en")
    assert i18n.tr("Profile '{name}' saved.", name="deck") == "Profile 'deck' saved."


# -- catalog integrity ------------------------------------------------------

def test_no_orphan_translations():
    """Every German key must correspond to a real tr() call (catches typos)."""
    orphans = set(de.TEXTS) - _source_keys()
    assert not orphans, f"de.py has keys not used in the UI: {orphans}"


def test_placeholders_match_across_languages():
    for src, dst in de.TEXTS.items():
        assert _fields(src) == _fields(dst), f"placeholder mismatch for {src!r}"
