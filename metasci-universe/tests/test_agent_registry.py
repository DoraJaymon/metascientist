from __future__ import annotations

from metasci_universe import describe_tool, list_tools, tool_schema


def test_tool_registry_lists_phase_1_tools() -> None:
    tools = list_tools()
    assert "works.search" in tools
    assert "works.fulltext" in tools
    assert "authors.search" in tools
    assert "authors.profile" in tools
    assert "authors.from_work" in tools
    assert "citations.resolve" in tools
    assert "citations.lookup" in tools
    assert "citations.references" in tools
    assert "citations.citations" in tools
    assert "conferences.papers" in tools
    assert "embeddings.embed_works" in tools
    assert "dataset.info" in tools
    assert "analysis.author_landscape" in tools


def test_tool_schema_is_introspectable() -> None:
    schema = tool_schema("works.search")
    assert schema["type"] == "object"
    assert "query" in schema["properties"]

    card = describe_tool("authors.search")
    assert card["name"] == "authors.search"
    assert "inputs" in card

    citation_schema = tool_schema("citations.lookup")
    assert "openalex_id" in citation_schema["properties"]
    assert "direction" not in citation_schema["properties"]

    fulltext_card = describe_tool("works.fulltext")
    assert fulltext_card["name"] == "works.fulltext"
    assert "identifier" in fulltext_card["inputs"]["properties"]
    assert "download_pdf" in fulltext_card["inputs"]["properties"]
    provider_schema = fulltext_card["inputs"]["properties"]["provider"]
    assert "springer" in provider_schema["enum"]
