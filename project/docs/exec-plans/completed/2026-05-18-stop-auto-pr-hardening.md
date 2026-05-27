# Stop hook hardening

## Summary

Hardened `.codex/hooks/stop_auto_pr.py` to keep Stop-hook output JSON-only, skip clean repositories with a continue payload, move unsafe work off protected branches, refuse secret-like paths, run detected verification commands, and create or update PRs without auto-merging.

## Verification

- `python -m py_compile .codex/hooks/stop_auto_pr.py` via `PYTHONPYCACHEPREFIX=/tmp/codex-pycache`
- `python -m unittest discover -s tests -p 'test_*.py'`

## Notes

- The hook now records runtime logs under `.codex-runs/`, but ignores those artifacts when deciding whether the worktree is meaningfully dirty.
- The PR body now includes verification and diff summaries plus the never-auto-merge note.

