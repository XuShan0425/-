#!/usr/bin/env python3
"""Agent task orchestrator.

Drives the plan -> run -> status flow on top of :mod:`agent_core`.

    python orchestrator/agent-team.py plan  "add user auth"
    python orchestrator/agent-team.py run   TASK-001
    python orchestrator/agent-team.py status
    python orchestrator/agent-team.py integrate [EPIC-XXX]

In autopilot mode ``run`` executes a task in an isolated worktree via a
headless Claude Code session, verifies, commits, pushes, opens a PR, then
auto-merges it. The task ends in ``completed``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Bootstrap: let ``import agent_core`` resolve to template/lib/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import agent_core as core  # noqa: E402


TASK_STATES = ("active", "running", "pr-opened", "completed", "failed")


# --------------------------------------------------------------------------- #
# Headless Claude execution
# --------------------------------------------------------------------------- #

def claude_exec(cwd: Path, prompt: str, log_path: Path) -> int:
    """Run a headless Claude Code session (full autonomy, no prompts).

    Sets ``AGENT_TEAM_WORKER`` so the project Stop hook steps aside — the
    orchestrator owns verification / commit / push / merge for this session.
    """
    if shutil.which("claude") is None:
        raise core.AgentError("claude CLI was not found in PATH")
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    env = {**os.environ, "AGENT_TEAM_WORKER": "1"}
    core.log_event(log_path, "claude_start", command=cmd)
    completed = subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True)
    core.log_event(log_path, "claude_stdout", text=core.tail(completed.stdout))
    if completed.stderr:
        core.log_event(log_path, "claude_stderr", text=core.tail(completed.stderr))
    core.log_event(log_path, "claude_finish", returncode=completed.returncode)
    return completed.returncode


# --------------------------------------------------------------------------- #
# Filesystem / task state
# --------------------------------------------------------------------------- #

def ensure_dirs(root: Path) -> None:
    for rel in (
        ".agent-runs",
        ".agent-tasks/active",
        ".agent-tasks/running",
        ".agent-tasks/pr-opened",
        ".agent-tasks/completed",
        ".agent-tasks/failed",
        "docs/exec-plans/active",
        "docs/exec-plans/completed",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)


def move_task(root: Path, source: Path, state: str, note: str | None = None) -> Path:
    destination = root / ".agent-tasks" / state / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    if note:
        text += f"\n\n## Orchestrator Note\n\n{note}\n"
    destination.write_text(text, encoding="utf-8")
    if source.resolve() != destination.resolve():
        source.unlink()
    return destination


def find_task(root: Path, task_id: str) -> Path:
    names = [task_id, f"{task_id}.md"] if not task_id.endswith(".md") else [task_id]
    for state in ("active", "running", "failed"):
        for name in names:
            path = root / ".agent-tasks" / state / name
            if path.exists():
                return path
    raise core.AgentError(f"task not found in active/running/failed: {task_id}")


def relpath_text(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def write_summary(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([f"# {title}", "", *lines, ""]), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Worktree isolation
# --------------------------------------------------------------------------- #

def worktree_path(root: Path, task_id: str) -> Path:
    return root.parent / f"{root.name}.agent-worktrees" / core.slug(task_id)


def worktree_inventory(root: Path) -> dict[Path, str | None]:
    result = core.run(["git", "worktree", "list", "--porcelain"], root, check=True)
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


def ensure_worktree(root: Path, path: Path, branch: str, base_branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inventory = worktree_inventory(root)
    resolved_path = path.resolve()

    if resolved_path in inventory:
        current_branch = inventory[resolved_path]
        if current_branch != branch:
            raise core.AgentError(
                f"worktree path already exists for branch {current_branch or 'detached'}: {path}"
            )
        return

    if path.exists():
        raise core.AgentError(f"worktree path already exists on disk but is not registered with git: {path}")

    occupied = worktree_branch_path(root, branch)
    if occupied is not None:
        raise core.AgentError(
            f"branch {branch} is already checked out in worktree {occupied}; refusing to reuse it"
        )

    if not branch.startswith("agent/"):
        raise core.AgentError(f"refusing to create non-agent branch: {branch}")

    base_ref = f"origin/{base_branch}" if core.remote_ref_exists(root, base_branch) else base_branch
    if core.branch_exists(root, branch):
        core.run(["git", "worktree", "add", str(path), branch], root, check=True)
    else:
        core.run(["git", "worktree", "add", "-b", branch, str(path), base_ref], root, check=True)


def commit_all(root: Path, message: str) -> str | None:
    core.run(["git", "add", "--all", "--", "."], root, check=True)
    if core.run(["git", "diff", "--cached", "--quiet"], root).returncode == 0:
        return None
    core.run(["git", "commit", "-m", message], root, check=True)
    return core.git_stdout(root, ["rev-parse", "--short", "HEAD"], check=True)


# --------------------------------------------------------------------------- #
# Markdown task parsing
# --------------------------------------------------------------------------- #

def parse_markdown_field(text: str, name: str) -> str | None:
    pattern = re.compile(rf"^\s*[-*]?\s*{re.escape(name)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip().strip("`").strip("'\"").strip()
    return None if value.upper() in {"TBD", "N/A", "NONE"} else value


def parse_verification_from_task(text: str) -> list[core.VerifyCommand]:
    commands: list[core.VerifyCommand] = []
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
                commands.append(core.VerifyCommand(f"task:{len(commands) + 1}", shlex.split(candidate)))
    return commands


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def command_plan(args: argparse.Namespace) -> int:
    root = core.repo_root(Path.cwd())
    ensure_dirs(root)
    epic_id = f"EPIC-{core.utc_stamp()}"
    run_id = f"{core.utc_stamp()}-plan"
    log_path = root / ".agent-runs" / f"{run_id}.jsonl"
    summary_path = root / ".agent-runs" / f"{run_id}-summary.md"
    prompt = f"""
