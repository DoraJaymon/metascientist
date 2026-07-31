from __future__ import annotations

import pytest

from metasci_citeflow.profiles import (
    PASSTHROUGH,
    PROFILES,
    CiteFlowProfile,
    UnknownOverrideError,
    UnknownProfileError,
    list_profiles,
    resolve,
    weights_for,
)


def test_every_preset_instantiates() -> None:
    assert set(PROFILES) == {"acadeepr-run1", "acadeepr-run3", "semantic12", "default"}
    for name, profile in PROFILES.items():
        assert isinstance(profile, CiteFlowProfile)
        assert profile.description, f"{name} needs provenance in its description"
        assert profile.to_dict()["init_search"]["limit"] > 0


def test_default_matches_run1_parameters() -> None:
    default, run1 = PROFILES["default"], PROFILES["acadeepr-run1"]
    assert default.refs == run1.refs
    assert default.filter_params_cite == run1.filter_params_cite
    assert default.mid_sort_weights == run1.mid_sort_weights


def test_run1_pins_the_batch_evaluation_values() -> None:
    p = resolve("acadeepr-run1")
    assert p.init_search.year == (2015, 2023)
    assert p.init_search.limit == 50
    assert p.refs.top_k_co_cited == 20
    assert p.refs.max_citing_papers == 12
    assert p.refs.max_per_seed == 100
    assert p.refs.co_seed_selection.min_total_citations == 600
    assert p.refs.co_seed_selection.max_citation_exclude == 5000
    assert p.filter_params_cite.max_citations == 7000
    assert p.filter_params.max_citations == 8000
    assert p.seed_llm.enforce_limits is True
    assert p.final_sort_weights_1["relevance_mode"] == "multiplicative"
    assert p.final_sort_weights_2["embedding_scale"] == 1.2


def test_run3_is_the_skip_refs_ablation() -> None:
    p = resolve("acadeepr-run3")
    # run_my_3 set start_from_phase1 + from_phase2, which bypassed refs expansion.
    assert p.skip_refs_expansion is True
    assert p.seed_llm.enforce_limits is False
    assert p.filter_params_cite.max_citations == 7500
    assert p.filter_params_cite.year_range == (2015, 2023)


def test_mid_sort_weights_are_never_a_silent_empty_dict() -> None:
    for name, profile in PROFILES.items():
        weights = profile.mid_sort_weights
        if weights == PASSTHROUGH:
            continue
        assert weights, (
            f"{name} has empty mid_sort_weights; use PASSTHROUGH to declare an "
            "intentionally unweighted mid-loop ranking"
        )


def test_passthrough_resolves_to_empty_weights() -> None:
    assert weights_for(PASSTHROUGH) == {}
    assert weights_for({"relevance": 0.8}) == {"relevance": 0.8}


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_dotted_override_replaces_one_leaf_and_leaves_siblings() -> None:
    base = resolve("acadeepr-run1")
    tweaked = resolve("acadeepr-run1", **{"refs.top_k_co_cited": 5})

    assert tweaked.refs.top_k_co_cited == 5
    assert tweaked.refs.max_citing_papers == base.refs.max_citing_papers
    assert tweaked.refs.co_seed_selection == base.refs.co_seed_selection
    assert tweaked.filter_params == base.filter_params
    # the preset itself must not be mutated
    assert PROFILES["acadeepr-run1"].refs.top_k_co_cited == 20


def test_deeply_nested_override() -> None:
    tweaked = resolve("acadeepr-run1", **{"refs.co_seed_selection.min_seeds": 4})

    assert tweaked.refs.co_seed_selection.min_seeds == 4
    assert tweaked.refs.co_seed_selection.min_total_citations == 600
    assert tweaked.refs.top_k_co_cited == 20


def test_multiple_overrides_apply_together() -> None:
    tweaked = resolve(
        "acadeepr-run1",
        **{"seed_llm.enforce_limits": False, "loop.rounds": 5, "year_end": 2024},
    )

    assert tweaked.seed_llm.enforce_limits is False
    assert tweaked.loop.rounds == 5
    assert tweaked.year_end == 2024


def test_unknown_profile_raises() -> None:
    with pytest.raises(UnknownProfileError):
        resolve("does-not-exist")


def test_unknown_override_key_raises() -> None:
    with pytest.raises(UnknownOverrideError):
        resolve("acadeepr-run1", **{"refs.nope": 1})

    with pytest.raises(UnknownOverrideError):
        resolve("acadeepr-run1", **{"not_a_section.field": 1})


def test_override_into_non_dataclass_raises() -> None:
    with pytest.raises(UnknownOverrideError):
        resolve("acadeepr-run1", **{"year_end.nested": 1})


def test_resolve_accepts_a_profile_instance() -> None:
    base = resolve("semantic12")
    assert resolve(base).name == "semantic12"


def test_list_profiles_reports_names_and_descriptions() -> None:
    listed = list_profiles()
    assert {entry["name"] for entry in listed} == set(PROFILES)
    assert all(entry["description"] for entry in listed)
