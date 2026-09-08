import asyncio
from types import SimpleNamespace
from uuid import uuid4

from db.models import ParsedSpec, SessionStatus, SpecSession
from main import restart_pipeline_args, session_snapshot_events
from services.graph import (
    competitor_completion_message,
    compute_missing_context,
    deterministic_moderation,
    preserve_moderated_identity,
)


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


def test_explicit_empty_report_does_not_fall_back_to_parser():
    # An explicit [] means "nothing missing" — only empty canonical fields apply.
    parsed = ParsedSpec(
        problem_statement="p", target_users="u", core_solution="s",
        technical_architecture="t", business_model="b", risks="r",
        missing_context=["risks"],
    )
    assert compute_missing_context(parsed, []) == []


def test_moderation_tolerates_unknown_severity_and_dedupes():
    rows = [
        finding("bad-sev", severity="catastrophic"),
        finding("dup-a", claim="Same", critique="Same"),
        finding("dup-b", claim="same ", critique=" same"),
    ]
    moderated = deterministic_moderation(rows)
    assert {m["id"] for m in moderated} == {"bad-sev", "dup-a"}  # no KeyError, one dupe dropped


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

    monkeypatch.setattr("services.graph.LLM_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("services.llm_gateway.asyncio.sleep", no_sleep)

    message = asyncio.run(competitor_completion_message(client, [{"role": "user", "content": "test"}]))

    assert message == "usable message"
    assert completions.calls == 2
