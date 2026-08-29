"""Tests for networking.probing HTTPS probing, using a mocked connection
factory (no real network access) and for the ICMP/HTTPS target parsers."""

from __future__ import annotations

import pytest

from multilink_manager.networking.probing import (
    parse_https_targets,
    parse_icmp_targets,
    probe_https_once,
)


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _FakeConnection:
    """Records calls; returns a scripted status (or raises a scripted
    exception) per call, to emulate exactly the subset of
    http.client.HTTPConnection that probe_https_once() uses."""

    def __init__(self, status=204, exc=None):
        self.status = status
        self.exc = exc
        self.closed = False
        self.requested = False

    def request(self, method, path, headers=None):
        self.requested = True

    def getresponse(self):
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.status)

    def close(self):
        self.closed = True


def _factory_returning(status):
    def factory(scheme, host, port, timeout_s, source_ip):
        return _FakeConnection(status=status)
    return factory


def _factory_raising(exc):
    def factory(scheme, host, port, timeout_s, source_ip):
        conn = _FakeConnection(exc=exc)
        return conn
    return factory


def test_https_probe_success_204_is_reachable_with_latency():
    result = probe_https_once(
        "192.168.1.10", "https://www.gstatic.com/generate_204", "eth0",
        count=2, timeout_s=1.0, connection_factory=_factory_returning(204),
    )
    assert result.target_kind == "https"
    assert result.target_id == "https:https://www.gstatic.com/generate_204"
    assert result.reachable is True
    assert result.http_status == 204
    assert result.rtt_ms is not None
    assert result.loss_pct == 0.0
    assert result.error is None


def test_https_probe_error_status_is_reachable_transport_success():
    """A 4xx/5xx proves the source-bound TCP/TLS/HTTP round trip worked.
    The endpoint error remains visible without becoming fake packet loss."""
    result = probe_https_once(
        "192.168.1.10", "https://example.invalid/", "eth0",
        count=2, timeout_s=1.0, connection_factory=_factory_returning(503),
    )
    assert result.reachable is True
    assert result.http_status == 503
    assert result.rtt_ms is not None
    assert result.loss_pct == 0.0
    assert result.error is not None


def test_https_probe_connection_failure_is_unreachable():
    result = probe_https_once(
        "192.168.1.10", "https://example.invalid/", "eth0",
        count=2, timeout_s=1.0, connection_factory=_factory_raising(OSError("no route")),
    )
    assert result.reachable is False
    assert result.http_status is None
    assert result.rtt_ms is None
    assert result.loss_pct == 100.0
    assert result.error is not None


def test_https_probe_malformed_url_has_no_hostname():
    result = probe_https_once(
        "192.168.1.10", "not-a-valid-url", "eth0",
        connection_factory=_factory_returning(204),
    )
    assert result.reachable is None
    assert result.error is not None


def test_parse_icmp_targets_dedupes_and_strips():
    targets = parse_icmp_targets(" 1.1.1.1, 8.8.8.8 ,1.1.1.1")
    assert targets == ["1.1.1.1", "8.8.8.8"]


def test_parse_icmp_targets_empty_raises():
    with pytest.raises(ValueError):
        parse_icmp_targets("   ")


def test_parse_https_targets_valid_urls():
    targets = parse_https_targets("https://a.example/x, http://b.example/y")
    assert targets == ["https://a.example/x", "http://b.example/y"]


def test_parse_https_targets_empty_is_allowed():
    assert parse_https_targets("") == []


def test_parse_https_targets_invalid_scheme_raises():
    with pytest.raises(ValueError):
        parse_https_targets("ftp://a.example/x")


def test_parse_https_targets_no_hostname_raises():
    with pytest.raises(ValueError):
        parse_https_targets("https://")
