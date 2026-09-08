"""Tests for security response headers."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_csp_present_and_blocks_everything():
    r = client.get("/sessions/00000000-0000-0000-0000-000000000000")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_headers_present_on_success_responses():
    r = client.get("/healthz")
    assert r.status_code in (200, 503)  # redis may be absent; headers apply either way
    assert "default-src 'none'" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


def test_obsolete_xss_header_removed():
    r = client.get("/sessions/00000000-0000-0000-0000-000000000000")
    assert "x-xss-protection" not in r.headers


def test_hsts_absent_in_dev():
    r = client.get("/sessions/00000000-0000-0000-0000-000000000000")
    assert "strict-transport-security" not in r.headers
