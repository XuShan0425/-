#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install.sh [--profile generic|node|python] [--force]

Install the Codex project environment template into the current repository.

Options:
  --profile   AGENTS profile to append. Default: generic.
  --force     Overwrite existing files when copying template files.
  -h, --help  Show this help.
USAGE
}

PROFILE="generic"
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      if [[ $# -lt 2 ]]; then
        echo "error: --profile requires generic, node, or python" >&2
        exit 2
      fi
      PROFILE="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$PROFILE" in
  generic|node|python) ;;
  *)
    echo "error: unsupported profile: $PROFILE" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_SRC="$SCRIPT_DIR/project"
PROFILE_FILE="$SCRIPT_DIR/profiles/$PROFILE/AGENTS.append.md"

if [[ ! -d "$PROJECT_SRC" ]]; then
  echo "error: project template directory not found: $PROJECT_SRC" >&2
  exit 1
fi

if [[ ! -f "$PROFILE_FILE" ]]; then
  echo "error: profile file not found: $PROFILE_FILE" >&2
  exit 1
fi

if git_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  TARGET_ROOT="$git_root"
else
  TARGET_ROOT="$(pwd)"
  echo "warning: current directory is not inside a Git repository; installing into $TARGET_ROOT" >&2
fi

copy_file() {
  local src="$1"
  local rel="$2"
  local dest="$TARGET_ROOT/$rel"

  mkdir -p -- "$(dirname -- "$dest")"

  if [[ -e "$dest" && "$FORCE" -ne 1 ]]; then
    echo "skip existing: $rel"
    return 0
  fi

  cp -- "$src" "$dest"
  echo "installed: $rel"
}

while IFS= read -r -d '' src; do
  rel="${src#"$PROJECT_SRC"/}"
  copy_file "$src" "$rel"
done < <(find "$PROJECT_SRC" -type f -print0 | sort -z)

AGENTS_FILE="$TARGET_ROOT/AGENTS.md"
BEGIN_MARKER="<!-- codex-env-template profile:$PROFILE begin -->"
END_MARKER="<!-- codex-env-template profile:$PROFILE end -->"

if [[ ! -f "$AGENTS_FILE" ]]; then
  touch "$AGENTS_FILE"
fi

if grep -Fq "$BEGIN_MARKER" "$AGENTS_FILE"; then
  echo "profile already appended: $PROFILE"
else
  {
    printf '\n%s\n' "$BEGIN_MARKER"
    cat "$PROFILE_FILE"
    printf '\n%s\n' "$END_MARKER"
  } >> "$AGENTS_FILE"
  echo "appended profile rules: $PROFILE"
fi

chmod +x "$TARGET_ROOT/.codex/hooks/stop_auto_pr.py" 2>/dev/null || true
chmod +x "$TARGET_ROOT/.codex/orchestrator/codex-team.py" 2>/dev/null || true
chmod +x "$TARGET_ROOT/install-skills.sh" 2>/dev/null || true

# Install bundled skills
if [[ -x "$TARGET_ROOT/install-skills.sh" ]]; then
  echo ""
  echo "Installing bundled skills..."
  "$TARGET_ROOT/install-skills.sh"
fi

cat <<NEXT_STEPS

Codex environment template installed into:
  $TARGET_ROOT

Next steps:
  1. Confirm GitHub CLI authentication:
     gh auth status

  2. Open Codex in this repository and trust project hooks:
     /hooks

  3. Plan work (agent-planner will be auto-invoked):
     python3 .codex/orchestrator/codex-team.py plan "Describe the requirement"

  4. Run a task (agent-worker will be auto-invoked):
     python3 .codex/orchestrator/codex-team.py run TASK-001

Installed skills: agent-planner, agent-worker, agent-reviewer,
  agent-integrator, find-skills, gh-address-comments, gh-fix-ci,
  yeet, auto-skill-installer, github

Safety:
  - Automation uses codex/... branches.
  - Stop hook never auto-merges.
  - Stop hook refuses direct commits to main/master/default branch.
NEXT_STEPS
