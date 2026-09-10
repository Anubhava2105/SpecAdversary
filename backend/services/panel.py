"""Adversarial panel registry: the single home for the critic roster.

The critic roster used to be smeared across four places: prompt briefs in
``services.graph``, the ``Critic`` enum in ``db.models``, the display list
in ``frontend/src/lib/critics.ts``, and the defaults in ``SpecInput.tsx``.
Every consumer now reads from here:

- backend: ``list_critics`` / ``is_known`` / ``filter_known`` (orchestrator
  fan-out validation), ``brief_for`` (prompt text), ``tier_for`` (model
  tier per critic), ``default_critics`` (session defaults);
- frontend: ``frontend/src/lib/critics.ts`` mirrors ``CRITIC_META`` titles
  (it cannot import this module; titles must match ``CONTEXT.md`` exactly).

Prompt bodies physically live in ``services.graph.BRIEFS`` next to the LLM
call sites and are reached only through ``brief_for`` (deferred import, so
there is no import cycle). Everything else about the roster — order,
defaults, display names, tiers, sort keys — lives here.

Domain terms follow ``CONTEXT.md``.
"""
from __future__ import annotations

from db.models import Critic

# Panel order. The index is the exhibit letter (A-H) and the sort key, so
# inserting a critic mid-panel renames later exhibits — append newcomers.
CRITIC_ORDER: tuple[Critic, ...] = (
    Critic.assumption,
    Critic.competitor,
    Critic.economics,
    Critic.feasibility,
    Critic.security,
    Critic.compliance,
    Critic.marketing,
    Critic.dissent,
)

# Sessions fan out to these critics unless the user picks others. Mirrored
# by ``SpecSession`` defaults, the session-route schema, and ``SpecInput``.
DEFAULT_CRITICS: tuple[str, ...] = ("assumption", "competitor", "economics", "feasibility")

# Display names match CONTEXT.md exactly; jobs match frontend critics.ts.
CRITIC_META: dict[Critic, dict[str, str]] = {
    Critic.assumption: {"title": "Assumption Hunter", "job": "Finds claims you treat as facts."},
    Critic.competitor: {"title": "Competitor Simulator", "job": "Attacks from a rival's point of view."},
    Critic.economics: {"title": "Economics Tester", "job": "Checks the numbers hold up."},
    Critic.feasibility: {"title": "Feasibility Auditor", "job": "Finds what breaks when you build it."},
    Critic.security: {"title": "Security Auditor", "job": "Looks for auth gaps, leaks, and insecure defaults."},
    Critic.compliance: {"title": "Compliance Critic", "job": "Flags regulatory exposure."},
    Critic.marketing: {"title": "Marketing Critic", "job": "Tests whether buyers will care."},
    Critic.dissent: {"title": "Dissenting Critic", "job": "Attacks the validated findings before synthesis."},
}


def list_critics() -> list[str]:
    """Every critic id in panel order."""
    return [c.value for c in CRITIC_ORDER]


def describe(critic: Critic) -> dict[str, str]:
    """Display metadata for one critic (title, job)."""
    return CRITIC_META[critic]


def default_critics() -> list[str]:
    """Fresh copy of the default fan-out."""
    return list(DEFAULT_CRITICS)


def is_known(name: str) -> bool:
    """True when a raw critic name is on the panel (drops stale clients)."""
    return any(name == c.value for c in CRITIC_ORDER)


def filter_known(names: list[str] | None) -> list[str]:
    """Keep panel members in panel order, dropping unknown names."""
    if not names:
        return []
    known = {c.value for c in CRITIC_ORDER}
    return [c.value for c in CRITIC_ORDER if c.value in set(names) and c.value in known]


def tier_for(critic: Critic) -> str:
    """Model tier for a critic's work: adversarial critique stays on main."""
    _ = critic
    return "main"


def sort_key(critic_name: str) -> int:
    """Panel-order index for sorting; unknown critics sort last."""
    for index, critic in enumerate(CRITIC_ORDER):
        if critic.value == critic_name:
            return index
    return len(CRITIC_ORDER)


def brief_for(critic: Critic) -> str:
    """Prompt brief for one critic — the only read path to the briefs."""
    from services.graph import BRIEFS

    return BRIEFS[critic]
