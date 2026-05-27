#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


VERIFY_TIMEOUT_SECONDS = 900


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


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def display_cmd(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def tail(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = False,
    timeout: int | None = None,
) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    result = CommandResult(args, completed.returncode, completed.stdout, completed.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {display_cmd(args)}\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )
    return result


def repo_root(cwd: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0:
        raise SystemExit("error: run this command inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def log_event(path: Path, kind: str, **data: Any) -> None:
    append_jsonl(
        path,
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **data,
        },
    )


def write_summary(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [f"# {title}", "", *lines, ""]
    path.write_text("\n".join(content), encoding="utf-8")


def relpath_text(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def ensure_dirs(root: Path) -> None:
    for rel in (
        ".codex-runs",
        ".codex-tasks/active",
        ".codex-tasks/running",
        ".codex-tasks/pr-opened",
        ".codex-tasks/completed",
        ".codex-tasks/failed",
        "docs/exec-plans/active",
        "docs/exec-plans/completed",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)


def detect_default_branch(root: Path) -> str:
    result = run(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], root)
    if result.returncode == 0 and result.stdout.strip():
        ref = result.stdout.strip()
        return ref.split("/", 1)[1] if "/" in ref else ref

    result = run(["git", "remote", "show", "origin"], root)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            match = re.search(r"HEAD branch:\s*(\S+)", line)
            if match:
                return match.group(1)

    for candidate in ("main", "master"):
        if run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"], root).returncode == 0:
            return candidate
    return "main"


def slug(value: str, fallback: str = "task") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return cleaned[:64] or fallback


def codex_exec(root: Path, prompt: str, log_path: Path) -> int:
    if shutil.which("codex") is None:
        raise RuntimeError("codex CLI was not found in PATH")

    cmd = ["codex", "exec", "--json", "--sandbox", "workspace-write", prompt]
    log_event(log_path, "codex_start", command=cmd)
    completed = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)

    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
            append_jsonl(log_path, parsed if isinstance(parsed, dict) else {"value": parsed})
        except json.JSONDecodeError:
            log_event(log_path, "codex_stdout", line=line)

    if completed.stderr:
        log_event(log_path, "codex_stderr", text=completed.stderr)
    log_event(log_path, "codex_finish", returncode=completed.returncode)
    return completed.returncode


def command_from_string(value: str) -> list[str]:
    return shlex.split(value)


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def package_manager(root: Path, package_json: dict[str, Any]) -> str:
    declared = str(package_json.get("packageManager", ""))
    if declared.startswith("pnpm@") or (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if declared.startswith("yarn@") or (root / "yarn.lock").exists():
        return "yarn"
    if declared.startswith("bun@") or (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    return "npm"


def node_command(pm: str, script_name: str) -> list[str]:
    if pm == "yarn":
        return ["yarn", "run", script_name]
    return [pm, "run", script_name]


def pyproject_text(root: Path) -> str:
    try:
        return (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""


def python_executable() -> str:
    return shutil.which("python3") or shutil.which("python") or sys.executable


def detect_verification_commands(root: Path) -> list[VerifyCommand]:
    commands: list[VerifyCommand] = []
    package_path = root / "package.json"
    if package_path.exists():
        package = load_json(package_path)
        scripts = package.get("scripts", {})
        if isinstance(scripts, dict):
            pm = package_manager(root, package)
            for name in ("lint", "typecheck", "test"):
                script = scripts.get(name)
                if isinstance(script, str) and script.strip():
                    if name == "test" and "no test specified" in script.lower() and "exit 1" in script.lower():
                        continue
                    commands.append(VerifyCommand(f"npm:{name}", node_command(pm, name)))

    py_text = pyproject_text(root)
    has_python = bool(py_text) or any(
        (root / name).exists()
        for name in ("pytest.ini", "tox.ini", "setup.cfg", "mypy.ini", "ruff.toml", "tests")
    )
    if has_python:
        if shutil.which("ruff") and ("[tool.ruff" in py_text or (root / "ruff.toml").exists()):
            commands.append(VerifyCommand("python:lint", ["ruff", "check", "."]))
        if shutil.which("mypy") and ("[tool.mypy" in py_text or (root / "mypy.ini").exists()):
            commands.append(VerifyCommand("python:typecheck", ["mypy", "."]))
        if "[tool.pytest" in py_text or (root / "pytest.ini").exists() or (root / "tests").is_dir():
            pytest_bin = shutil.which("pytest")
            commands.append(VerifyCommand("python:test", [pytest_bin] if pytest_bin else [python_executable(), "-m", "pytest"]))
        if (root / "tox.ini").exists() and shutil.which("tox"):
            commands.append(VerifyCommand("python:tox", ["tox"]))

    seen: set[tuple[str, ...]] = set()
    unique: list[VerifyCommand] = []
    for command in commands:
        key = tuple(command.args)
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def parse_markdown_field(text: str, name: str) -> str | None:
    pattern = re.compile(rf"^\s*[-*]?\s*{re.escape(name)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip().strip("`").strip("'\"").strip()
    return None if value.upper() in {"TBD", "N/A", "NONE"} else value


def parse_verification_from_task(text: str) -> list[VerifyCommand]:
    commands: list[VerifyCommand] = []
    in_section = False
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s+verification commands\s*$", line.strip(), re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("#"):
            break
        if not in_section:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("-"):
            candidate = stripped[1:].strip()
            if candidate.startswith("`") and candidate.endswith("`"):
                candidate = candidate[1:-1]
            if candidate and candidate.upper() not in {"TBD", "NONE", "N/A"}:
                commands.append(VerifyCommand(f"task:{len(commands) + 1}", command_from_string(candidate)))
    return commands


def run_verification(root: Path, commands: list[VerifyCommand], log_path: Path) -> bool:
    if not commands:
        log_event(log_path, "verification_skipped", reason="no commands detected")
        return True

    ok = True
    for command in commands:
        log_event(log_path, "verification_start", label=command.label, command=command.args)
        result = run(command.args, root, timeout=VERIFY_TIMEOUT_SECONDS)
        log_event(
            log_path,
            "verification_finish",
            label=command.label,
            command=command.args,
            returncode=result.returncode,
            stdout_tail=tail(result.stdout),
            stderr_tail=tail(result.stderr),
        )
        if result.returncode != 0:
            ok = False
            break
    return ok


def find_task(root: Path, task_id: str) -> Path:
    names = [task_id]
    if not task_id.endswith(".md"):
        names.append(f"{task_id}.md")
    for state in ("active", "running", "failed"):
        for name in names:
            path = root / ".codex-tasks" / state / name
            if path.exists():
                return path
    raise SystemExit(f"error: task not found in active/running/failed: {task_id}")


def move_task(root: Path, source: Path, state: str, note: str | None = None) -> Path:
    destination = root / ".codex-tasks" / state / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    if note:
        text += f"\n\n## Orchestrator Note\n\n{note}\n"
    destination.write_text(text, encoding="utf-8")
    if source.resolve() != destination.resolve():
        source.unlink()
    return destination


def worktree_path(root: Path, task_id: str) -> Path:
    return root.parent / f"{root.name}.codex-worktrees" / slug(task_id)


def worktree_inventory(root: Path) -> dict[Path, str | None]:
    result = run(["git", "worktree", "list", "--porcelain"], root, check=True)
    inventory: dict[Path, str | None] = {}
    current_path: Path | None = None
    current_branch: str | None = None

    for line in result.stdout.splitlines():
        if not line:
            if current_path is not None:
                inventory[current_path] = current_branch
            current_path = None
            current_branch = None
            continue

        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1]).resolve()
        elif line.startswith("branch "):
            ref = line.split(" ", 1)[1].strip()
            current_branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref

    if current_path is not None:
        inventory[current_path] = current_branch

    return inventory


def worktree_branch_path(root: Path, branch: str) -> Path | None:
    for path, current_branch in worktree_inventory(root).items():
        if current_branch == branch:
            return path
    return None


def branch_exists(root: Path, branch: str) -> bool:
    return run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], root).returncode == 0


def remote_ref_exists(root: Path, branch: str) -> bool:
    return run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], root).returncode == 0


def ensure_worktree(root: Path, path: Path, branch: str, base_branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inventory = worktree_inventory(root)
    resolved_path = path.resolve()

    if resolved_path in inventory:
        current_branch = inventory[resolved_path]
        if current_branch != branch:
            raise RuntimeError(
                f"worktree path already exists for branch {current_branch or 'detached'}: {path}"
            )
        return

    if path.exists():
        raise RuntimeError(f"worktree path already exists on disk but is not registered with git: {path}")

    occupied_path = worktree_branch_path(root, branch)
    if occupied_path is not None:
        raise RuntimeError(
            f"branch {branch} is already checked out in worktree {occupied_path}; refusing to reuse it"
        )

    if not branch.startswith("codex/"):
        raise RuntimeError(f"refusing to create non-codex branch: {branch}")

    base_ref = f"origin/{base_branch}" if remote_ref_exists(root, base_branch) else base_branch
    if branch_exists(root, branch):
        run(["git", "worktree", "add", str(path), branch], root, check=True)
    else:
        run(["git", "worktree", "add", "-b", branch, str(path), base_ref], root, check=True)


def commit_all(root: Path, message: str) -> str | None:
    run(["git", "add", "--all", "--", "."], root, check=True)
    if run(["git", "diff", "--cached", "--quiet"], root).returncode == 0:
        return None
    run(["git", "commit", "-m", message], root, check=True)
    return run(["git", "rev-parse", "--short", "HEAD"], root, check=True).stdout.strip()


def ensure_gh() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("gh CLI was not found in PATH")


def ensure_gh_auth(root: Path) -> None:
    ensure_gh()
    result = run(["gh", "auth", "status"], root)
    if result.returncode != 0:
        raise RuntimeError(
            "gh CLI is not authenticated; cannot open or update a PR.\n"
            f"stdout:\n{tail(result.stdout)}\n"
            f"stderr:\n{tail(result.stderr)}"
        )


def ensure_origin(root: Path) -> None:
    if run(["git", "remote", "get-url", "origin"], root).returncode != 0:
        raise RuntimeError("remote 'origin' is required to push and open a PR")


def push_branch(root: Path, branch: str) -> None:
    ensure_origin(root)
    run(["git", "push", "-u", "origin", branch], root, check=True)


def find_existing_pr(root: Path, branch: str) -> dict[str, Any] | None:
    result = run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,url,title", "--limit", "1"],
        root,
        check=True,
    )
    prs = json.loads(result.stdout or "[]")
    return prs[0] if isinstance(prs, list) and prs else None


def open_or_update_pr(root: Path, branch: str, base: str, title: str, body: str) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body)
        body_path = Path(handle.name)
    try:
        existing = find_existing_pr(root, branch)
        if existing:
            run(["gh", "pr", "edit", str(existing["number"]), "--title", title, "--body-file", str(body_path)], root, check=True)
            return str(existing["url"])
        result = run(
            ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", str(body_path)],
            root,
            check=True,
        )
        output = result.stdout.strip().splitlines()
        if not output:
            raise RuntimeError("gh pr create succeeded but returned no URL")
        return output[-1]
    finally:
        try:
            body_path.unlink()
        except OSError:
            pass


def command_plan(args: argparse.Namespace) -> int:
    root = repo_root(Path.cwd())
    ensure_dirs(root)
    epic_id = f"EPIC-{utc_stamp()}"
    run_id = f"{utc_stamp()}-plan"
    log_path = root / ".codex-runs" / f"{run_id}.jsonl"
    summary_path = root / ".codex-runs" / f"{run_id}-summary.md"
    prompt = f"""
You are in planner mode. Do not implement business logic.

Requirement:
{args.requirement}

Create a concise execution plan at docs/exec-plans/active/{epic_id}.md.
Create one or more task files under .codex-tasks/active/ using TASK-001.md, TASK-002.md, and so on.
Use .codex-tasks/active/TASK-template.md as the task format.
Each task must include parent epic, goal, scope, allowed files, forbidden files, acceptance criteria, verification commands, branch, base branch, and output requirements.
Use codex/... branch names.
Keep tasks small enough to run independently in a worktree.
Do not edit application code.
"""
    rc = codex_exec(root, prompt.strip(), log_path)
    write_summary(
        summary_path,
        f"{epic_id} Plan",
        [
            f"- Requirement: `{args.requirement}`",
            f"- Log: `{log_path.relative_to(root)}`",
            f"- Exit code: `{rc}`",
        ],
    )
    print(f"planner exit code: {rc}")
    print(f"log: {log_path.relative_to(root)}")
    return rc


def command_run(args: argparse.Namespace) -> int:
    root = repo_root(Path.cwd())
    ensure_dirs(root)
    task_path = find_task(root, args.task)
    task_id = task_path.stem
    task_text = task_path.read_text(encoding="utf-8")
    default_branch = detect_default_branch(root)
    branch = parse_markdown_field(task_text, "Branch") or f"codex/{slug(task_id)}"
    base_branch = parse_markdown_field(task_text, "Base branch") or default_branch
    if not branch.startswith("codex/"):
        branch = f"codex/{slug(branch)}"

    run_id = f"{utc_stamp()}-{task_id}"
    summary_path = root / ".codex-runs" / f"{run_id}-summary.md"
    running_task = move_task(root, task_path, "running", f"Started at {utc_stamp()} on branch `{branch}`.")
    wt_path = worktree_path(root, task_id)
    log_path = root / ".codex-runs" / f"{run_id}.jsonl"
    try:
        ensure_worktree(root, wt_path, branch, base_branch)
        ensure_dirs(wt_path)
        log_path = wt_path / ".codex-runs" / f"{run_id}.jsonl"
        summary_path = wt_path / ".codex-runs" / f"{run_id}-summary.md"
        wt_task = wt_path / ".codex-tasks" / "running" / running_task.name
        wt_task.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(running_task, wt_task)

        prompt = f"""
You are a Codex worker running non-interactively in a task worktree.

Execute exactly this task:

{task_text}

Rules:
- Stay on branch {branch}.
- Modify only files allowed by the task.
- Do not merge branches.
- Do not open a PR; the orchestrator will do that after verification.
- Save any durable notes in the task file or docs/exec-plans/completed/.
- Leave the repository ready for verification.
"""
        rc = codex_exec(wt_path, prompt.strip(), log_path)
        if rc != 0:
            write_summary(summary_path, f"{task_id} Failed", [f"- Codex exit code: `{rc}`", f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", f"Codex exited with code {rc}. Log: `{log_path}`.")
            print(f"task failed: {task_id}")
            print(f"log: {log_path}")
            return rc

        commands = parse_verification_from_task(task_text) or detect_verification_commands(wt_path)
        verification_ok = run_verification(wt_path, commands, log_path)
        if not verification_ok:
            write_summary(summary_path, f"{task_id} Failed Verification", [f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", f"Verification failed. Log: `{log_path}`.")
            print(f"verification failed for {task_id}")
            print(f"log: {log_path}")
            return 1

        ensure_origin(wt_path)
        ensure_gh_auth(wt_path)

        commit_sha = commit_all(wt_path, f"{task_id}: Codex worker changes")
        if commit_sha is None:
            write_summary(summary_path, f"{task_id} Failed", [f"- Reason: `No changes were produced`", f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", "No changes were produced, so no PR was opened.")
            print(f"no changes to commit for {task_id}")
            return 1

        push_branch(wt_path, branch)
        verification_lines = (
            "\n".join(f"- PASS: `{display_cmd(command.args)}`" for command in commands)
            if commands
            else "- No verification commands detected."
        )
        body = (
            f"Task: `{task_id}`\n\n"
            f"Branch: `{branch}`\n"
            f"Base: `{base_branch}`\n"
            f"Commit: `{commit_sha}`\n"
            f"Run log: `{log_path.relative_to(wt_path)}`\n\n"
            f"Verification:\n{verification_lines}\n\n"
            "This PR was opened by the Codex orchestrator. It will not auto-merge.\n"
        )
        pr_url = open_or_update_pr(wt_path, branch, base_branch, f"{task_id}: Codex changes", body)
        write_summary(
            summary_path,
            f"{task_id} Run Summary",
            [
                f"- Branch: `{branch}`",
                f"- Base branch: `{base_branch}`",
                f"- Commit: `{commit_sha}`",
                f"- PR: `{pr_url}`",
                f"- Log: `{relpath_text(log_path, wt_path)}`",
            ],
        )
        move_task(root, running_task, "pr-opened", f"PR opened or updated: {pr_url}")
        print(f"task complete: {task_id}")
        print(f"branch: {branch}")
        print(f"commit: {commit_sha}")
        print(f"pr: {pr_url}")
        print(f"log: {log_path}")
        return 0
    except Exception as exc:
        write_summary(
            summary_path,
            f"{task_id} Failed",
            [
                f"- Error: `{type(exc).__name__}: {exc}`",
                f"- Log: `{relpath_text(log_path, wt_path if wt_path.exists() else root)}`",
            ],
        )
        move_task(root, running_task, "failed", f"{type(exc).__name__}: {exc}. Log: `{log_path}`.")
        print(f"task failed: {task_id}")
        print(f"error: {type(exc).__name__}: {exc}")
        print(f"log: {log_path}")
        return 1


def command_status(args: argparse.Namespace) -> int:
    root = repo_root(Path.cwd())
    ensure_dirs(root)
    for state in ("active", "running", "pr-opened", "completed", "failed"):
        paths = sorted((root / ".codex-tasks" / state).glob("*.md"))
        paths = [path for path in paths if path.name != "TASK-template.md"]
        print(f"{state}: {len(paths)}")
        for path in paths:
            print(f"  - {path.name}")
    return 0


def command_integrate(args: argparse.Namespace) -> int:
    root = repo_root(Path.cwd())
    ensure_gh()
    cmd = ["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName,baseRefName,url,isDraft", "--limit", "50"]
    if args.epic:
        cmd.extend(["--search", args.epic])
    result = run(cmd, root, check=True)
    prs = json.loads(result.stdout or "[]")
    codex_prs = [pr for pr in prs if str(pr.get("headRefName", "")).startswith("codex/")]
    if not codex_prs:
        print("no open codex/... PRs found")
        return 0

    print("open codex PRs:")
    for pr in codex_prs:
        print(f"  #{pr['number']} {pr['title']} [{pr['headRefName']} -> {pr['baseRefName']}]")
        print(f"     {pr['url']}")

    print("\nConservative next steps:")
    print("  gh pr checks <number>")
    print("  gh pr view <number> --web")
    print("  gh pr merge <number> --squash --delete-branch")
    print("\nThe orchestrator MVP does not auto-merge.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex task orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="plan an epic and task files")
    plan_parser.add_argument("requirement", help="requirement to plan")
    plan_parser.set_defaults(func=command_plan)

    run_parser = subparsers.add_parser("run", help="run one task in a worktree")
    run_parser.add_argument("task", help="task id, for example TASK-001")
    run_parser.set_defaults(func=command_run)

    status_parser = subparsers.add_parser("status", help="show task status")
    status_parser.set_defaults(func=command_status)

    integrate_parser = subparsers.add_parser("integrate", help="list PRs for conservative integration")
    integrate_parser.add_argument("epic", nargs="?", help="optional epic id to search")
    integrate_parser.set_defaults(func=command_integrate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
