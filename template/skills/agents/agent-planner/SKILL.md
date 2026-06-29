---
name: agent-planner
description: Use when the user gives a high-level requirement and wants it clarified, split into an EPIC + bounded TASK files under .agent-tasks/. Planning only — do not implement business logic.
---

# Planner

Turn an unclear or broad requirement into versioned planning artifacts that
worker sessions can execute autonomously.

## Primary rule

Do not implement business logic. Your output is plan and task files only.

## Workflow

1. Read `CLAUDE.md`.
2. Restate the requirement; surface assumptions.
3. Ask only essential clarification questions when the requirement is too
   ambiguous to plan safely.
4. Create the EPIC plan and bounded task files.

## Output locations

- `docs/exec-plans/active/EPIC-XXX.md`
- `.agent-tasks/active/TASK-001.md`, `TASK-002.md`, …
- Use `.agent-tasks/active/TASK-template.md` as the format.

## EPIC file includes

Title, user goal, non-goals, assumptions, constraints, architecture impact,
task list, dependency graph, testing strategy, open questions.

## Task file includes

Task ID, parent epic, goal, non-goals, allowed files, forbidden files,
dependencies, acceptance criteria, verification commands, branch (`agent/...`),
base branch, parallel-safety, expected outputs.

## Sizing

Each task must be small enough for one worker to finish in one branch with a
clear, verifiable result. Prefer narrow scope, explicit files, testable
acceptance criteria, minimal overlap. Mark tasks that touch lockfiles, schema,
shared types, or auth boundaries as unsafe for parallel execution.

## Autopilot note

In this project, a completed task auto-merges once verification passes — there
is no manual review gate. So plan verification commands carefully: they are the
only thing standing between a task and `main`. Prefer concrete, fast commands.
