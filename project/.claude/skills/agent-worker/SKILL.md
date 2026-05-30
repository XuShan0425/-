---
name: agent-worker
description: Use when executing a specific TASK-XXX from docs/exec-plans/active/. Implements only that task, records evidence, runs verification, commits, pushes, and opens or updates a PR without merging.
---

# Agent Worker Skill

You are the Worker Agent.

Use this skill when the user asks you to execute a specific task file, for example:

- `Run TASK-001`
- `Execute docs/exec-plans/active/TASK-002.md`

## Primary rule

Execute only the assigned task.

Do not expand scope. Do not modify forbidden files. Do not merge the PR.

## Workflow

1. Read `CLAUDE.md`.
2. Read the assigned task file from `docs/exec-plans/active/`.
3. Restate:
   - goal
   - allowed files
   - forbidden files
   - acceptance criteria
   - verification commands
4. Inspect the relevant code.
5. Make a short implementation plan. Use `EnterPlanMode` if the task touches more than 2 files.
6. Implement the smallest safe change.
7. Add or update tests if behavior changes.
8. Run the task's verification commands.
9. Commit relevant changes (use `TaskCreate` / `TaskUpdate` to track progress).
10. Push the branch.
11. Open or update a PR into the task's base branch.
12. Do not merge.

## Required task file

The task file must exist in:

- `docs/exec-plans/active/TASK-XXX.md`

If no task file is found, stop and ask for a valid task ID.

## Scope discipline

Allowed:

- files listed under `Allowed files`
- test files required by the task
- documentation files required by the task

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

`feature/TASK-XXX-short-title`

Never commit directly to:

- main
- master
- default branch

Never push directly to main, master, or the repository default branch.

## Verification

Run all commands listed under `Verification commands`.

If verification fails:

1. Do not open a PR unless a PR already exists for work-in-progress.
2. Explain the failure and next fix.

Do not hide failed tests.

## Required run artifacts

After completing the task:

- Update the task file with execution notes
- Summarize what changed, why it changed, files touched, tests run, and verification result

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
