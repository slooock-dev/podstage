"""Tests for the moonshine HTTP client (no network: urlopen is stubbed)."""

import io
import urllib.error

import pytest

from podstage.core import moonshine_api


class _Resp(io.BytesIO):
    def __init__(self, body: str, status: int = 200) -> None:
        super().__init__(body.encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _stub_urlopen(monkeypatch, *, body="", status=200, http_error=None,
                  capture=None):
    def fake(req, timeout=None):
        if capture is not None:
            capture.append(req)
        if http_error is not None:
            raise http_error
        return _Resp(body, status)

    monkeypatch.setattr(moonshine_api.urllib.request, "urlopen", fake)


# -- pairing ----------------------------------------------------------------

def test_pair_posts_a_form_body_with_moonlights_fixed_id(monkeypatch):
    """No auth, no JSON: uniqueid + pin, form-encoded, on the base port."""
    seen: list = []
    _stub_urlopen(monkeypatch, body="", capture=seen)
    assert moonshine_api.pair("1234", 47989) is True
    req = seen[0]
    assert req.full_url == "http://localhost:47989/submit-pin"
    assert req.data == b"uniqueid=0123456789ABCDEF&pin=1234"
    assert req.get_header("Content-type") == "application/x-www-form-urlencoded"


def test_pair_returns_false_on_the_honest_400(monkeypatch):
    """moonshine answers 400 when no attempt is pending (sunshine returns
    true regardless), so that is a result and not a transport failure."""
    err = urllib.error.HTTPError("u", 400, "Failed to register PIN.", {},
                                 io.BytesIO(b"Failed to register PIN."))
    _stub_urlopen(monkeypatch, http_error=err)
    assert moonshine_api.pair("1234", 47989) is False


def test_pair_raises_when_unreachable(monkeypatch):
    _stub_urlopen(monkeypatch, http_error=urllib.error.URLError("refused"))
    with pytest.raises(moonshine_api.MoonshineApiError, match="unreachable"):
        moonshine_api.pair("1234", 47989)


def test_pair_verified_needs_a_new_cert_in_the_sandbox_state(monkeypatch, tmp_path):
    """The endpoint accepts a wrong PIN too, so the persisted certificate is
    the signal. Real (tiny) timeouts here: patching time.monotonic would
    patch it for pytest as well."""
    conf = tmp_path / ".local/share/moonshine"
    conf.mkdir(parents=True)
    state = conf / "state.toml"
    state.write_text('unique_id = "u"\nclients = []\npaired_certs = []\n')

    # PIN accepted, but no certificate is ever persisted: nothing paired.
    _stub_urlopen(monkeypatch, body="")
    assert moonshine_api.pair_verified("1234", tmp_path, port=47989,
                                       timeout=0.01) is False

    # A real pairing persists the certificate as moonshine answers the POST.
    def pairing_urlopen(req, timeout=None):
        state.write_text('unique_id = "u"\nclients = ["0123456789ABCDEF"]\n'
                         'paired_certs = ["ab12"]\n')
        return _Resp("")

    monkeypatch.setattr(moonshine_api.urllib.request, "urlopen", pairing_urlopen)
    assert moonshine_api.pair_verified("1234", tmp_path, port=47989,
                                       timeout=5.0) is True


def test_pair_verified_reports_a_missing_attempt(monkeypatch, tmp_path):
    err = urllib.error.HTTPError("u", 400, "no", {}, io.BytesIO(b"no"))
    _stub_urlopen(monkeypatch, http_error=err)
    with pytest.raises(moonshine_api.MoonshineApiError, match="no pairing attempt"):
        moonshine_api.pair_verified("1234", tmp_path, port=47989)


