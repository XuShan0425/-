# Project Codex Rules

Human steers. Agents execute. The repository is the source of truth.

## Default Workflow

Before implementation:

- Restate the goal.
- Identify affected files.
- Create or update a versioned task file for non-trivial work.
- Make a short plan.
- Define acceptance criteria.

During implementation:

- Work on a `codex/...` feature branch.
- Prefer task-specific worktrees for complex work.
- Keep changes small and verifiable.
- Preserve architecture boundaries.
- Validate external data at boundaries.
- Prefer shared utilities over one-off helpers.
- Save run logs and verification evidence under `.codex-runs/`.

Before finishing:

- Run the task's verification commands.
- Run detected lint, typecheck, and test commands when available.
- Inspect the diff.
- Summarize verification evidence.

## Task Files

Each task should have a file under `.codex-tasks/`.

- New work starts in `.codex-tasks/active/`.
- In-progress work moves to `.codex-tasks/running/`.
- Work with an opened PR moves to `.codex-tasks/pr-opened/`.
- Merged or manually accepted work moves to `.codex-tasks/completed/`.
- Failed work moves to `.codex-tasks/failed/`.

Use `.codex-tasks/active/TASK-template.md` as the starting format.

## Planning

Complex work must be planned before implementation.

Planning output belongs in:

- `docs/exec-plans/active/`
- `.codex-tasks/active/`

Completed execution notes belong in:

- `docs/exec-plans/completed/`

## PR Behavior

- Automation may commit, push, and open or update PRs.
- Automation must never auto-merge.
- Automation must never commit directly to `main`, `master`, or the detected default branch.
- Automated branches must use the `codex/...` prefix.
- PRs must include verification evidence or explain why no verification command was available.

## Stop Hook Safety

The Stop hook is allowed to automate PR creation only after project hooks are trusted.

The Stop hook must:

- skip clean repositories
- move protected-branch work to a `codex/...` branch
- run available verification commands
- block completion when verification fails
- refuse to auto-commit obvious secret files or `.env` files
- commit only repository-local changes
- push the feature branch
- create or update a GitHub PR with `gh`
- never auto-merge

Never hide failing tests or claim verification passed when it did not run.
