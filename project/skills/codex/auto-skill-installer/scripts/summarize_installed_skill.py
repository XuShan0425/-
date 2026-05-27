#!/usr/bin/env python3
"""Summarize a locally installed skill and generate suggested commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}
    data: dict[str, str] = {}
    for line in parts[0].splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def parse_openai_yaml(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    in_interface = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if not line.startswith(" "):
            in_interface = line.strip() == "interface:"
            continue
        if not in_interface:
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def build_commands(skill_name: str, display_name: str | None, prompt: str | None) -> list[str]:
    commands = [
        f"${skill_name}",
        f"使用 {skill_name} 帮我处理一个任务",
    ]
    if display_name and display_name != skill_name:
        commands.append(f"使用 {display_name} 帮我处理一个任务")
    if prompt:
        commands.append(prompt)
    return commands


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: summarize_installed_skill.py <skill_dir>", file=sys.stderr)
        return 2

    skill_dir = Path(sys.argv[1]).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    agents_yaml = skill_dir / "agents" / "openai.yaml"

    result = {
        "path": str(skill_dir),
        "exists": skill_dir.exists(),
        "has_skill_md": skill_md.exists(),
        "has_agents_yaml": agents_yaml.exists(),
        "skill_name": skill_dir.name,
        "description": "",
        "display_name": "",
        "default_prompt": "",
        "suggested_commands": [],
    }

    if skill_md.exists():
        frontmatter = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        result["skill_name"] = frontmatter.get("name", result["skill_name"])
        result["description"] = frontmatter.get("description", "")

    if agents_yaml.exists():
        metadata = parse_openai_yaml(agents_yaml.read_text(encoding="utf-8"))
        result["display_name"] = metadata.get("display_name", "")
        result["default_prompt"] = metadata.get("default_prompt", "")

    result["suggested_commands"] = build_commands(
        result["skill_name"],
        result["display_name"] or None,
        result["default_prompt"] or None,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
