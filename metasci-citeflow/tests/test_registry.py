from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from metasci_citeflow import registry
from metasci_citeflow.session import clear_cache


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def test_every_tool_has_a_validating_model_and_serialisable_card() -> None:
    assert registry.list_tools(), "registry must expose at least one tool"
    for name in registry.list_tools():
        assert name.startswith("cf.")
        card = registry.describe_tool(name)
        assert card["description"]
        assert card["examples"]
        assert "properties" in card["inputs"] or card["inputs"].get("type") == "object"


def test_unknown_tool_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        asyncio.run(registry.run_tool("cf.nope", {}))


def test_bad_payload_raises_validation_error_not_typeerror() -> None:
    # The previous ds.* factory forwarded raw payloads, so a bad field surfaced as a
    # TypeError from inside the algorithm instead of a named validation failure.
    with pytest.raises(ValidationError):
        asyncio.run(registry.run_tool("cf.session.info", {}))

    with pytest.raises(ValidationError):
        asyncio.run(registry.run_tool("cf.profiles.show", {"name": "x", "bogus": 1}))


def test_session_open_returns_metasci_result(tmp_path) -> None:
    result = asyncio.run(
        registry.run_tool(
            "cf.session.open",
            {"query": "factual consistency metrics", "session_dir": str(tmp_path)},
        )
    )

    assert result.command == "cf.session.open"
    assert result.data["query"] == "factual consistency metrics"
    assert result.data["profile"] == "default"
    assert result.data["stats"]["total_papers"] == 0
    assert result.input["query"] == "factual consistency metrics"


def test_session_open_then_info_round_trips_through_disk(tmp_path) -> None:
    opened = asyncio.run(
        registry.run_tool(
            "cf.session.open",
            {"query": "q", "profile": "acadeepr-run1", "session_dir": str(tmp_path)},
        )
    )
    sid = opened.data["session_id"]

    clear_cache()
    info = asyncio.run(
        registry.run_tool("cf.session.info", {"session_id": sid, "session_dir": str(tmp_path)})
    )

    assert info.data["session_id"] == sid
    assert info.data["profile"] == "acadeepr-run1"
    assert info.data["rounds_summary"] == []


def test_session_open_reattaches_to_existing_session(tmp_path) -> None:
    first = asyncio.run(
        registry.run_tool("cf.session.open", {"query": "q", "session_dir": str(tmp_path)})
    )
    sid = first.data["session_id"]

    again = asyncio.run(
        registry.run_tool(
            "cf.session.open", {"session_id": sid, "session_dir": str(tmp_path)}
        )
    )
    assert again.data["session_id"] == sid


def test_profiles_tools_expose_presets() -> None:
    listed = asyncio.run(registry.run_tool("cf.profiles.list", {}))
    names = {entry["name"] for entry in listed.data["profiles"]}
    assert "acadeepr-run1" in names

    shown = asyncio.run(registry.run_tool("cf.profiles.show", {"name": "acadeepr-run1"}))
    profile = shown.data["profile"]
    assert profile["refs"]["top_k_co_cited"] == 20
    assert profile["seed_llm"]["enforce_limits"] is True


def test_profiles_show_rejects_unknown_profile() -> None:
    with pytest.raises(KeyError):
        asyncio.run(registry.run_tool("cf.profiles.show", {"name": "nope"}))


def test_store_stats_reports_coverage_signals(tmp_path) -> None:
    opened = asyncio.run(
        registry.run_tool("cf.session.open", {"query": "q", "session_dir": str(tmp_path)})
    )
    sid = opened.data["session_id"]

    stats = asyncio.run(
        registry.run_tool("cf.store.stats", {"session_id": sid, "session_dir": str(tmp_path)})
    )

    for signal in (
        "openalex_coverage",
        "abstract_coverage",
        "embedding_sim_coverage",
        "keyword_score_coverage",
        "seeds",
        "judged",
        "rounds_summary",
    ):
        assert signal in stats.data


def test_rounds_tools_read_the_ledger(tmp_path) -> None:
    opened = asyncio.run(
        registry.run_tool("cf.session.open", {"query": "q", "session_dir": str(tmp_path)})
    )
    sid = opened.data["session_id"]

    from metasci_citeflow.session import Session

    session = Session.open(sid, root=tmp_path)
    session.record_round(round_num=0, phase="search", expanded_ids=["W1", "W2"], new_ids=["W1"])

    listed = asyncio.run(
        registry.run_tool("cf.rounds.list", {"session_id": sid, "session_dir": str(tmp_path)})
    )
    assert listed.data["rounds"][0]["expanded"] == 2

    got = asyncio.run(
        registry.run_tool(
            "cf.rounds.get",
            {"session_id": sid, "round": "last", "session_dir": str(tmp_path)},
        )
    )
    assert got.data["found"] is True
    assert got.data["expanded_ids"] == ["W1", "W2"]


def test_rounds_get_reports_missing_round(tmp_path) -> None:
    opened = asyncio.run(
        registry.run_tool("cf.session.open", {"query": "q", "session_dir": str(tmp_path)})
    )
    sid = opened.data["session_id"]

    got = asyncio.run(
        registry.run_tool(
            "cf.rounds.get", {"session_id": sid, "round": 3, "session_dir": str(tmp_path)}
        )
    )
    assert got.data["found"] is False
