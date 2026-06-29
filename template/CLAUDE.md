# Project Rules — Autopilot Mode

Human steers. Agents execute — **fully autonomously, no human confirmation**.
The repository is the source of truth.

This project runs in autopilot: agents plan, implement, verify, commit, push,
open PRs, and **auto-merge** without asking. The only quality gate is
verification. The only hard guardrail is the secret block (below).

## Autopilot behavior

- **No confirmation prompts.** Permission mode is `bypassPermissions`
  (`.claude/settings.json`). Every tool call proceeds without asking.
- **Auto-merge.** PRs merge into their base branch automatically once
  verification passes. There is no human review step.
- **Main is allowed.** Agents may commit to and merge into `main` (or the
  detected default branch). There is no protected-branch fence.
- **Verification is the sole gate.** Detected `lint` / `typecheck` / `test`
  commands must pass before anything is committed. If they fail, fix them
  before stopping — failed verification blocks completion.
- **Isolated task execution.** The orchestrator runs each task in its own git
  worktree on an `agent/...` branch, then merges.

## The one guardrail: secrets

Never weakened, even in autopilot:

- The Stop hook and orchestrator **refuse to commit** files matching secret
  patterns: `.env*`, `secrets/`, and paths containing `secret` or `token`.
- Remove such files from the change set and proceed. This is the only thing
  that will block an otherwise-verifying change.

Never attempt to disable this check or route secrets around it.

## Workflow

Plan, then run, then check status — all driven by the orchestrator:

```bash
python orchestrator/agent-team.py plan  "describe the requirement"
python orchestrator/agent-team.py run   TASK-001
python orchestrator/agent-team.py status
python orchestrator/agent-team.py integrate
```

- `plan` — a headless Claude session writes an EPIC + task files; it does not
  edit application code.
- `run` — executes one task in a worktree: implement → verify → commit → push →
  open PR → **auto-merge** → move the task to `completed`.
- `status` — shows task counts per state.
- `integrate` — lists any `agent/...` PRs that failed to auto-merge.

For ad-hoc interactive work, just edit and stop: the Stop hook verifies,
commits, pushes, and (on a feature branch) auto-merges for you.

## Task files

Each task is a markdown file under `.agent-tasks/` and moves through states:

- `active/` — planned, waiting to run
- `running/` — a worker is executing it
- `pr-opened/` — (reserved; autopilot merges immediately, so rarely used)
- `completed/` — merged
- `failed/` — verification failed, worker errored, or no changes

Start from `.agent-tasks/active/TASK-template.md`. Every task must specify:
goal, scope, allowed files, forbidden files, acceptance criteria, verification
commands, branch (`agent/...`), and base branch.

## Planning

Complex work is planned before implementation.

- Execution plans live in `docs/exec-plans/active/` (and `completed/`).
- Task files live in `.agent-tasks/active/`.
- Run logs and summaries live in `.agent-runs/`.

## Before finishing any change

- Run the task's verification commands (or the detected lint/typecheck/test).
- Do not stop while verification is failing — the Stop hook will block.
- Inspect the diff.
- Record evidence under `.agent-runs/`.

## General conduct

- Treat the repository as the source of truth.
- Restate the goal before non-trivial work.
- Identify affected files before editing.
- Keep changes small, scoped, and verifiable.
- Preserve architecture boundaries and existing style.
- Validate external data at boundaries.
- Prefer shared utilities (`lib/agent_core.py`) over one-off helpers.
- Never hide failing tests or claim verification passed when it did not run.