You are in planner mode. Do not implement business logic.

Requirement:
{args.requirement}

Create a concise execution plan at docs/exec-plans/active/{epic_id}.md.
Create one or more task files under .agent-tasks/active/ using TASK-001.md, TASK-002.md, and so on.
Use .agent-tasks/active/TASK-template.md as the task format.
Each task must include parent epic, goal, scope, allowed files, forbidden files, acceptance criteria, verification commands, branch, base branch, and output requirements.
Use agent/... branch names.
Keep tasks small enough to run independently in a worktree.
Do not edit application code.
"""
    rc = claude_exec(root, prompt.strip(), log_path)
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
    root = core.repo_root(Path.cwd())
    ensure_dirs(root)
    task_path = find_task(root, args.task)
    task_id = task_path.stem
    task_text = task_path.read_text(encoding="utf-8")
    default_branch = core.detect_default_branch(root)
    branch = parse_markdown_field(task_text, "Branch") or f"agent/{core.slug(task_id)}"
    base_branch = parse_markdown_field(task_text, "Base branch") or default_branch
    if not branch.startswith("agent/"):
        branch = f"agent/{core.slug(branch)}"

    run_id = f"{core.utc_stamp()}-{task_id}"
    running_task = move_task(root, task_path, "running", f"Started at {core.utc_stamp()} on branch `{branch}`.")
    wt_path = worktree_path(root, task_id)
    # Default to root-level artifacts; reassigned to worktree-level once it exists.
    log_path = root / ".agent-runs" / f"{run_id}.jsonl"
    summary_path = root / ".agent-runs" / f"{run_id}-summary.md"

    try:
        ensure_worktree(root, wt_path, branch, base_branch)
        ensure_dirs(wt_path)
        log_path = wt_path / ".agent-runs" / f"{run_id}.jsonl"
        summary_path = wt_path / ".agent-runs" / f"{run_id}-summary.md"
        wt_task = wt_path / ".agent-tasks" / "running" / running_task.name
        wt_task.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(running_task, wt_task)

        prompt = f"""
You are a Claude Code worker running non-interactively in a task worktree.

Execute exactly this task:

{task_text}

