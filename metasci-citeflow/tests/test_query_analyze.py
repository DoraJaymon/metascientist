from __future__ import annotations

import asyncio

import pytest
import yaml

from metasci_citeflow import registry
from metasci_citeflow.deps import CiteFlowDeps
from metasci_citeflow.llm.parsers import (
    parse_discriminative_terms,
    parse_search_queries,
    parse_slot_keywords,
    strip_code_fence,
)
from metasci_citeflow.llm.query_analyzer import (
    SlotBasedQueryAnalyzer,
    analysis_from_config,
    rerank_query_text,
)
from metasci_citeflow.session import Session, clear_cache
from fakes import FakeLLM

SLOT_REPLY = (
    "reasoning: The task is developing evaluation metrics for factual alignment.\n"
    'core_keywords: [("alignment", "factual"), ("summarization", "machine-generated"), ("metric",)]'
)
QUERIES_REPLY = (
    "reasoning: research_task first, then narrower combinations\n"
    "Factual Alignment Summarization\n"
    "factual alignment metric\n"
    "factual alignment\n"
)
TERMS_REPLY = (
    "reasoning: rare terms score high\n"
    "terms:\n"
    "  factuality: 9\n"
    "  faithfulness: 9\n"
    "  summarization: 2\n"
)


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_cache()
    yield
    clear_cache()


def _analyzer(**script):
    llm = FakeLLM(script)
    return llm, SlotBasedQueryAnalyzer(llm, model="test-model")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_slot_keywords_normalises_tuples() -> None:
    parsed = parse_slot_keywords(SLOT_REPLY)

    assert parsed["core_keywords"] == [
        ("alignment", "factual"),
        ("summarization", "machine-generated"),
        ("metric",),
    ]
    assert parsed["reasoning"].startswith("The task is")


def test_parse_slot_keywords_promotes_bare_strings_and_drops_empties() -> None:
    parsed = parse_slot_keywords('core_keywords: ["metric", ("task", ""), ("", "")]')

    assert parsed["core_keywords"] == [("metric",), ("task",)]


def test_parse_slot_keywords_records_error_without_raising() -> None:
    parsed = parse_slot_keywords("core_keywords: [(unclosed")

    assert parsed["core_keywords"] == []
    assert "_parse_error" in parsed


def test_parse_slot_keywords_strips_code_fence() -> None:
    fenced = "```python\ncore_keywords: [(\"metric\",)]\n```"
    assert parse_slot_keywords(fenced)["core_keywords"] == [("metric",)]
    assert strip_code_fence("no fence") == "no fence"


def test_parse_search_queries_lowercases_and_caps_at_five() -> None:
    reply = "reasoning: r\n" + "\n".join(f"Query Number {i}" for i in range(8))
    parsed = parse_search_queries(reply)

    assert len(parsed["queries"]) == 5
    assert parsed["queries"][0] == "query number 0"


def test_parse_search_queries_skips_comments_and_rules() -> None:
    parsed = parse_search_queries("reasoning: r\n# a comment\n---\nreal query")
    assert parsed["queries"] == ["real query"]


def test_parse_discriminative_terms_via_yaml_and_fallback() -> None:
    assert parse_discriminative_terms(TERMS_REPLY)["terms"] == {
        "factuality": 9,
        "faithfulness": 9,
        "summarization": 2,
    }

    # Non-YAML shape still parses, and non-integer scores are skipped.
    messy = "reasoning: r\nterms:\n  alpha: 7\n  beta: high\n"
    assert parse_discriminative_terms(messy)["terms"] == {"alpha": 7}


# ---------------------------------------------------------------------------
# Rerank query construction
# ---------------------------------------------------------------------------


def test_rerank_query_reverses_each_tuple() -> None:
    # ("alignment", "factual") reads as "factual alignment" - modifier before head.
    text = rerank_query_text([("alignment", "factual"), ("metric",)])
    assert text == "factual alignment metric"


def test_rerank_query_handles_empty_input() -> None:
    assert rerank_query_text([]) == ""
    assert rerank_query_text([()]) == ""


# ---------------------------------------------------------------------------
# Three-turn conversation
# ---------------------------------------------------------------------------


def test_analyze_all_runs_three_turns_in_order() -> None:
    llm, analyzer = _analyzer(
        slot_keywords=[SLOT_REPLY],
        format_search_queries=[QUERIES_REPLY],
        extract_discriminative_terms=[TERMS_REPLY],
    )

    analysis = asyncio.run(analyzer.analyze_all("Have any new metrics been developed?"))

    assert [call["prompt_key"] for call in llm.calls] == [
        "slot_keywords",
        "format_search_queries",
        "extract_discriminative_terms",
    ]
    assert analysis["structured_keywords"] == [
        ["alignment", "factual"],
        ["summarization", "machine-generated"],
        ["metric"],
    ]
    assert analysis["search_queries"][0] == "factual alignment summarization"
    assert analysis["discriminative_terms"]["factuality"] == 9
    assert analysis["rerank_query"] == "factual alignment machine-generated summarization metric"


