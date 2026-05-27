#!/usr/bin/env bash
set -euo pipefail

# Install bundled skills into the local Codex/Claude skills directories.
# Skips any skill that is already installed (existence check at target path).
# Supports both Claude Code and Codex environments.

usage() {
  cat <<'USAGE'
Usage: install-skills.sh [--dry-run] [--force]

Install bundled skills into ~/.codex/skills, ~/.agents/skills, and
~/.codex/skills/.system.  Skips skills already present at the target
location unless --force is used.

Options:
  --dry-run   Print what would be installed without copying.
  --force     Overwrite existing skill directories.
  -h, --help  Show this help.
USAGE
}

DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$SCRIPT_DIR/skills"

# --- target directories ---
CODEX_DIR="${CODEX_DIR:-$HOME/.codex/skills}"
AGENTS_DIR="${AGENTS_DIR:-$HOME/.agents/skills}"
GITHUB_PLUGIN_DIR="${GITHUB_PLUGIN_DIR:-$HOME/.codex/skills/github-plugin}"

# --- helper ---
install_skill() {
  local src_dir="$1"
  local dst_dir="$2"
  local skill_name="$3"

  local src="$src_dir/$skill_name"
  local dst="$dst_dir/$skill_name"

  if [[ ! -d "$src" ]]; then
    echo "warning: source not found: $src" >&2
    return 1
  fi

  if [[ -d "$dst" || -f "$dst/SKILL.md" ]] && [[ "$FORCE" -ne 1 ]]; then
    echo "skip (exists): $dst"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "would install: $skill_name → $dst"
    return 0
  fi

  mkdir -p "$(dirname "$dst")"
  if [[ -d "$dst" ]]; then
    rm -rf "$dst"
  fi
  cp -r "$src" "$dst"
  echo "installed: $dst"
}

# ==============================================
# Agent skills → ~/.agents/skills/
# ==============================================
AGENT_SKILLS=(
  agent-planner
  agent-worker
  agent-reviewer
  agent-integrator
  find-skills
)

echo "==> Agent skills (~/.agents/skills/)"
for skill in "${AGENT_SKILLS[@]}"; do
  install_skill "$SKILLS_SRC/agents" "$AGENTS_DIR" "$skill"
done

# ==============================================
# Codex skills → ~/.codex/skills/
# ==============================================
CODEX_SKILLS=(
  gh-address-comments
  gh-fix-ci
  yeet
  auto-skill-installer
)

echo "==> Codex skills (~/.codex/skills/)"
for skill in "${CODEX_SKILLS[@]}"; do
  install_skill "$SKILLS_SRC/codex" "$CODEX_DIR" "$skill"
done

# ==============================================
# GitHub plugin skills → ~/.codex/skills/github-plugin/
# ==============================================
GITHUB_PLUGIN_SKILLS=(
  github
)

echo "==> GitHub plugin skills (~/.codex/skills/github-plugin/)"
for skill in "${GITHUB_PLUGIN_SKILLS[@]}"; do
  install_skill "$SKILLS_SRC/github-plugin" "$GITHUB_PLUGIN_DIR" "$skill"
done

echo ""
echo "Skill installation complete."
echo "Installed skills will be available on the next Codex / Claude session."
