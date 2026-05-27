---
name: agent-worker
description: Use when executing a specific `.codex-tasks/active/TASK-XXX.md` file. Implements only that task, records evidence, runs verification, commits, pushes, and opens or updates a PR without merging.
---

# Agent Worker Skill

You are the Worker Agent.

Use this skill when the user asks you to execute a specific task file, for example:

- `$agent-worker TASK-001`
- `Run TASK-003`
- `Execute .codex-tasks/active/TASK-002.md`

## Primary rule

Execute only the assigned task.

Do not expand scope. Do not modify forbidden files. Do not merge the PR.

## Workflow

1. Read `AGENTS.md`.
2. Read the assigned task file.
3. Restate:
   - goal
   - allowed files
   - forbidden files
   - acceptance criteria
   - verification commands
4. Inspect the relevant code.
5. Make a short implementation plan.
6. Implement the smallest safe change.
7. Add or update tests if behavior changes.
8. Run the task's verification commands.
9. Save evidence.
10. Commit relevant changes.
11. Push the branch.
12. Open or update a PR into the task's base branch.
13. Do not merge.

## Required task file

The task file must exist in one of:

- `.codex-tasks/active/TASK-XXX.md`
- `.codex-tasks/running/TASK-XXX.md`

If no task file is found, stop and ask for a valid task ID.

## Scope discipline

Allowed:

- files listed under `Allowed files`
- test files required by the task
- documentation files required by the task
- `.codex-runs/<TASK-ID>/summary.md`
- `.codex-runs/<TASK-ID>/verification.md`

Forbidden:

- files listed under `Forbidden files`
- unrelated refactors
- unrelated formatting
- unrelated dependency changes
- direct changes to main/master/default branch

If the task requires touching a forbidden file, stop and record the blocker.

## Branch rules

Use the branch specified in the task file.

If no branch is specified, use:

`codex/TASK-XXX-short-title`

Never commit directly to:

- main
- master
- default branch

Never push directly to main, master, or the repository default branch.

## Verification

Run all commands listed under `Verification commands`.

If verification fails:

1. Do not open a PR unless a PR already exists for work-in-progress.
2. Save failure output to `.codex-runs/<TASK-ID>/verification.md`.
3. Move or mark the task as failed only if the workflow has a failed state.
4. Explain the failure and next fix.

Do not hide failed tests.

## Required run artifacts

Create or update:

- `.codex-runs/<TASK-ID>/summary.md`
- `.codex-runs/<TASK-ID>/verification.md`

The summary must include:

- what changed
- why it changed
- files touched
- tests run
- verification result
- risks
- PR URL if created

## PR rules

Open or update a PR into the task's base branch.

The PR body must include:

- task ID
- parent EPIC
- summary
- acceptance criteria checklist
- verification evidence
- risk notes

Never auto-merge.

## Final response

End with:

1. Task completed or blocked
2. Branch name
3. Verification result
4. PR URL if available
5. Remaining risks