Rules:
- Stay on branch {branch}.
- Modify only files allowed by the task.
- Do not merge branches or open a PR; the orchestrator verifies, commits, pushes, opens a PR, and auto-merges after verification passes.
- Save durable notes in the task file or docs/exec-plans/completed/.
- Leave the repository ready for verification.
"""
        rc = claude_exec(wt_path, prompt.strip(), log_path)
        if rc != 0:
            write_summary(summary_path, f"{task_id} Failed", [f"- Claude exit code: `{rc}`", f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", f"Claude exited with code {rc}. Log: `{log_path}`.")
            print(f"task failed: {task_id}\nlog: {log_path}")
            return rc

        commands = parse_verification_from_task(task_text) or core.detect_verification_commands(wt_path)
        results, ok = core.run_verification(wt_path, commands, log_path)
        if not ok:
            failed = next((r for r in results if r.returncode != 0), None)
            detail = ""
            if failed:
                detail = f"\n\n{core.display_cmd(failed.command.args)}\nstdout:\n{core.tail(failed.stdout)}\nstderr:\n{core.tail(failed.stderr)}"
            write_summary(summary_path, f"{task_id} Failed Verification", [f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", f"Verification failed.{detail} Log: `{log_path}`.")
            print(f"verification failed for {task_id}\nlog: {log_path}")
            return 1

        core.ensure_origin(wt_path)
        core.ensure_gh_auth(wt_path)

        commit_sha = commit_all(wt_path, f"{task_id}: agent worker changes")
        if commit_sha is None:
            write_summary(summary_path, f"{task_id} Failed", [f"- Reason: `No changes were produced`", f"- Log: `{relpath_text(log_path, wt_path)}`"])
            move_task(root, running_task, "failed", "No changes were produced, so no PR was opened.")
            print(f"no changes to commit for {task_id}")
            return 1

        core.push_branch(wt_path, branch)
        report = core.verification_report(results, commands)
        body = (
            f"Task: `{task_id}`\n\n"
            f"Branch: `{branch}`\nBase: `{base_branch}`\nCommit: `{commit_sha}`\n"
            f"Run log: `{log_path.relative_to(wt_path)}`\n\n"
            f"Verification:\n{report}\n\n"
            "Opened and auto-merged by the agent orchestrator (autopilot mode).\n"
        )
        pr_url = core.open_or_update_pr(wt_path, branch, base_branch, f"{task_id}: agent changes", body)
        core.merge_pr(wt_path, pr_url)

        write_summary(
            summary_path,
            f"{task_id} Run Summary",
            [
                f"- Branch: `{branch}` (merged & deleted)",
                f"- Base branch: `{base_branch}`",
                f"- Commit: `{commit_sha}`",
                f"- PR (auto-merged): `{pr_url}`",
                f"- Log: `{relpath_text(log_path, wt_path)}`",
            ],
        )
        move_task(root, running_task, "completed", f"Auto-merged into `{base_branch}`: {pr_url}")
        print(f"task complete: {task_id}")
        print(f"branch: {branch} (merged)")
        print(f"commit: {commit_sha}")
        print(f"pr (auto-merged): {pr_url}")
        print(f"log: {log_path}")
        return 0
    except core.AgentError as exc:
        write_summary(summary_path, f"{task_id} Failed", [f"- Error: `{exc}`", f"- Log: `{relpath_text(log_path, wt_path if wt_path.exists() else root)}`"])
        move_task(root, running_task, "failed", str(exc))
        print(f"task failed: {task_id}\nerror: {exc}")
        return 1
    except Exception as exc:
        write_summary(summary_path, f"{task_id} Failed", [f"- Error: `{type(exc).__name__}: {exc}`"])
        move_task(root, running_task, "failed", f"{type(exc).__name__}: {exc}")
        print(f"task failed: {task_id}\nerror: {type(exc).__name__}: {exc}")
        return 1


def command_status(args: argparse.Namespace) -> int:
    root = core.repo_root(Path.cwd())
    ensure_dirs(root)
    for state in TASK_STATES:
        paths = sorted(p for p in (root / ".agent-tasks" / state).glob("*.md") if p.name != "TASK-template.md")
        print(f"{state}: {len(paths)}")
        for path in paths:
            print(f"  - {path.name}")
    return 0


def command_integrate(args: argparse.Namespace) -> int:
    root = core.repo_root(Path.cwd())
    core.ensure_gh()
    cmd = ["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName,baseRefName,url", "--limit", "50"]
    if args.epic:
        cmd.extend(["--search", args.epic])
    result = core.run(cmd, root, check=True)
    prs = json.loads(result.stdout or "[]")
    stuck = [pr for pr in prs if str(pr.get("headRefName", "")).startswith("agent/")]
    if not stuck:
        print("no open agent/... PRs — all tasks auto-merge on completion.")
        return 0
    print("open agent/ PRs (expected to auto-merge; these did not):")
    for pr in stuck:
        print(f"  #{pr['number']} {pr['title']} [{pr['headRefName']} -> {pr['baseRefName']}]")
        print(f"     {pr['url']}")
    print("\nRetry a merge with:  gh pr merge <number> --squash --delete-branch")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent task orchestrator (autopilot)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="plan an epic and task files")
    p.add_argument("requirement", help="requirement to plan")
    p.set_defaults(func=command_plan)

    p = sub.add_parser("run", help="run one task in a worktree, then auto-merge")
    p.add_argument("task", help="task id, for example TASK-001")
    p.set_defaults(func=command_run)

    p = sub.add_parser("status", help="show task status")
    p.set_defaults(func=command_status)

    p = sub.add_parser("integrate", help="list agent/ PRs that failed to auto-merge")
    p.add_argument("epic", nargs="?", help="optional epic id to search")
    p.set_defaults(func=command_integrate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
