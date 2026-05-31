"""Prompt helpers for MetaSci light-agent adapters."""

from __future__ import annotations

from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_FETCH_SKILL = WORKSPACE_ROOT / "metasci-skills" / "skills" / "metasci-data-fetch" / "SKILL.md"
DEFAULT_AUTHOR_LOOKUP_SKILL = WORKSPACE_ROOT / "metasci-skills" / "skills" / "metasci-author-lookup" / "SKILL.md"


def read_skill_text(path: str | Path | None) -> str:
    if path is None:
        return ""
    skill_path = Path(path)
    if not skill_path.exists():
        return ""
    return skill_path.read_text(encoding="utf-8")


def metasci_react_system_prompt(skill_paths: list[str | Path] | None = None) -> str:
    if skill_paths is None:
        skill_paths = [DEFAULT_DATA_FETCH_SKILL, DEFAULT_AUTHOR_LOOKUP_SKILL]
    skills = "\n\n".join(read_skill_text(path) for path in skill_paths)
    return (
        "You are a MetaSci ReAct agent built on light-agent. Use the direct MetaSci "
        "Universe tools exposed in the current tool list for data retrieval: search "
        "works, get one work, search authors, get one author profile, get authors "
        "from a work, and inspect saved dataset artifacts. Choose the smallest tool "
        "set that satisfies the user request. Return artifact paths, counts, provider, "
        "and diagnostics whenever data is retrieved. Do not perform downstream analysis "
        "unless the user explicitly asks.\n\n"
        "Loaded skill instructions:\n"
        f"{skills}"
    )


top_level_system_prompt = metasci_react_system_prompt
