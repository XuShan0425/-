# EPIC-001 - Stop hook hardening

## Goal

Harden `.codex/hooks/stop_auto_pr.py` so the Stop hook only emits JSON, blocks unsafe commits, runs the right verification commands, and manages branch/PR flow without auto-merging.

## Scope

- Stop-hook input parsing and JSON output
- Clean-repo continue behavior
- Protected-branch branch creation
- Verification detection and failure blocking
- Secret-path commit refusal
- Commit, fetch, rebase, push, and PR update flow
- Small helper tests

## Acceptance Criteria

- Clean repositories return a valid continue JSON response.
- Verification failures block completion and do not commit.
- Secret-like files are refused before commit.
- Protected branches never receive direct commits.
- Successful runs commit, push, and create or update a PR with verification and diff details.
- The hook never auto-merges and never writes non-JSON to stdout.

