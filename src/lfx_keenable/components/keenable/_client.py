"""Shared transport for the Keenable Langflow components.

One place for the parts of the Keenable contract that both the search and the
fetch component need: keyed-vs-keyless endpoint selection, the attribution
headers, HTTPS-only base-URL resolution, the client-side SSRF guard, and turning
a non-2xx response into a single, readable error string. The components import
these helpers; this module itself defines no ``Component`` subclass, so the
bundle loader ignores it for discovery.
"""

from __future__ import annotations

import ipaddress
import os
from importlib import metadata
from typing import Any
from urllib.parse import urlsplit

import httpx

try:
    _VERSION = metadata.version("lfx-keenable")
except metadata.PackageNotFoundError:  # pragma: no cover - editable/source checkout
    _VERSION = "unknown"

# Tagged User-Agent so Keenable can attribute traffic from this integration.
_USER_AGENT = f"keenable-langflow/{_VERSION}"

# The load-bearing attribution signal: the Keenable backend segments traffic by
# this header (adoption dashboards). The User-Agent above is a secondary tag.
_ATTRIBUTION_TITLE = "Langflow"

# Endpoint comes from the environment, never from a component/LLM-settable input
# (an arbitrary base URL would be an SSRF foothold).
_DEFAULT_BASE_URL = "https://api.keenable.ai"
_BASE_URL_ENV = "KEENABLE_API_URL"


class KeenableError(Exception):
    """A Keenable transport/API error, carrying a message safe to show a user."""


def resolve_base_url() -> str:
    """Resolve the API base URL from ``KEENABLE_API_URL`` and enforce HTTPS."""
    base = (os.environ.get(_BASE_URL_ENV) or _DEFAULT_BASE_URL).rstrip("/")
    parsed = urlsplit(base)
    # A usable absolute URL needs a host; bail out clearly on e.g. "https://"
    # rather than letting a malformed base produce a broken request URL later.
    if parsed.hostname:
        if parsed.scheme == "https":
            return base
        # Permit plain http only for local development against a loopback host.
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return base
    msg = f"{_BASE_URL_ENV} must be an https:// URL with a host, got {base!r}"
    raise KeenableError(msg)


def reject_private_fetch_target(url: str) -> None:
    """Refuse obviously private/internal fetch targets before sending (SSRF).

    The backend enforces this server-side too, but a client-side guard avoids
    leaking an internal hostname in a request and is required by our integration
    contract. Hostnames that are not IP literals are passed through — the
    backend's SSRF guard is the backstop for those.
    """
    host = (urlsplit(url).hostname or "").strip().lower()
    if not host:
        msg = f"Refusing to fetch a URL with no host: {url!r}"
        raise KeenableError(msg)
    if host in {"localhost", "metadata.google.internal"}:
        msg = f"Refusing to fetch a private/internal host: {host!r}"
        raise KeenableError(msg)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        msg = f"Refusing to fetch a private/internal address: {host!r}"
        raise KeenableError(msg)


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"User-Agent": _USER_AGENT, "X-Keenable-Title": _ATTRIBUTION_TITLE}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _select_path(api_key: str | None, public_path: str, keyed_path: str) -> str:
    return keyed_path if api_key else public_path


def _raise_for_status(response: httpx.Response) -> None:
    """Map a non-2xx Keenable response to a readable :class:`KeenableError`."""
    if response.is_success:
        return
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("error") or body.get("detail") or "")
    except ValueError:
        detail = (response.text or "").strip()
    label = {
        401: "Keenable authentication failed (401)",
        402: "Keenable: insufficient credits (402)",
        429: "Keenable rate limit exceeded (429)",
    }.get(response.status_code, f"Keenable API error ({response.status_code})")
    raise KeenableError(f"{label}: {detail}" if detail else label)


def _decode(response: httpx.Response) -> dict[str, Any]:
    _raise_for_status(response)
    try:
        data = response.json()
    except ValueError as e:
        snippet = (response.text or "")[:200]
        msg = f"Keenable API returned a non-JSON response: {snippet!r}"
        raise KeenableError(msg) from e
    if not isinstance(data, dict):
        msg = f"Unexpected response from the Keenable API: {data!r}"
        raise KeenableError(msg)
    return data


def keenable_post(
    public_path: str,
    keyed_path: str,
    payload: dict[str, Any],
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    """POST ``payload`` to the keyed or keyless endpoint and return the body."""
    path = _select_path(api_key, public_path, keyed_path)
    url = f"{resolve_base_url()}{path}"
    headers = {**_headers(api_key), "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as e:
        msg = f"Could not reach the Keenable API: {e!r}"
        raise KeenableError(msg) from e
    return _decode(response)


def keenable_get(
    public_path: str,
    keyed_path: str,
    params: dict[str, Any],
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    """GET the keyed or keyless endpoint with query ``params``; return the body."""
    path = _select_path(api_key, public_path, keyed_path)
    url = f"{resolve_base_url()}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, params=params, headers=_headers(api_key))
    except httpx.RequestError as e:
        msg = f"Could not reach the Keenable API: {e!r}"
        raise KeenableError(msg) from e
    return _decode(response)


def resolve_api_key(raw: Any) -> str | None:
    """The non-blank component key, else ``KEENABLE_API_KEY``, else ``None``.

    Langflow resolves a ``SecretStrInput`` to a plain string at runtime; an
    empty/whitespace value means "no key", in which case we fall back to the
    environment and finally to the keyless public endpoints.
    """
    key = raw.strip() if isinstance(raw, str) else ""
    if not key:
        key = (os.environ.get("KEENABLE_API_KEY") or "").strip()
    return key or None
