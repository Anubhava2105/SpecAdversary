"""Tests for the /healthz dependency-readiness endpoint."""
from fastapi.testclient import TestClient

import main


class FakeRedis:
    async def ping(self):
        return True


def test_healthz_ok_when_dependencies_answer(monkeypatch):
    monkeypatch.setattr(main, "redis_client", lambda: FakeRedis())
    client = TestClient(main.app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"


def test_healthz_reports_redis_outage(monkeypatch):
    class DeadRedis:
        async def ping(self):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(main, "redis_client", lambda: DeadRedis())
    client = TestClient(main.app)
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["db"] == "ok"
    assert resp.json()["redis"].startswith("error:")


def test_healthz_reports_database_outage(monkeypatch):
    class BoomSession:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise RuntimeError("db unreachable")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(main, "Session", BoomSession)
    client = TestClient(main.app)
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["db"].startswith("error:")
