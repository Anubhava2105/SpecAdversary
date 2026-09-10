"""Tests for the panel registry: the single home of the critic roster."""
from db.models import Critic
from routes.session_routes import CreateSession
from services import panel


def test_roster_covers_every_critic_enum_member():
    assert set(panel.list_critics()) == {c.value for c in Critic}


def test_roster_order_is_stable_and_unique():
    roster = panel.list_critics()
    assert len(roster) == len(set(roster)) == 7
    assert roster.index("assumption") < roster.index("marketing")


def test_describe_matches_context_vocabulary():
    assert panel.describe(Critic.assumption)["title"] == "Assumption Hunter"
    assert panel.describe(Critic.marketing)["title"] == "Marketing Critic"


def test_tier_mapping_keeps_critique_on_main():
    for critic in Critic:
        assert panel.tier_for(critic) == "main"


def test_unknown_names_drop_but_empty_falls_back():
    assert panel.filter_known(["assumption", "tarot"]) == ["assumption"]
    assert panel.filter_known([]) == []
    assert panel.filter_known(None) == []


def test_consumer_defaults_derive_from_registry():
    assert panel.default_critics() == list(panel.DEFAULT_CRITICS)
    assert [c.value for c in CreateSession.model_validate({"raw_spec": "x"}).selected_critics] == panel.default_critics()


def test_brief_for_reaches_every_critic():
    for critic in Critic:
        assert len(panel.brief_for(critic)) > 100
