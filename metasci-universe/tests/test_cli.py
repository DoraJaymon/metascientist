from __future__ import annotations

from click.testing import CliRunner

from metasci_universe.cli import main


def test_cli_tools_list_json() -> None:
    result = CliRunner().invoke(main, ["tools", "list", "--json"])
    assert result.exit_code == 0
    assert "works.search" in result.output
    assert "conferences.papers" in result.output


def test_cli_tools_describe_json() -> None:
    result = CliRunner().invoke(main, ["tools", "describe", "works.search", "--json"])
    assert result.exit_code == 0
    assert '"name": "works.search"' in result.output


def test_cli_conference_papers_accepts_new_sources() -> None:
    result = CliRunner().invoke(main, ["conferences", "papers", "--help"])
    assert result.exit_code == 0
    assert "--source-collection-id" in result.output
    assert "pmlr" in result.output


def test_cli_citations_help() -> None:
    result = CliRunner().invoke(main, ["citations", "lookup", "--help"])
    assert result.exit_code == 0
    assert "--openalex-id" in result.output
    assert "--s2-id" in result.output
    assert "--direction" not in result.output
