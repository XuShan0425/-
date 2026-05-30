---
name: yeet
description: Use only when the user explicitly asks to stage, commit, push, and open a GitHub pull request in one flow using the GitHub CLI (`gh`).
---

## Prerequisites

- Require GitHub CLI `gh`. Check `gh --version`. If missing, ask the user to install `gh` and stop.
- Require authenticated `gh` session. Run `gh auth status`. If not authenticated, ask the user to run `gh auth login` before continuing.

## Naming conventions

- Branch: `feature/{description}` when starting from main/master/default.
- Commit: `{description}` (terse).
- PR title: `{description}` summarizing the full diff.

## Workflow

- If on main/master/default, create a branch: `git checkout -b "feature/{description}"`
- Otherwise stay on the current branch.
- Confirm status: `git status -sb`
- Stage all changes: `git add -A`
- Commit tersely with the description: `git commit -m "{description}"`
- Run checks if not already. If checks fail due to missing deps/tools, install dependencies and rerun once.
- Push with tracking: `git push -u origin $(git branch --show-current)`
- Open a PR: `gh pr create --draft --fill --head $(git branch --show-current)`
- PR description (markdown) must be detailed prose covering the issue, the cause and effect, the root cause, the fix, and any tests or checks used to validate.
- Never auto-merge.
