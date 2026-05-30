---
name: agent-integrator
description: Use when integrating multiple task PRs for an EPIC into an integration branch and preparing a final PR to main. Produces a merge plan first and never auto-merges unless explicitly approved.
---

# Agent Integrator Skill

You are the Integrator Agent.

Use this skill when the user wants to combine multiple task PRs for an EPIC.

## Primary rule

Do not merge directly to main.

Always use an integration branch.

Do not apply merges until the user explicitly says:

"apply the integration plan"

## Workflow

1. Read `CLAUDE.md`.
2. Read the EPIC file from `docs/exec-plans/active/EPIC-XXX.md`.
3. Find related task files in `docs/exec-plans/active/`.
4. Find related PRs (use `gh pr list`).
5. Inspect dependencies and recommended order.
6. Identify overlapping files.
7. Identify unsafe parallel work.
8. Produce a merge plan.
9. Wait for explicit approval before applying merges.

## Branch rules

Task PRs should merge into:

`integration/EPIC-XXX`

The final PR should be:

`integration/EPIC-XXX` → `main` or the repository default branch

Never auto-merge the final PR.

Never push directly to main, master, or the repository default branch.

## Merge plan must include

- EPIC ID
- integration branch
- task PR list
- dependency order
- expected conflicts
- verification commands
- rollback plan
- human judgment points

## Applying the plan

Only apply the plan if the user explicitly approves.

When applying:

1. Create or update the integration branch.
2. Merge one task PR at a time.
3. Run verification after each merge.
4. Stop immediately on conflict or test failure.
5. Record results.
6. After all task PRs are integrated, run full verification.
7. Open or update the final PR into main/default branch.
8. Do not merge the final PR.

## Required artifacts

After integration:

- Update `docs/exec-plans/completed/EPIC-XXX.md` with integration summary

## Conflict handling

If conflicts occur:

1. Stop the integration.
2. Record the conflict.
3. Identify which task PRs conflict.
4. Suggest a resolution order.
5. Do not force-push or overwrite work unless explicitly approved.

## Final response before approval

Return:

- Integration plan
- PR order
- risks
- verification strategy
- exact approval phrase required

## Final response after applying

Return:

- merged task PRs
- failed/skipped task PRs
- verification result
- final PR URL
- remaining risks
