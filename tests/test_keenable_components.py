"""Unit tests for the Keenable Langflow extension bundle (``lfx-keenable``).

Offline: the HTTP transport is faked at the ``httpx.Client`` boundary, so these
exercise endpoint selection, attribution headers, the SSRF guard, HTTPS
enforcement, error mapping, and the component wiring without a network.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lfx_keenable import KeenableFetchComponent, KeenableSearchComponent
from lfx_keenable.components.keenable import _client
from lfx_keenable.components.keenable._client import (
    KeenableError,
    keenable_get,
    keenable_post,
    reject_private_fetch_target,
    resolve_api_key,
    resolve_base_url,
)


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text="", raise_on_json=False):
        self.status_code = status_code
        self._json = json_body
        self.text = text
        self._raise_on_json = raise_on_json

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._raise_on_json:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    """Captures the last request and returns a queued response."""

    last = {}

    def __init__(self, response):
        self._response = response

    def __call__(self, *args, **kwargs):  # httpx.Client(timeout=...)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        _FakeClient.last = {"method": "POST", "url": url, "json": json, "headers": headers}
        return self._response

    def get(self, url, params=None, headers=None):
        _FakeClient.last = {"method": "GET", "url": url, "params": params, "headers": headers}
        return self._response


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    monkeypatch.delenv("KEENABLE_API_URL", raising=False)


def _patch_client(monkeypatch, response):
    monkeypatch.setattr(_client.httpx, "Client", _FakeClient(response))


# --------------------------------------------------------------------------- #
# resolve_base_url
# --------------------------------------------------------------------------- #


def test_base_url_default_https():
    assert resolve_base_url() == "https://api.keenable.ai"


def test_base_url_env_https(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_URL", "https://eu.keenable.ai/")
    assert resolve_base_url() == "https://eu.keenable.ai"


def test_base_url_http_loopback_allowed(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_URL", "http://localhost:8000")
    assert resolve_base_url() == "http://localhost:8000"


def test_base_url_http_public_rejected(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_URL", "http://api.keenable.ai")
    with pytest.raises(KeenableError):
        resolve_base_url()


def test_base_url_no_host_rejected(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_URL", "https://")
    with pytest.raises(KeenableError):
        resolve_base_url()


# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://[::1]/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://metadata.google.internal/x",
        "https:///nohost",
    ],
)
def test_reject_private_fetch_target(url):
    with pytest.raises(KeenableError):
        reject_private_fetch_target(url)


def test_public_fetch_target_allowed():
    # Domain names that are not IP literals pass; backend SSRF guard is the backstop.
    reject_private_fetch_target("https://example.com/article")


# --------------------------------------------------------------------------- #
# resolve_api_key
# --------------------------------------------------------------------------- #


def test_resolve_api_key_blank_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_KEY", "env-key")
    assert resolve_api_key("   ") == "env-key"


def test_resolve_api_key_explicit_wins(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_KEY", "env-key")
    assert resolve_api_key("explicit") == "explicit"


def test_resolve_api_key_none_when_absent():
    assert resolve_api_key("") is None
    assert resolve_api_key(None) is None


# --------------------------------------------------------------------------- #
# Transport: endpoint selection, attribution, errors
# --------------------------------------------------------------------------- #


def test_post_keyless_uses_public_path_and_attribution(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(json_body={"results": []}))
    keenable_post("/v1/search/public", "/v1/search", {"query": "x"}, None, 30.0)
    sent = _FakeClient.last
    assert sent["url"].endswith("/v1/search/public")
    assert sent["headers"]["X-Keenable-Title"] == "Langflow"
    assert "X-API-Key" not in sent["headers"]
    assert sent["headers"]["User-Agent"].startswith("keenable-langflow/")


def test_post_keyed_uses_authenticated_path(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(json_body={"results": []}))
    keenable_post("/v1/search/public", "/v1/search", {"query": "x"}, "secret", 30.0)
    sent = _FakeClient.last
    assert sent["url"].endswith("/v1/search")
    assert sent["headers"]["X-API-Key"] == "secret"


def test_get_keyless_fetch_path(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(json_body={"content": "hi"}))
    keenable_get("/v1/fetch/public", "/v1/fetch", {"url": "https://e.com"}, None, 30.0)
    assert _FakeClient.last["url"].endswith("/v1/fetch/public")


@pytest.mark.parametrize(
    ("status", "needle"),
    [(401, "authentication"), (402, "credits"), (429, "rate limit"), (500, "500")],
)
def test_error_status_mapping(monkeypatch, status, needle):
    _patch_client(monkeypatch, _FakeResponse(status_code=status, json_body={"message": "boom"}))
    with pytest.raises(KeenableError) as exc:
        keenable_post("/v1/search/public", "/v1/search", {"query": "x"}, None, 30.0)
    assert needle in str(exc.value).lower()


def test_non_json_response_raises(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(text="<html>", raise_on_json=True))
    with pytest.raises(KeenableError):
        keenable_post("/v1/search/public", "/v1/search", {"query": "x"}, None, 30.0)


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #


def test_search_component_initialization():
    component = KeenableSearchComponent(query="typescript", mode="pro", _session_id="t")
    node = component.to_frontend_node()["data"]["node"]
    assert node["template"]["query"]["value"] == "typescript"
    assert node["template"]["mode"]["value"] == "pro"


def test_search_returns_results(monkeypatch):
    body = {"results": [{"title": "T", "url": "https://e.com", "description": "d"}]}
    _patch_client(monkeypatch, _FakeResponse(json_body=body))
    component = KeenableSearchComponent(query="x", mode="pro", _session_id="t")
    df = component.search()
    assert len(df) == 1
    sent = _FakeClient.last
    assert sent["json"]["query"] == "x"
    assert sent["json"]["mode"] == "pro"


def test_search_filters_are_sent(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(json_body={"results": []}))
    component = KeenableSearchComponent(
        query="x", mode="pro", site="github.com", published_after="2026-01-01", _session_id="t"
    )
    component.search()
    sent = _FakeClient.last["json"]
    assert sent["site"] == "github.com"
    assert sent["published_after"] == "2026-01-01"


def test_search_error_returns_error_data(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(status_code=429, json_body={"message": "slow down"}))
    component = KeenableSearchComponent(query="x", mode="pro", _session_id="t")
    df = component.search()
    assert len(df) == 1
    # the single row carries the error rather than crashing the flow
    assert "error" in df.iloc[0].to_dict()


def test_fetch_component_initialization():
    component = KeenableFetchComponent(url="https://example.com", _session_id="t")
    node = component.to_frontend_node()["data"]["node"]
    assert node["template"]["url"]["value"] == "https://example.com"


def test_fetch_returns_content(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse(json_body={"url": "https://e.com", "title": "T", "content": "body"}))
    component = KeenableFetchComponent(url="https://e.com", _session_id="t")
    df = component.fetch()
    assert len(df) == 1
    assert _FakeClient.last["url"].endswith("/v1/fetch/public")


@pytest.mark.parametrize("bad_url", ["ftp://e.com/x", "http://127.0.0.1/x", "not-a-url"])
def test_fetch_rejects_bad_urls(monkeypatch, bad_url):
    # No client patch: the guard must trip before any request.
    component = KeenableFetchComponent(url=bad_url, _session_id="t")
    df = component.fetch()
    assert "error" in df.iloc[0].to_dict()


def test_fetch_keyed_path(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_KEY", "secret")
    _patch_client(monkeypatch, _FakeResponse(json_body={"content": "x"}))
    component = KeenableFetchComponent(url="https://e.com", _session_id="t")
    component.fetch()
    assert _FakeClient.last["url"].endswith("/v1/fetch")
    assert _FakeClient.last["headers"]["X-API-Key"] == "secret"
