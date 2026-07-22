"""
SSRF guard — validates a user-supplied webhook/callback URL before the
backend makes an outbound request to it.

Blocks: non-http(s) schemes, loopback/private/link-local/reserved IP
ranges (including the 169.254.169.254 cloud-metadata endpoint), and any
hostname that resolves to one of those ranges. This is a request-time
check, not a network-layer control — it closes the direct "paste an
internal URL" attack but does not defend against DNS rebinding (a
hostname that resolves safely at validation time and to a private IP at
connection time). Full rebinding protection would require pinning the
validated IP for the actual httpx connection; out of scope for this pass.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(ValueError):
    """Raised when a URL fails the public-reachability check."""


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — fail closed
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or
        ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    """Raise UnsafeUrlError if `url` is not a safe, public http(s) target."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no hostname")

    # Literal IP in the URL — check directly, no DNS involved.
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False

    if is_literal_ip:
        if _is_blocked_ip(host):
            raise UnsafeUrlError(f"URL host resolves to a non-public address: {host!r}")
        return

    # Hostname — resolve and check every address it maps to (a name can
    # have multiple A/AAAA records; all must be public).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host {host!r}: {exc}") from exc
    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise UnsafeUrlError(f"URL host {host!r} resolves to a non-public address: {ip_str!r}")
