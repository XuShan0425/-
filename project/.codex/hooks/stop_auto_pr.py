#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTECTED_BRANCH_NAMES = {"main", "master"}
VERIFY_TIMEOUT_SECONDS = 900
RUNTIME_ARTIFACT_PREFIX = ".codex-runs/"

ENV_FILE_PATTERN = re.compile(r"(^|/)\.env(\.|$)")
SECRETS_DIR_PATTERN = re.compile(r"(^|/)secrets(/|$)")


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class VerifyCommand:
    label: str
    args: list[str]


@dataclass
class VerificationResult:
    command: VerifyCommand
    returncode: int
    stdout: str
    stderr: str


class HookBlock(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def display_cmd(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def tail(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def debug(message: str) -> None:
    sys.stderr.write(f"[stop_auto_pr] {message}\n")
    sys.stderr.flush()


def emit(decision: str, reason: str, **extra: Any) -> None:
    payload: dict[str, Any] = {"decision": decision, "reason": reason}
    payload.update(extra)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = False,
    timeout: int | None = None,
    input_text: str | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        result = CommandResult(args=args, returncode=127, stdout="", stderr=str(exc))
        if check:
            raise HookBlock(
                f"Command not found: {display_cmd(args)}\n"
                f"stderr:\n{tail(result.stderr)}"
            ) from exc
        return result
    except OSError as exc:
        result = CommandResult(args=args, returncode=127, stdout="", stderr=str(exc))
        if check:
            raise HookBlock(
                f"Failed to launch command: {display_cmd(args)}\n"
                f"stderr:\n{tail(result.stderr)}"
            ) from exc
        return result

    result = CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and result.returncode != 0:
        raise HookBlock(
            f"Command failed: {display_cmd(args)}\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )
    return result


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def event(log_path: Path | None, kind: str, **data: Any) -> None:
    if log_path is None:
        return
    payload = {
        "time": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **data,
    }
    append_jsonl(log_path, payload)


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HookBlock(f"Could not parse Stop hook input as JSON: {exc.msg}") from exc
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def repo_root_from_git(cwd: Path) -> Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def git_stdout(repo: Path, args: list[str], *, check: bool = True) -> str:
    return run(["git", *args], repo, check=check).stdout.strip()


def split_nul(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def staged_paths(repo: Path) -> list[str]:
    result = run(["git", "diff", "--cached", "--name-only", "-z"], repo, check=True)
    return split_nul(result.stdout)


def unstaged_paths(repo: Path) -> list[str]:
    result = run(
        ["git", "ls-files", "-m", "-d", "-o", "--exclude-standard", "-z"],
        repo,
        check=True,
    )
    return split_nul(result.stdout)


def unmerged_paths(repo: Path) -> list[str]:
    result = run(["git", "diff", "--name-only", "--diff-filter=U", "-z"], repo, check=True)
    return split_nul(result.stdout)


def git_path(repo: Path, ref: str) -> Path:
    result = run(["git", "rev-parse", "--git-path", ref], repo, check=True)
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else repo / path


def in_progress_git_operations(repo: Path) -> list[str]:
    operations: list[str] = []
    if git_path(repo, "rebase-apply").exists() or git_path(repo, "rebase-merge").exists():
        operations.append("rebase")
    if git_path(repo, "MERGE_HEAD").exists():
        operations.append("merge")
    if git_path(repo, "CHERRY_PICK_HEAD").exists():
        operations.append("cherry-pick")
    if git_path(repo, "REVERT_HEAD").exists():
        operations.append("revert")
    return operations


def is_runtime_artifact(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == ".codex-runs" or normalized.startswith(RUNTIME_ARTIFACT_PREFIX)


def visible_changed_paths(repo: Path) -> list[str]:
    return [
        path
        for path in unique_paths([*staged_paths(repo), *unstaged_paths(repo)])
        if not is_runtime_artifact(path)
    ]


def is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if ENV_FILE_PATTERN.search(normalized):
        return True
    if SECRETS_DIR_PATTERN.search(normalized):
        return True
    if "secret" in normalized:
        return True
    if "token" in normalized:
        return True
    return False


def current_branch(repo: Path) -> str:
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo, check=True)
    return result.stdout.strip()


def ref_exists(repo: Path, ref: str) -> bool:
    result = run(["git", "rev-parse", "--verify", "--quiet", ref], repo)
    return result.returncode == 0


def detect_default_branch(repo: Path) -> str:
    result = run(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        repo,
    )
    if result.returncode == 0 and result.stdout.strip():
        remote_ref = result.stdout.strip()
        if "/" in remote_ref:
            return remote_ref.split("/", 1)[1]
        return remote_ref

    result = run(["git", "remote", "show", "origin"], repo)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            match = re.search(r"HEAD branch:\s*(\S+)", line)
            if match:
                return match.group(1)

    for candidate in ("main", "master"):
        if ref_exists(repo, f"refs/heads/{candidate}") or ref_exists(
            repo, f"refs/remotes/origin/{candidate}"
        ):
            return candidate
    return "main"


def python_executable() -> str:
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python"


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def package_manager(repo: Path, package_json: dict[str, Any]) -> str:
    declared = str(package_json.get("packageManager", ""))
    if declared.startswith("pnpm@") or (repo / "pnpm-lock.yaml").exists():
        return "pnpm"
    if declared.startswith("yarn@") or (repo / "yarn.lock").exists():
        return "yarn"
    if declared.startswith("npm@") or (repo / "package-lock.json").exists():
        return "npm"
    if declared.startswith("bun@") or (repo / "bun.lockb").exists() or (repo / "bun.lock").exists():
        return "bun"
    return "npm"


def node_command(pm: str, script_name: str) -> list[str]:
    if pm == "yarn":
        return ["yarn", "run", script_name]
    return [pm, "run", script_name]


def ruff_available() -> bool:
    return shutil.which("ruff") is not None


def pytest_available() -> bool:
    if shutil.which("pytest") is not None:
        return True
    try:
        return importlib.util.find_spec("pytest") is not None
    except (ImportError, ValueError):
        return False


def has_python_project(repo: Path) -> bool:
    markers = (
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pytest.ini",
        "tox.ini",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
    )
    if any((repo / marker).exists() for marker in markers):
        return True
    if any(repo.glob("requirements*.txt")):
        return True
    return (repo / "src").is_dir() or (repo / "tests").is_dir()


def detect_verification_commands(repo: Path) -> list[VerifyCommand]:
    commands: list[VerifyCommand] = []

    package_path = repo / "package.json"
    if package_path.exists():
        package = load_json(package_path)
        scripts = package.get("scripts", {})
        if isinstance(scripts, dict):
            pm = package_manager(repo, package)
            for name in ("lint", "typecheck", "test"):
                script = scripts.get(name)
                if isinstance(script, str) and script.strip():
                    commands.append(VerifyCommand(f"node:{name}", node_command(pm, name)))

    if has_python_project(repo):
        if ruff_available():
            commands.append(VerifyCommand("python:ruff", ["ruff", "check", "."]))
        if pytest_available():
            pytest_bin = shutil.which("pytest")
            commands.append(
                VerifyCommand(
                    "python:pytest",
                    [pytest_bin] if pytest_bin else [python_executable(), "-m", "pytest"],
                )
            )

    seen: set[tuple[str, ...]] = set()
    unique: list[VerifyCommand] = []
    for command in commands:
        key = tuple(command.args)
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def run_verification(repo: Path, commands: list[VerifyCommand], log_path: Path) -> list[VerificationResult]:
    if not commands:
        event(log_path, "verification_skipped", reason="no verification commands detected")
        return []

    results: list[VerificationResult] = []
    for command in commands:
        debug(f"Verification start: {display_cmd(command.args)}")
        event(log_path, "verification_start", label=command.label, command=command.args)
        result = run(command.args, repo, timeout=VERIFY_TIMEOUT_SECONDS)
        verification = VerificationResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        results.append(verification)
        event(
            log_path,
            "verification_finish",
            label=command.label,
            command=command.args,
            returncode=result.returncode,
            stdout_tail=tail(result.stdout, 4000),
            stderr_tail=tail(result.stderr, 4000),
        )
        if result.returncode != 0:
            raise HookBlock(
                "Verification failed. Fix the failure before stopping again.\n\n"
                f"Command: {display_cmd(command.args)}\n"
                f"Log: {log_path.relative_to(repo)}\n\n"
                f"stdout:\n{tail(result.stdout)}\n\n"
                f"stderr:\n{tail(result.stderr)}"
            )
    return results


def build_verification_report(results: list[VerificationResult], commands: list[VerifyCommand]) -> str:
    if not commands:
        return "- No verification commands were detected."
    return "\n".join(f"- PASS: `{display_cmd(item.command.args)}`" for item in results)


def diff_summary(repo: Path) -> str:
    result = run(["git", "diff", "--cached", "--stat", "--summary"], repo, check=True)
    summary = result.stdout.strip()
    return summary if summary else "(no staged diff)"


def branch_requires_codex_branch(current: str, default_branch: str) -> bool:
    if current == "HEAD":
        return True
    if current in PROTECTED_BRANCH_NAMES or current == default_branch:
        return True
    return not current.startswith("codex/")


def create_auto_branch(repo: Path) -> str:
    base_branch = f"codex/auto-{utc_stamp()}"
    branch = base_branch
    suffix = 2
    while ref_exists(repo, f"refs/heads/{branch}"):
        branch = f"{base_branch}-{suffix}"
        suffix += 1
    debug(f"Creating branch {branch}")
    run(["git", "switch", "-c", branch], repo, check=True)
    return branch


def ensure_codex_branch(repo: Path, current: str, default_branch: str, log_path: Path) -> str:
    if not branch_requires_codex_branch(current, default_branch):
        return current
    branch = create_auto_branch(repo)
    event(
        log_path,
        "branch_created",
        previous_branch=current,
        branch=branch,
        default_branch=default_branch,
    )
    return branch


def ensure_origin(repo: Path) -> None:
    result = run(["git", "remote", "get-url", "origin"], repo)
    if result.returncode != 0 or not result.stdout.strip():
        raise HookBlock("No Git remote named 'origin' is configured; cannot push or open a PR.")


def ensure_gh_auth(repo: Path) -> None:
    if shutil.which("gh") is None:
        raise HookBlock("GitHub CLI 'gh' was not found in PATH; cannot open or update a PR.")
    result = run(["gh", "auth", "status"], repo)
    if result.returncode != 0:
        raise HookBlock(
            "GitHub CLI is not authenticated; cannot open or update a PR.\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )


def stage_all(repo: Path) -> None:
    run(["git", "add", "-A"], repo, check=True)


def commit_staged(repo: Path, branch: str, log_path: Path) -> str:
    if run(["git", "diff", "--cached", "--quiet"], repo).returncode == 0:
        raise HookBlock("No staged changes are available to commit after git add -A.")

    subject = "chore: codex auto PR"
    paths = staged_paths(repo)
    listed = "\n".join(f"- {path}" for path in paths[:80])
    if len(paths) > 80:
        listed += f"\n- ... and {len(paths) - 80} more"
    body = (
        "Automated Codex Stop hook commit.\n\n"
        f"Branch: {branch}\n"
        f"Run log: {log_path.relative_to(repo)}\n\n"
        "Files:\n"
        f"{listed}\n"
    )
    run(["git", "commit", "-m", subject, "-m", body], repo, check=True)
    commit_sha = git_stdout(repo, ["rev-parse", "--short", "HEAD"], check=True)
    event(log_path, "commit_created", branch=branch, commit=commit_sha, paths=paths)
    return commit_sha


def fetch_origin(repo: Path, log_path: Path) -> None:
    debug("Fetching origin")
    result = run(["git", "fetch", "origin", "--prune"], repo)
    event(
        log_path,
        "fetch_finish",
        returncode=result.returncode,
        stdout_tail=tail(result.stdout, 4000),
        stderr_tail=tail(result.stderr, 4000),
    )
    if result.returncode != 0:
        raise HookBlock(
            "Failed to fetch origin.\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )


def rebase_codex_branch(repo: Path, branch: str, default_branch: str, log_path: Path) -> None:
    if not branch.startswith("codex/"):
        return
    debug(f"Rebasing {branch} onto origin/{default_branch}")
    result = run(["git", "rebase", f"origin/{default_branch}"], repo)
    event(
        log_path,
        "rebase_finish",
        branch=branch,
        returncode=result.returncode,
        stdout_tail=tail(result.stdout, 4000),
        stderr_tail=tail(result.stderr, 4000),
    )
    if result.returncode != 0:
        raise HookBlock(
            f"Failed to rebase branch {branch} onto origin/{default_branch}.\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )


def push_branch(repo: Path, branch: str, log_path: Path) -> None:
    debug(f"Pushing {branch}")
    result = run(["git", "push", "--force-with-lease", "-u", "origin", branch], repo)
    event(
        log_path,
        "push_finish",
        branch=branch,
        returncode=result.returncode,
        stdout_tail=tail(result.stdout, 4000),
        stderr_tail=tail(result.stderr, 4000),
    )
    if result.returncode != 0:
        raise HookBlock(
            f"Failed to push branch {branch}.\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )


def find_existing_pr(repo: Path, branch: str) -> dict[str, Any] | None:
    result = run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url,title",
            "--limit",
            "1",
        ],
        repo,
    )
    if result.returncode != 0:
        raise HookBlock(
            f"Failed to query existing PRs with gh.\nstdout:\n{tail(result.stdout)}\nstderr:\n{tail(result.stderr)}"
        )
    try:
        prs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise HookBlock(f"Could not parse gh PR list output: {exc}") from exc
    if isinstance(prs, list) and prs:
        first = prs[0]
        if isinstance(first, dict):
            return first
    return None


def pr_body(
    repo: Path,
    branch: str,
    base: str,
    commit_sha: str,
    log_path: Path,
    verification_report: str,
    diff_text: str,
) -> str:
    return (
        "Automated Codex PR.\n\n"
        f"- Branch: `{branch}`\n"
        f"- Base: `{base}`\n"
        f"- Commit: `{commit_sha}`\n"
        f"- Run log: `{log_path.relative_to(repo)}`\n\n"
        "Verification report:\n"
        f"{verification_report}\n\n"
        "Diff summary:\n"
        "```text\n"
        f"{diff_text}\n"
        "```\n\n"
        "Safety:\n"
        "- This hook never auto-merges.\n"
        "- This hook refuses direct commits to protected branches.\n"
    )


def create_or_update_pr(
    repo: Path,
    branch: str,
    base: str,
    commit_sha: str,
    log_path: Path,
    verification_report: str,
    diff_text: str,
) -> str:
    body = pr_body(repo, branch, base, commit_sha, log_path, verification_report, diff_text)
    title = f"Codex: {branch}"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body)
        body_file = Path(handle.name)
    try:
        existing = find_existing_pr(repo, branch)
        if existing:
            number = str(existing["number"])
            result = run(["gh", "pr", "edit", number, "--title", title, "--body-file", str(body_file)], repo)
            if result.returncode != 0:
                raise HookBlock(
                    f"Failed to update PR #{number}.\nstdout:\n{tail(result.stdout)}\nstderr:\n{tail(result.stderr)}"
                )
            url = str(existing["url"])
            event(log_path, "pr_updated", number=number, url=url)
            return url

        result = run(
            ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", str(body_file)],
            repo,
        )
        if result.returncode != 0:
            raise HookBlock(
                f"Failed to create PR.\nstdout:\n{tail(result.stdout)}\nstderr:\n{tail(result.stderr)}"
            )
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        event(log_path, "pr_created", url=url)
        return url
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


def main() -> int:
    hook_input: dict[str, Any] = {}
    log_path: Path | None = None
    repo: Path | None = None

    try:
        hook_input = read_hook_input()
        repo = repo_root_from_git(Path.cwd())
        if repo is None:
            emit("continue", "No Git repository found; stop hook skipped.")
            return 0

        debug(f"Repository root: {repo}")

        active_operations = in_progress_git_operations(repo)
        if active_operations:
            reason = "Git is mid-operation (" + ", ".join(active_operations) + "); resolve that state before finishing."
            emit("block", reason)
            return 0

        conflict_paths = unmerged_paths(repo)
        if conflict_paths:
            emit(
                "block",
                "Resolve Git conflict markers before finishing:\n"
                + "\n".join(f"- {path}" for path in conflict_paths),
            )
            return 0

        visible_changes = visible_changed_paths(repo)
        if not visible_changes:
            emit("continue", "No Git changes detected; stop hook skipped.")
            return 0

        log_path = repo / ".codex-runs" / f"stop-{utc_stamp()}.jsonl"
        event(log_path, "hook_start", input=hook_input, visible_changes=visible_changes)

        secret_paths = [path for path in visible_changes if is_sensitive_path(path)]
        if secret_paths:
            reason = (
                "Refusing to auto-commit files matching secret patterns:\n"
                + "\n".join(f"- {path}" for path in secret_paths)
                + "\nRemove them from the commit and stop again."
            )
            event(log_path, "blocked", reason=reason)
            emit("block", reason, log=str(log_path.relative_to(repo)))
            return 0

        default_branch = detect_default_branch(repo)
        current = current_branch(repo)
        branch = ensure_codex_branch(repo, current, default_branch, log_path)
        event(
            log_path,
            "changes_detected",
            current_branch=current,
            branch=branch,
            default_branch=default_branch,
            paths=visible_changes,
        )

        commands = detect_verification_commands(repo)
        verification_runs = run_verification(repo, commands, log_path)
        verification_report = build_verification_report(verification_runs, commands)

        ensure_origin(repo)
        ensure_gh_auth(repo)

        stage_all(repo)
        staged_text = diff_summary(repo)
        commit_staged(repo, branch, log_path)
        fetch_origin(repo, log_path)
        rebase_codex_branch(repo, branch, default_branch, log_path)
        final_sha = git_stdout(repo, ["rev-parse", "--short", "HEAD"], check=True)
        push_branch(repo, branch, log_path)
        pr_url = create_or_update_pr(
            repo,
            branch,
            default_branch,
            final_sha,
            log_path,
            verification_report,
            staged_text,
        )

        event(
            log_path,
            "completed",
            branch=branch,
            commit=final_sha,
            pr=pr_url,
            verification=verification_report,
            diff_summary=staged_text,
        )
        emit(
            "continue",
            f"Verified, committed, pushed, and opened or updated PR: {pr_url}",
            branch=branch,
            commit=final_sha,
            pr=pr_url,
            log=str(log_path.relative_to(repo)),
        )
        return 0
    except HookBlock as exc:
        if log_path is not None:
            event(log_path, "blocked", reason=exc.reason)
            emit("block", exc.reason, log=str(log_path.relative_to(repo)))
        else:
            emit("block", exc.reason)
        return 0
    except Exception as exc:
        message = f"Stop hook failed unexpectedly: {exc!r}. Fix the hook or repository state before stopping again."
        if log_path is not None and repo is not None:
            event(log_path, "error", error=repr(exc))
            emit("block", message, log=str(log_path.relative_to(repo)))
        else:
            emit("block", message)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
