"""Tests for the dissenting critic node and the citation gate (graph.py).

The dissent pass is opt-in and post-moderation by design (ADR-0001); the
citation gate is deterministic so fabricated grounding never needs an LLM
round-trip to catch.
"""
import asyncio

from db.models import Critic, FindingsResponse
from services import graph


def _finding(cid, critic, sources=None):
    return {
        "id": cid,
        "critic": critic,
        "severity": "significant",
        "claim": "claim",
        "critique": "critique",
        "sources": sources or [],
    }


def test_dissent_noops_without_findings_to_attack():
    # Empty moderated list: returns before touching the stream writer, so no
    # LangGraph context is needed.
    assert asyncio.run(graph.dissent({})) == {}
    assert asyncio.run(graph.dissent({"moderated_findings": []})) == {}


def test_dissent_appends_new_findings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(graph, "get_stream_writer", lambda: lambda event: None)

    async def _fake_parse(client, instruction, payload, schema):
        assert "dissent" in instruction.lower()
        return FindingsResponse.model_validate({
            "findings": [{
                "critic": "dissent",
                "severity": "minor",
                "claim": "overstated moat",
                "critique": "weak",
            }]
        })

    monkeypatch.setattr(graph, "parse", _fake_parse)
    base = [_finding("F1", "assumption")]
    # No selection needed: dissent is automatic on every full run.
    state = {
        "raw_spec": "spec",
        "moderated_findings": base,
        "relevant_critics": ["assumption"],
    }
    result = asyncio.run(graph.dissent(state))
    assert len(result["moderated_findings"]) == 2
    assert result["moderated_findings"][0]["id"] == "F1"
    assert result["moderated_findings"][1]["critic"] == Critic.dissent


def test_fan_out_skips_dissent_silently():
    sends = graph.fan_out({"relevant_critics": ["assumption", "dissent"]})
    assert [s.node for s in sends] == ["assumption_hunter"]


def test_valid_source_url():
    assert graph._valid_source_url("https://example.com/a?b=c") is True
    assert graph._valid_source_url("http://x.io/") is True
    assert graph._valid_source_url("not a url") is False
    assert graph._valid_source_url("ftp://x.io/f") is False
    assert graph._valid_source_url("") is False
    assert graph._valid_source_url(None) is False
    assert graph._valid_source_url("https://") is False


def test_citation_gate_drops_ungrounded_grounded_findings():
    findings = [
        _finding("K1", "competitor", [{"url": "https://real.example.com/x", "excerpt": "q"}]),
        _finding("K2", "competitor", []),
        _finding("K3", "security", [{"url": "not a url"}]),
        _finding("K4", "assumption", []),
        _finding("K5", "dissent", []),
    ]
    kept = graph.enforce_citations(findings)
    assert [f["id"] for f in kept] == ["K1", "K4", "K5"]


def test_execute_run_persists_token_usage(monkeypatch):
    from sqlmodel import Session

    from db.models import AnalysisRun, SpecSession
    from services import pipeline_runner

    async def _noop_publish(run_id, sequence, event):
        return None

    monkeypatch.setattr(pipeline_runner, "publish_event", _noop_publish)

    async def _gen(_state):
        yield "updates", {"n": {"findings": []}}
        yield "updates", {"n": {"revised_spec": "revised"}}

    class _Graph:
        def astream(self, initial_state, stream_mode=None):
            return _gen(initial_state)

    monkeypatch.setattr(pipeline_runner, "spec_graph", _Graph())

    session = SpecSession(raw_spec="spec")
    run = AnalysisRun(session_id=session.id)
    with Session(pipeline_runner.engine) as db:
        db.add(session)
        db.add(run)
        db.commit()
        run_id = run.id

    asyncio.run(pipeline_runner.execute_run(run_id))

    with Session(pipeline_runner.engine) as db:
        stored = db.get(AnalysisRun, run_id)
        assert stored is not None and stored.status.value == "succeeded"
        assert stored.token_usage == 0


def test_citation_gate_preserves_sources_through_moderation():
    originals = [_finding("K1", "security", [{"url": "https://cve.example.com/1", "excerpt": "q"}])]
    candidate = [{"id": "K1", "sources": [{"url": "https://evil.example.com/fake"}]}]
    restored = graph.preserve_moderated_identity(candidate, originals)
    assert restored[0]["sources"] == [{"url": "https://cve.example.com/1", "excerpt": "q"}]
