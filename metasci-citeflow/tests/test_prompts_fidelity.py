"""Guard the prompt YAMLs against drift from the original implementation.

The prompt text *is* the algorithm for all four LLM decision points — the seed
selector's "would a paper answering this query actually cite this one?" framing, the
relevance judge's quality-over-quantity instruction, and the decider's parameter bands
are all encoded in prose.  An innocuous-looking edit silently changes behaviour in a way
no other test would catch, so these files are compared byte-for-byte against AcaDeepR.

Skipped when the original checkout is not present.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

ACADEEPR = Path("/home/dell/Desktop/AcaDeepR")
PROMPT_DIR = Path(__file__).resolve().parents[1] / "src" / "metasci_citeflow" / "llm"

ORIGINALS = {
    "slot_based_prompts.yaml": ACADEEPR / "src/tools/query_analyzer/slot_based_prompts.yaml",
    "seed_selector_prompts_v2.yaml": ACADEEPR / "src/tools/paper_bigbang/seed_selector_prompts_v2.yaml",
    "citation_params_decider_prompts.yaml": ACADEEPR
    / "src/tools/paper_bigbang/citation_params_decider_prompts.yaml",
    "relevance_selector_prompts.yaml": ACADEEPR
    / "src/tools/paper_selector/relevance_selector_prompts.yaml",
}

EXPECTED_KEYS = {
    "slot_based_prompts.yaml": {
        "slot_keywords",
        "format_search_queries",
        "extract_discriminative_terms",
    },
    "seed_selector_prompts_v2.yaml": {"seed_selection"},
    "citation_params_decider_prompts.yaml": {
        "citation_params_decision",
        "seed_selection_params_decision",
    },
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("filename", sorted(ORIGINALS))
def test_prompt_matches_original(filename: str) -> None:
    original = ORIGINALS[filename]
    if not original.exists():
        pytest.skip(f"AcaDeepR checkout not available at {original}")

    ours = PROMPT_DIR / filename
    assert ours.exists(), f"missing prompt file {ours}"
    assert _digest(ours) == _digest(original), (
        f"{filename} has drifted from the AcaDeepR original. If the change is "
        "deliberate, update this test and record why in the commit message."
    )


@pytest.mark.parametrize("filename", sorted(EXPECTED_KEYS))
def test_prompt_exposes_expected_keys(filename: str) -> None:
    data = yaml.safe_load((PROMPT_DIR / filename).read_text(encoding="utf-8"))

    assert EXPECTED_KEYS[filename] <= set(data)
    for key in EXPECTED_KEYS[filename]:
        assert "system" in data[key] and "user" in data[key]


def test_seed_prompt_still_states_the_citation_likelihood_rule() -> None:
    data = yaml.safe_load(
        (PROMPT_DIR / "seed_selector_prompts_v2.yaml").read_text(encoding="utf-8")
    )
    system = data["seed_selection"]["system"].lower()

    # The core judgement the whole seed-selection step rests on.
    assert "likely cite" in system or "citation likelihood" in system
    assert "empty list" in system.lower() or "empty list" in data["seed_selection"]["user"].lower()


def test_decider_prompt_still_caps_min_citations_at_five() -> None:
    data = yaml.safe_load(
        (PROMPT_DIR / "citation_params_decider_prompts.yaml").read_text(encoding="utf-8")
    )
    user = data["citation_params_decision"]["user"]

    # Python clamps to [0, 5] as well; if the prompt band changes the clamp must follow.
    assert "never exceed 5" in user.lower()
