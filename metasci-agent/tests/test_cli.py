from __future__ import annotations

from click.testing import CliRunner

from metasci_agent.cli import main


def test_cli_tools_list() -> None:
    result = CliRunner().invoke(main, ["tools", "list", "--json"])
    assert result.exit_code == 0
    assert "metasci_search_works" in result.output
    assert "metasci_list_tools" not in result.output
