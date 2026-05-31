"""CLI smoke runner for MetaSci light-agent adapters."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from metasci_agent.tools.metasci_tools import get_metasci_agent_tool, metasci_agent_tools


def _run(coro):
    return asyncio.run(coro)


@click.group()
def main() -> None:
    """MetaSci light-agent adapter CLI."""


@main.group("tools")
def tools_group() -> None:
    """Adapter tool smoke commands."""


@tools_group.command("list")
@click.option("--json", "as_json", is_flag=True)
def list_tools_cmd(as_json: bool) -> None:
    tools = metasci_agent_tools()
    if as_json:
        click.echo(json.dumps([tool.to_manifest() for tool in tools], ensure_ascii=False, indent=2))
        return
    click.echo("\n".join(tool.name for tool in tools))


@tools_group.command("describe")
@click.argument("tool_name")
@click.option("--json", "as_json", is_flag=True)
def describe_tool_cmd(tool_name: str, as_json: bool) -> None:
    try:
        tool = get_metasci_agent_tool(tool_name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    manifest = tool.to_manifest()
    if as_json:
        click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))


@tools_group.command("run")
@click.argument("tool_name")
@click.argument("arguments_json")
@click.option("--json", "as_json", is_flag=True)
def run_tool_cmd(tool_name: str, arguments_json: str, as_json: bool) -> None:
    try:
        arguments: dict[str, Any] = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON arguments: {exc}") from exc

    try:
        tool = get_metasci_agent_tool(tool_name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    result = _run(tool.forward(**arguments))
    if result.error:
        raise click.ClickException(result.error)
    if as_json:
        click.echo(json.dumps(result.structured_output, ensure_ascii=False, indent=2))
        return
    click.echo(result.output)


@main.command("react")
@click.argument("task")
@click.option("--model", "model_id", default="gpt-5.4-mini", show_default=True)
@click.option("--base-url", default=None, help="OpenAI-compatible API base URL.")
@click.option("--max-steps", type=int, default=8, show_default=True)
def react_cmd(task: str, model_id: str, base_url: str | None, max_steps: int) -> None:
    """Run the MetaSci ReAct agent with an OpenAI-compatible model."""
    try:
        from light_agent.llm import LLMConfig, create_openai_model

        from metasci_agent.agents.data_fetch_agent import DataFetchAgent

        config = LLMConfig.from_env(
            default_model=model_id,
            model_id=model_id,
            base_url=base_url,
            model_env_vars=("METASCI_AGENT_MODEL", "OPENAI_MODEL"),
        )
        model = create_openai_model(config, temperature=0, max_tokens=1600, trust_env=False)
        agent = DataFetchAgent(
            model=model,
            max_steps=max_steps,
            verbose=True,
        )
        answer = _run(agent.run(task))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        client = getattr(locals().get("model", None), "client", None)
        if client is not None:
            _run(client.close())

    click.echo(answer)


if __name__ == "__main__":
    main()
