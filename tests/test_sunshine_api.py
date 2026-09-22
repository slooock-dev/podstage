"""Tests for the sunshine web API client, pairing contract in particular."""

import pytest

from podstage.core import sunshine_api

PENDING = {"pairings": [{"address": "192.168.0.2", "id": "a" * 32, "name": "roth"}]}


def _record(monkeypatch, get_result, post_result=None):
    """Stub _request; returns the call log as (path, payload) tuples."""
    calls: list[tuple[str, dict | None]] = []

    def fake(path, web_port, payload=None, timeout=5.0):
        calls.append((path, payload))
        if payload is None:
            if isinstance(get_result, Exception):
                raise get_result
            return get_result
        return post_result or {}

    monkeypatch.setattr(sunshine_api, "_request", fake)
    return calls


def test_pair_sends_the_pending_pairing_id(monkeypatch):
    # sunshine answers 400 without it ("pairing_id must contain exactly 32
    # hexadecimal characters"), so the POST is preceded by the GET.
    calls = _record(monkeypatch, PENDING, {"status": "true"})
    assert sunshine_api.pair("1234", "deck") is True
    assert calls[0] == ("/api/pin", None)
    assert calls[1][1] == {"pin": "1234", "name": "deck", "pairing_id": "a" * 32}


def test_pair_without_a_pending_request_does_not_post(monkeypatch):
    # A POST without pairing_id answers 400, which would surface as an HTTP
    # error instead of pair_verified's "start it in moonlight first".
    calls = _record(monkeypatch, {"pairings": []}, {"status": "false"})
    assert sunshine_api.pair("1234", "deck") is False
    assert calls == [("/api/pin", None)]


def test_pair_survives_an_api_without_the_pairing_list(monkeypatch):
    # Older image than the code: GET /api/pin does not exist there, and the
    # old POST contract took pin + name alone.
    calls = _record(monkeypatch, sunshine_api.SunshineApiError("404"),
                    {"status": "true"})
    assert sunshine_api.pair("1234", "deck") is True
    assert calls[1][1] == {"pin": "1234", "name": "deck"}


def test_pair_refuses_to_guess_between_two_pending(monkeypatch):
    # The PIN belongs to exactly one request and the endpoint blocks until that
    # pairing resolves, so guessing costs a wrong client its attempt.
    two = {"pairings": [{"id": "b" * 32, "name": "roth", "address": "10.0.0.2"},
                        {"id": "c" * 32, "name": "deck", "address": "10.0.0.3"}]}
    calls = _record(monkeypatch, two, {"status": "true"})
    with pytest.raises(sunshine_api.SunshineApiError, match="roth.*deck"):
        sunshine_api.pair("1234", "deck")
    assert calls == [("/api/pin", None)]          # nothing posted


def test_pair_gives_the_pin_post_its_own_timeout(monkeypatch):
    seen: list[float] = []

    def fake(path, web_port, payload=None, timeout=5.0):
        seen.append(timeout)
        return PENDING if payload is None else {"status": "true"}

    monkeypatch.setattr(sunshine_api, "_request", fake)
    assert sunshine_api.pair("1234", "deck") is True
    # sunshine answers the POST only once the handshake resolved (upstream
    # #5680), so the default 5s would report a mistyped PIN as unreachable.
    assert seen[1] == sunshine_api.PIN_TIMEOUT > 5.0


def test_pair_reports_a_stalled_handshake_as_such(monkeypatch):
    def fake(path, web_port, payload=None, timeout=5.0):
        if payload is None:
            return PENDING
        raise sunshine_api.SunshineApiError("sunshine API unreachable "
                                            "(The read operation timed out)")

    monkeypatch.setattr(sunshine_api, "_request", fake)
    with pytest.raises(sunshine_api.SunshineApiError, match="did not complete"):
        sunshine_api.pair("1234", "deck")


def test_pending_pairings_ignores_junk(monkeypatch):
    _record(monkeypatch, {"pairings": [{"id": "x"}, "nope", None]})
    assert sunshine_api.pending_pairings() == [{"id": "x"}]
    _record(monkeypatch, {})
    assert sunshine_api.pending_pairings() == []


def test_pair_verified_names_the_missing_attempt(monkeypatch, tmp_path):
    _record(monkeypatch, {"pairings": []}, {"status": "false"})
    with pytest.raises(sunshine_api.SunshineApiError, match="no pairing attempt"):
        sunshine_api.pair_verified("1234", "deck", tmp_path)


def test_pair_verified_unpairs_duplicate_records(monkeypatch, tmp_path):
    # A fresh pairing of an already-paired client adds a second record for the
    # same cert, which sunshine then refuses. Heal it while sunshine is up.
    posts: list[tuple[str, dict]] = []

    def fake(path, web_port, payload=None, timeout=5.0):
        if payload is None:
            return PENDING
        posts.append((path, payload))
        return {"status": "true"}

    monkeypatch.setattr(sunshine_api, "_request", fake)
    monkeypatch.setattr(sunshine_api.sandbox, "paired_device_ids",
                        lambda home, backend=None: set() if not posts else {"new"})
    monkeypatch.setattr(sunshine_api.sandbox, "sunshine_devices", lambda home: [])
    monkeypatch.setattr(sunshine_api.sandbox, "duplicate_cert_uuids",
                        lambda devices: ["stale-1", "stale-2"])
    assert sunshine_api.pair_verified("1234", "deck", tmp_path) is True
    assert [p for p in posts if p[0] == "/api/clients/unpair"] == [
        ("/api/clients/unpair", {"uuid": "stale-1"}),
        ("/api/clients/unpair", {"uuid": "stale-2"}),
    ]
