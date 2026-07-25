"""
Webhook Registry

Validates tenant-supplied webhook endpoints before they are persisted to the
notification routing table. A registration is only accepted once the endpoint
has been confirmed to be publicly reachable, which keeps unroutable or
internal-only URLs out of the dispatch path.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"https"}
_PREFLIGHT_TIMEOUT = 5
_MAX_PREVIEW_BYTES = 512


class WebhookValidationError(ValueError):
    """Raised when a webhook endpoint fails registration validation."""


@dataclass
class PreflightResult:
    reachable: bool
    status_code: int
    preview: str


def _resolve_addresses(host: str) -> list[str]:
    """Resolve every A/AAAA record for host so all candidates can be screened."""
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


def _is_non_public_address(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_endpoint(url: str) -> str:
    """
    Confirm that url is an https endpoint whose host resolves only to public,
    internet-routable addresses. Rejects any URL that could target internal
    infrastructure (loopback, RFC1918, link-local, reserved ranges).
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise WebhookValidationError("only https webhook URLs are allowed")

    host = parsed.hostname
    if not host:
        raise WebhookValidationError("webhook URL is missing a host")

    addresses = _resolve_addresses(host)
    if not addresses:
        raise WebhookValidationError("webhook host could not be resolved")

    for addr in addresses:
        if _is_non_public_address(addr):
            raise WebhookValidationError(
                "webhook host resolves to a non-public address"
            )

    return url


def preflight_webhook(url: str) -> PreflightResult:
    """
    Validate url and perform a lightweight reachability probe. The probe result
    is returned so the caller can surface a helpful confirmation to the tenant
    admin registering the endpoint.
    """
    assert_public_endpoint(url)

    resp = requests.get(url, timeout=_PREFLIGHT_TIMEOUT)
    log.info("Webhook preflight %s -> %s", url, resp.status_code)

    return PreflightResult(
        reachable=resp.ok,
        status_code=resp.status_code,
        preview=resp.text[:_MAX_PREVIEW_BYTES],
    )
