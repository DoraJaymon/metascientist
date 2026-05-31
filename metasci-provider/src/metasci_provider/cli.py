"""CLI entrypoint for the private MetaSci provider skeleton."""

from __future__ import annotations

import json

import click

from metasci_provider.service import create_app


@click.group()
def main() -> None:
    """MetaSci provider service commands."""


@main.command("schema")
def schema_cmd() -> None:
    """Print the service contract summary."""
    app = create_app()
    click.echo(json.dumps({"app": app.title, "version": app.version}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