def test_later_turns_continue_the_same_conversation() -> None:
    llm, analyzer = _analyzer(
        slot_keywords=[SLOT_REPLY],
        format_search_queries=[QUERIES_REPLY],
        extract_discriminative_terms=[TERMS_REPLY],
    )

    asyncio.run(analyzer.analyze_all("q"))

    first = llm.calls[0]
    assert first["history"] == []

    # Turns 2 and 3 carry system + user + assistant from turn 1, so the model can refer
    # back to the keywords it just produced. Asking cold changes the output materially.
    for call in llm.calls[1:]:
        assert [message["role"] for message in call["history"]] == [
            "system",
            "user",
            "assistant",
        ]
        assert call["history"][2]["content"] == SLOT_REPLY


def test_keywords_are_rendered_as_python_tuples_for_the_prompt() -> None:
    llm, analyzer = _analyzer(
        slot_keywords=[SLOT_REPLY],
        format_search_queries=[QUERIES_REPLY],
        extract_discriminative_terms=[TERMS_REPLY],
    )

    asyncio.run(analyzer.analyze_all("q"))

    assert "('alignment', 'factual')" in llm.calls[1]["user"]


def test_later_turns_are_skipped_when_no_keywords_parsed() -> None:
    llm, analyzer = _analyzer(slot_keywords=["core_keywords: [(broken"])

    analysis = asyncio.run(analyzer.analyze_all("q"))

    # Only the first turn fires; the fake would raise on any unscripted follow-up.
    assert [call["prompt_key"] for call in llm.calls] == ["slot_keywords"]
    assert analysis["search_queries"] == []
    assert analysis["discriminative_terms"] == {}
    assert analysis["parse_error"]


# ---------------------------------------------------------------------------
# Pinning an original config
# ---------------------------------------------------------------------------


def test_analysis_from_config_pins_all_three_fields() -> None:
    config = {
        "query": "Have any new metrics been developed?",
        "structured_keywords": [("alignment", "factual"), ("metric",)],
        "search_queries": ["factual alignment summarization"],
        "discriminative_terms": {"factuality": 9},
    }

    analysis = analysis_from_config(config)

    assert analysis["structured_keywords"] == [["alignment", "factual"], ["metric"]]
    assert analysis["search_queries"] == ["factual alignment summarization"]
    assert analysis["discriminative_terms"] == {"factuality": 9}
    assert analysis["rerank_query"] == "factual alignment metric"


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------


def test_tool_persists_analysis_across_a_process_boundary(tmp_path) -> None:
    opened = asyncio.run(
        registry.run_tool(
            "cf.session.open", {"query": "new metrics?", "session_dir": str(tmp_path)}
        )
    )
    sid = opened.data["session_id"]

    llm = FakeLLM(
        {
            "slot_keywords": [SLOT_REPLY],
            "format_search_queries": [QUERIES_REPLY],
            "extract_discriminative_terms": [TERMS_REPLY],
        }
    )
    result = asyncio.run(
        registry.run_tool(
            "cf.query.analyze",
            {"session_id": sid, "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(llm=llm),
        )
    )

    assert result.data["search_queries"][0] == "factual alignment summarization"

    clear_cache()
    reloaded = Session.open(sid, root=tmp_path)
    assert reloaded.analysis["discriminative_terms"]["faithfulness"] == 9
    assert reloaded.analysis["rerank_query"].startswith("factual alignment")


def test_tool_can_pin_analysis_from_a_config_file(tmp_path) -> None:
    config_path = tmp_path / "semantic_5.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "query": "pinned query",
                "structured_keywords": [["alignment", "factual"], ["metric"]],
                "search_queries": ["factual alignment"],
                "discriminative_terms": {"factuality": 9},
            }
        ),
        encoding="utf-8",
    )

    opened = asyncio.run(
        registry.run_tool("cf.session.open", {"session_dir": str(tmp_path)})
    )
    sid = opened.data["session_id"]

    # No LLM is supplied: pinning must not call the model at all.
    result = asyncio.run(
        registry.run_tool(
            "cf.query.analyze",
            {"session_id": sid, "from_yaml": str(config_path), "session_dir": str(tmp_path)},
            deps=CiteFlowDeps(llm=FakeLLM({})),
        )
    )

    assert result.data["query"] == "pinned query"
    assert result.data["discriminative_terms"] == {"factuality": 9}
    assert result.data["rerank_query"] == "factual alignment metric"


def test_tool_requires_a_query() -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            registry.run_tool(
                "cf.query.analyze",
                {"session_id": Session.create().session_id},
                deps=CiteFlowDeps(llm=FakeLLM({})),
            )
        )
