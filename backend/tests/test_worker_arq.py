"""Tests for the ARQ worker wiring (worker.py) and dispatch seam (deps)."""
import asyncio
import importlib
from uuid import uuid4

import worker
from core import broker, deps
from core.deps import dispatch_run as _real_dispatch


def test_job_function_registered_under_stable_name():
    names = [fn.__name__ for fn in worker.WorkerSettings.functions]
    assert "run_analysis_job" in names


def test_queue_name_matches_broker():
    assert worker.WorkerSettings.queue_name == broker.ARQ_QUEUE_NAME


def test_reap_cron_registered():
    assert len(worker.WorkerSettings.cron_jobs) == 1


def test_default_concurrency_is_small():
    # Sync SQLModel sessions inside async jobs block the loop: the default
    # must stay small; scale with replicas, not in-process jobs.
    assert worker.WorkerSettings.max_jobs <= 4


def test_concurrency_honors_env(monkeypatch):
    monkeypatch.setenv("WORKER_CONCURRENCY", "3")
    reloaded = importlib.reload(worker)
    try:
        assert reloaded.WorkerSettings.max_jobs == 3
    finally:
        importlib.reload(worker)


def test_results_not_kept_in_redis():
    assert worker.WorkerSettings.keep_result == 0


def test_job_runs_execute_run_and_tracks_in_flight(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "execute_run", lambda rid: seen.append(rid) or asyncio.sleep(0))
    run_id = uuid4()
    asyncio.run(worker.run_analysis_job({}, str(run_id)))
    assert seen == [run_id]
    assert worker._in_flight == 0


def test_job_resets_in_flight_on_failure(monkeypatch):
    async def _boom(rid):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(worker, "execute_run", _boom)
    with __import__("pytest").raises(RuntimeError):
        asyncio.run(worker.run_analysis_job({}, str(uuid4())))
    assert worker._in_flight == 0


class _FakePool:
    """Minimal stand-in for arq's pool: records enqueued jobs and closes."""

    def __init__(self):
        self.enqueued = []
        self.closed = False

    async def enqueue_job(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return None

    async def close(self):
        self.closed = True


def test_dispatch_enqueues_arq_job(monkeypatch):
    # NOTE: conftest stubs deps.dispatch_run for every test; call the
    # import-time reference to exercise the real seam.
    pool = _FakePool()

    async def _create(*args, **kwargs):
        return pool

    monkeypatch.setattr(deps, "create_pool", _create)
    run_id = uuid4()
    asyncio.run(_real_dispatch(run_id))
    assert pool.enqueued == [("run_analysis_job", (str(run_id),), {"_job_id": str(run_id)})]
    assert pool.closed is True


def test_dispatch_inline_bypasses_redis(monkeypatch):
    monkeypatch.setenv("INLINE_WORKER", "true")
    calls = []
    monkeypatch.setattr(deps, "execute_run", lambda rid: calls.append(rid) or asyncio.sleep(0))

    async def _run():
        await _real_dispatch(uuid4())
        for task in list(deps.inline_tasks):
            await task

    asyncio.run(_run())
    assert len(calls) == 1
