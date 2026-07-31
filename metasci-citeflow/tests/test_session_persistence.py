from __future__ import annotations

import json

import pytest

from metasci_citeflow.session import Session, SessionNotFoundError, clear_cache


def _paper(corpus_id: str, **overrides) -> dict:
    paper = {
        "corpus_id": corpus_id,
        "openalex_id": f"W{corpus_id}",
        "title": f"Paper {corpus_id}",
        "abstract": f"Abstract {corpus_id}",
        "year": 2020,
        "citation_count": 25,
    }
    paper.update(overrides)
    return paper


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def test_create_writes_both_artifacts(tmp_path) -> None:
    session = Session.create(query="test query", profile="acadeepr-run1", root=tmp_path)

    assert session.store_path.exists()
    assert session.ledger_path.exists()
    ledger = json.loads(session.ledger_path.read_text(encoding="utf-8"))
    assert ledger["query"] == "test query"
    assert ledger["profile"] == {"name": "acadeepr-run1", "overrides": {}}


def test_session_survives_a_process_boundary(tmp_path) -> None:
    session = Session.create(query="q", profile="acadeepr-run1", root=tmp_path)
    sid = session.session_id
    session.store.add_papers([_paper("1"), _paper("2")], source="search", keywords="alpha")
    session.set_analysis({"search_queries": ["alpha", "beta"], "discriminative_terms": {"x": 9}})
    session.record_round(
        round_num=0, phase="search", expanded_ids=["W1", "W2"], new_ids=["W1", "W2"]
    )
    session.add_judged(["W1"])
    session.save()

    # Simulate a fresh process: nothing left in memory, everything read back from disk.
    clear_cache()
    reloaded = Session.open(sid, root=tmp_path)

    assert reloaded.query == "q"
    assert reloaded.profile.name == "acadeepr-run1"
    assert len(reloaded.store.get_all_papers()) == 2
    assert reloaded.analysis["search_queries"] == ["alpha", "beta"]
    assert reloaded.judged_ids == ["W1"]
    assert reloaded.rounds_summary() == [
        {"round": 0, "phase": "search", "seeds": 0, "expanded": 2, "new": 2, "params": {}}
    ]


def test_reload_preserves_profile_overrides(tmp_path) -> None:
    session = Session.create(
        profile="acadeepr-run1", overrides={"refs.top_k_co_cited": 7}, root=tmp_path
    )
    sid = session.session_id
    clear_cache()

    reloaded = Session.open(sid, root=tmp_path)
    assert reloaded.profile.refs.top_k_co_cited == 7


def test_open_without_id_creates_new_session(tmp_path) -> None:
    a = Session.open(None, query="one", root=tmp_path)
    b = Session.open(None, query="two", root=tmp_path)
    assert a.session_id != b.session_id


def test_open_with_unknown_id_raises(tmp_path) -> None:
    with pytest.raises(SessionNotFoundError):
        Session.open("cf_missing", root=tmp_path)


def test_record_round_distinguishes_expanded_from_new(tmp_path) -> None:
    session = Session.create(root=tmp_path)
    session.record_round(
        round_num=1,
        phase="citations",
        seed_ids=["W1"],
        expanded_ids=["W1", "W2", "W3"],
        new_ids=["W3"],
        params={"year_start": 2018, "min_citations": 2},
    )

    row = session.get_round("last")
    assert row is not None
    # expanded_ids is what the fetch returned (the next round's candidate pool);
    # new_ids is only what the store had not seen before.
    assert row["expanded_ids"] == ["W1", "W2", "W3"]
    assert row["new_ids"] == ["W3"]
    assert row["params"]["year_start"] == 2018


def test_get_round_filters_by_phase(tmp_path) -> None:
    session = Session.create(root=tmp_path)
    session.record_round(round_num=0, phase="search", expanded_ids=["W1"])
    session.record_round(round_num=0, phase="refs", expanded_ids=["W2"])
    session.record_round(round_num=1, phase="citations", expanded_ids=["W3"])

    assert session.get_round("last")["phase"] == "citations"
    assert session.get_round("last", "refs")["expanded_ids"] == ["W2"]
    assert session.get_round(0, "search")["expanded_ids"] == ["W1"]
    assert session.get_round(9, "search") is None


def test_add_judged_deduplicates(tmp_path) -> None:
    session = Session.create(root=tmp_path)

    assert session.add_judged(["W1", "W2"]) == 2
    assert session.add_judged(["W2", "W3"]) == 1
    assert session.judged_ids == ["W1", "W2", "W3"]


def test_cocitation_payload_is_stored_outside_the_tool_result(tmp_path) -> None:
    session = Session.create(root=tmp_path)
    session.set_cocitation({"citing_map": {"W9": ["W1", "W2"]}, "source_ranks": {"W1": 0}})
    sid = session.session_id
    clear_cache()

    reloaded = Session.open(sid, root=tmp_path)
    assert reloaded.cocitation["citing_map"] == {"W9": ["W1", "W2"]}


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path) -> None:
    session = Session.create(root=tmp_path)
    session.store.add_papers([_paper("1")], source="search")
    session.save()

    assert list(session.dir.glob("*.tmp")) == []
    assert json.loads(session.store_path.read_text(encoding="utf-8"))["papers"]
