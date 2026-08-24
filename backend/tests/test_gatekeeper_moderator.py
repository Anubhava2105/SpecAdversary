from models import ParsedSpec
from graph import (
    competitor_completion_message,
    compute_missing_context,
    deterministic_moderation,
    preserve_moderated_identity,
)
from main import restart_pipeline_args, session_snapshot_events
from models import SessionStatus, SpecSession
from uuid import uuid4
import asyncio
from types import SimpleNamespace


def finding(identifier: str, **overrides):
    value = {
        "id": identifier, "critic": "assumption", "severity": "significant",
        "claim": "Users will pay", "critique": "Payment is unvalidated",
        "suggested_fix": "Interview users", "thread": [{"role": "user", "content": "Why?"}], "dismissed": False,
    }
    value.update(overrides)
    return value


def test_missing_context_is_deterministic_for_sparse_spec():
    parsed = ParsedSpec(problem_statement="Build an app for dogs")
    assert compute_missing_context(parsed, ["target_users"]) == [
        "target_users", "core_solution", "technical_architecture", "business_model", "risks"
    ]


def test_complete_spec_has_no_missing_context():
    parsed = ParsedSpec(
        problem_statement="p", target_users="u", core_solution="s",
        technical_architecture="t", business_model="b", risks="r",
    )
    assert compute_missing_context(parsed) == []


def test_moderated_findings_are_a_separate_replacement_value():
    raw = [finding("one"), finding("two", claim="Architecture", critique="Queue lacks retries")]
    moderated = deterministic_moderation(raw)
    assert moderated is not raw
    assert len(moderated) == 2


def test_moderation_preserves_ids_threads_and_filters_dismissed():
    kept = finding("keep")
    dismissed = finding("dismissed", dismissed=True)
    candidate = [finding("keep", critique="Consolidated critique", thread=[]), finding("invented")]
    result = preserve_moderated_identity(candidate, [kept, dismissed])
    assert result == [{**candidate[0], "id": "keep", "thread": kept["thread"], "dismissed": False}]
    assert deterministic_moderation([kept, dismissed]) == [kept]


def test_late_snapshot_replays_gatekeeper_context():
    row = SpecSession(raw_spec="spec", missing_context=["technical_architecture"], status=SessionStatus.critiquing)
    assert list(session_snapshot_events(row))[1] == {"type": "gatekeeper", "missing_context": ["technical_architecture"]}


def test_restart_uses_persisted_selected_critics():
    identifier = uuid4()
    row = SpecSession(id=identifier, raw_spec="spec", selected_critics=["security", "marketing"])
    assert restart_pipeline_args(row) == (identifier, "spec", ["security", "marketing"])


def test_competitor_completion_retries_when_provider_returns_no_choices(monkeypatch):
    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(choices=None)
            return SimpleNamespace(choices=[SimpleNamespace(message="usable message")])

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    async def no_sleep(_):
        return None

    monkeypatch.setattr("graph.LLM_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("llm_gateway.asyncio.sleep", no_sleep)

    message = asyncio.run(competitor_completion_message(client, [{"role": "user", "content": "test"}]))

    assert message == "usable message"
    assert completions.calls == 2
