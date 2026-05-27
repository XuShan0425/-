# TASK-001-stop-auto-pr-hardening

## Parent Epic

- Epic: `EPIC-001`
- Epic file: `docs/exec-plans/active/EPIC-001.md`

## Goal

Harden `.codex/hooks/stop_auto_pr.py` to follow the requested Stop-hook contract: JSON-only output, clean-repo continue behavior, protected-branch branch creation, verification gating, secret-path refusal, PR creation/update, and no auto-merge.

## Scope

- `.codex/hooks/stop_auto_pr.py`
- `tests/test_stop_auto_pr.py`
- `docs/exec-plans/active/EPIC-001.md`

## Allowed Files

- `.codex/hooks/stop_auto_pr.py`
- `tests/test_stop_auto_pr.py`
- `docs/exec-plans/active/EPIC-001.md`
- `.codex-tasks/active/TASK-001-stop-auto-pr-hardening.md`

## Forbidden Files

- Anything outside the files above

## Acceptance Criteria

- Clean repos emit a continue JSON payload and stop.
- Protected-branch work is moved to a `codex/auto-<timestamp>` branch.
- Node `lint`, `typecheck`, and `test` scripts run when present.
- Python `ruff check .` and `pytest` run when available and relevant.
- Secret-like files block completion before commit.
- Failed verification blocks completion and skips commit.
- Successful runs commit, fetch, rebase if codex-owned, push, and open or update a PR with verification and diff summaries.
- Stdout contains only the final JSON payload.

## Verification Commands

- `python -m py_compile .codex/hooks/stop_auto_pr.py`
- `python -m unittest discover -s tests -p 'test_*.py'`

## Branch

Branch: `codex/auto-stop-auto-pr-hardening`

## Base Branch

Base branch: `main`

## Notes

- Execution finished.
- `python -m py_compile .codex/hooks/stop_auto_pr.py` required `PYTHONPYCACHEPREFIX=/tmp/codex-pycache` because the hook directory is read-only for bytecode writes.
- `python -m unittest discover -s tests -p 'test_*.py'` passed.

