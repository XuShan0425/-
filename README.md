# Codex Environment Template

This repository is a reusable Codex development environment template. Install it into a project when you want an agent-first workflow where the repository is the source of truth, complex work is planned before implementation, each task has a versioned task file, and Codex worker runs leave logs, verification evidence, commits, pushes, and GitHub PRs.

The template is intentionally an MVP. It uses plain files, Python scripts, Git worktrees, `gh`, and the Codex CLI. It never auto-merges and it never commits directly to `main`, `master`, or the detected default branch.

## Requirements

- Git
- Python 3.10+
- GitHub CLI: `gh`
- Codex CLI with `codex exec`
- A GitHub remote named `origin`
- `gh auth login` completed for the target repository

## Install

From this template directory, run the installer inside the repository you want to configure:

```bash
/path/to/codex-env-template/install.sh --profile generic
```

Profiles:

```bash
/path/to/codex-env-template/install.sh --profile node
/path/to/codex-env-template/install.sh --profile python
```

The installer copies the `project/` template into the current Git repository. Existing files are not overwritten unless you pass `--force`:

```bash
/path/to/codex-env-template/install.sh --profile python --force
```

The installer also appends profile-specific rules to `AGENTS.md` and makes the hook and orchestrator scripts executable.

## Trust Hooks

After installation, open Codex in the project and run:

```text
/hooks
```

Review and trust the project hooks. The Stop hook becomes active only after project hooks are trusted.

The installed hook is:

```text
.codex/hooks/stop_auto_pr.py
```

It is called from `.codex/hooks.json` using `$(git rev-parse --show-toplevel)`, so it works when Codex stops from a subdirectory.

## Workflow

### 1. Plan

Ask the orchestrator to create an epic and task files:

```bash
python3 .codex/orchestrator/codex-team.py plan "Add password reset flow with tests"
```

The planner runs Codex non-interactively and asks it to create:

- `docs/exec-plans/active/EPIC-*.md`
- `.codex-tasks/active/TASK-*.md`

Planning mode should not implement business logic.

### 2. Run A Task

Run one task in its own branch and worktree:

```bash
python3 .codex/orchestrator/codex-team.py run TASK-001
```

The orchestrator:

- creates a `codex/...` branch
- creates a Git worktree outside the main working tree
- runs `codex exec --json --sandbox workspace-write`
- stores JSONL logs and a run summary under `.codex-runs/`
- runs verification commands
- commits, pushes, and opens or updates a GitHub PR with `gh`

### 3. Review The PR

Review the PR in GitHub. The system does not auto-merge.

Useful commands:

```bash
gh pr list --head codex/TASK-001
gh pr checks <pr-number>
gh pr view <pr-number> --web
```

### 4. Integrate

Use the conservative integration helper:

```bash
python3 .codex/orchestrator/codex-team.py integrate EPIC-001
```

The MVP integration command lists relevant PRs and prints next-step commands. It does not merge.

## Stop Hook Behavior

When Codex stops after editing a trusted project, the Stop hook:

- reads hook JSON from stdin
- detects the Git repository root
- skips clean repositories
- detects the default branch
- creates a `codex/...` branch if Codex is on `main`, `master`, the default branch, a detached head, or a non-`codex/` branch
- detects common Node and Python verification commands
- blocks if Git is already mid-merge/rebase or if obvious secret or `.env` files are present
- runs lint, typecheck, and tests when available
- blocks completion if verification fails
- stages and commits repository changes
- pushes the branch
- creates or updates a GitHub PR using `gh`

The hook emits JSON to stdout. On verification failure it returns a block response that asks Codex to fix the failing command.

## Safety Assumptions

- Auto PR is enabled by committed project files, not environment variables.
- The Stop hook never auto-merges.
- The Stop hook refuses to commit to `main`, `master`, or the detected default branch.
- Branches created by automation use the `codex/...` prefix.
- Verification failures are not hidden. They block completion.
- Obvious secret files and `.env` files are blocked before auto-commit.
- Python scripts use subprocess argv lists and do not use `shell=True`.
- Work should happen in clean task worktrees when possible.
- Secrets must not be committed. Review diffs and PRs before merging.

## Node Example

Install:

```bash
/path/to/codex-env-template/install.sh --profile node
```

Expected scripts in `package.json`:

```json
{
  "scripts": {
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  }
}
```

The hook and orchestrator detect `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, and `package-lock.json` to choose the package manager.

## Python Example

Install:

```bash
/path/to/codex-env-template/install.sh --profile python
```

Typical verification files:

```text
pyproject.toml
pytest.ini
ruff.toml
mypy.ini
tests/
```

The hook and orchestrator run available commands such as:

```bash
ruff check .
mypy .
python3 -m pytest
```

## Manual Stop Hook Test

You can run the hook manually from a repository after installation:

```bash
printf '{}\n' | python3 .codex/hooks/stop_auto_pr.py
```

If there are no changes, it returns a JSON approval response and skips PR creation.
