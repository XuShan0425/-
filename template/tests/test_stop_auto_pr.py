from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASH = shutil.which("bash")
_SKIP_NO_BASH = "bash not available on this platform"


TEMPLATE_DIR = Path(__file__).resolve().parents[1]
LIB_DIR = TEMPLATE_DIR / "lib"
HOOK_PATH = TEMPLATE_DIR / ".claude" / "hooks" / "stop-auto-pr.py"


def _load_module(name: str, path: Path):
    """Load a Python module from *path* registered as *name* in sys.modules."""
    sys.path.insert(0, str(path.parent)) if name == "agent_core" else None
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Ensure lib/ is importable for the hook's ``import agent_core``.
sys.path.insert(0, str(LIB_DIR))

core = _load_module("agent_core", LIB_DIR / "agent_core.py")
hook = _load_module("stop_auto_pr", HOOK_PATH)


# =================================================================== #
# agent_core — the shared library
# =================================================================== #

class AgentCoreTests(unittest.TestCase):

    # -- secret guardrail -------------------------------------------- #

    def test_is_sensitive_path(self) -> None:
        self.assertTrue(core.is_sensitive_path(".env"))
        self.assertTrue(core.is_sensitive_path(".env.local"))
        self.assertTrue(core.is_sensitive_path("config/.env.example"))
        self.assertTrue(core.is_sensitive_path("app/secrets/private.key"))
        self.assertTrue(core.is_sensitive_path("app/api-secret.json"))
        self.assertTrue(core.is_sensitive_path("app/api-token.json"))
        self.assertFalse(core.is_sensitive_path("docs/readme.md"))
        self.assertFalse(core.is_sensitive_path("src/settings.py"))

    def test_is_runtime_artifact(self) -> None:
        self.assertTrue(core.is_runtime_artifact(".agent-runs/stop-123.jsonl"))
        self.assertTrue(core.is_runtime_artifact(".agent-runs"))
        self.assertFalse(core.is_runtime_artifact("src/app.py"))
        self.assertFalse(core.is_runtime_artifact("agent-runs/foo"))

    # -- verification detection -------------------------------------- #

    def test_detect_node_scripts_skipping_noop_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                json.dumps({
                    "scripts": {
                        "test": "echo \"Error: no test specified\" && exit 1",
                        "lint": "eslint .",
                    }
                }),
                encoding="utf-8",
            )
            commands = core.detect_verification_commands(repo)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].args, ["npm", "run", "lint"])

    def test_detect_prefers_pnpm_and_includes_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                json.dumps({
                    "name": "demo",
                    "scripts": {
                        "lint": "eslint .",
                        "typecheck": "tsc --noEmit",
                        "test": "vitest",
                    },
                }),
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
            (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

            def fake_which(name: str) -> str | None:
                return {"ruff": "ruff", "pytest": "pytest", "mypy": None, "tox": None}.get(name)

            with mock.patch.object(core.shutil, "which", side_effect=fake_which):
                commands = core.detect_verification_commands(repo)

        self.assertEqual(
            [c.args for c in commands],
            [
                ["pnpm", "run", "lint"],
                ["pnpm", "run", "typecheck"],
                ["pnpm", "run", "test"],
                ["ruff", "check", "."],
                ["pytest"],
            ],
        )

    def test_detect_mypy_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n", encoding="utf-8")
            (repo / "tests").mkdir()

            def fake_which(name: str) -> str | None:
                return {"mypy": "/usr/bin/mypy", "ruff": None, "pytest": None}.get(name)

            with mock.patch.object(core.shutil, "which", side_effect=fake_which):
                commands = core.detect_verification_commands(repo)

        labels = [c.label for c in commands]
        self.assertIn("python:mypy", labels)

    # -- verification run -------------------------------------------- #

    def test_run_verification_passes_when_no_commands(self) -> None:
        results, ok = core.run_verification(Path("."), [])
        self.assertTrue(ok)
        self.assertEqual(results, [])

    def test_run_verification_fails_on_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # Create a marker file so the "command" can check the cwd exists.
            (repo / "marker.txt").touch()
            commands = [core.VerifyCommand("test:fail", ["python", "-c", "import sys; sys.exit(1)"])]
            results, ok = core.run_verification(repo, commands)
        self.assertFalse(ok)
        self.assertEqual(results[0].returncode, 1)

    # -- verification report ----------------------------------------- #

    def test_verification_report_formatting(self) -> None:
        commands = [
            core.VerifyCommand("node:lint", ["npm", "run", "lint"]),
            core.VerifyCommand("python:pytest", ["pytest"]),
        ]
        from agent_core import VerificationResult
        results = [
            VerificationResult(commands[0], 0, "", ""),
            VerificationResult(commands[1], 1, "FAIL\n", ""),
        ]
        report = core.verification_report(results, commands)
        self.assertIn("PASS: `npm run lint`", report)
        self.assertIn("FAIL: `pytest`", report)


# =================================================================== #
# stop-auto-pr hook (protocol + integration with core)
# =================================================================== #

class HookProtocolTests(unittest.TestCase):

    def test_done_exits_zero_with_message(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            hook.done("all good")
        self.assertEqual(ctx.exception.code, 0)

    def test_done_exits_zero_without_message(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            hook.done()
        self.assertEqual(ctx.exception.code, 0)

    def test_block_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            hook.block("bad secrets")
        self.assertEqual(ctx.exception.code, 2)

    def test_hook_shares_core_sensitive_path_logic(self) -> None:
        # The hook imports agent_core; verify it delegates correctly.
        self.assertTrue(core.is_sensitive_path(".env"))
        self.assertFalse(core.is_sensitive_path("README.md"))

    def test_hook_runtime_artifact_path(self) -> None:
        self.assertTrue(core.is_runtime_artifact(".agent-runs/stop-abc.jsonl"))
        self.assertFalse(core.is_runtime_artifact("src/main.py"))


# =================================================================== #
# orchestrator (lightweight: just verify import + CLI parsing)
# =================================================================== #

class OrchestratorTests(unittest.TestCase):

    def test_import_succeeds(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_team",
            str(TEMPLATE_DIR / "orchestrator" / "agent-team.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["agent_team"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        self.assertTrue(hasattr(mod, "build_parser"))
        parser = mod.build_parser()
        # Verify all subcommands are present via choices dict.
        sub_action = next(
            a for a in parser._actions
            if a.__class__.__name__ == "_SubParsersAction"
        )
        self.assertEqual(set(sub_action.choices), {"plan", "run", "status", "integrate"})

    def test_parse_verification_from_task(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "agent_team",
            str(TEMPLATE_DIR / "orchestrator" / "agent-team.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["agent_team"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        text = "## Verification Commands\n\n- `npm test`\n- `ruff check .`\n"
        cmds = mod.parse_verification_from_task(text)
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0].args, ["npm", "test"])
        self.assertEqual(cmds[1].args, ["ruff", "check", "."])


# =================================================================== #
# install.sh (dry-run)
# =================================================================== #

class InstallScriptTests(unittest.TestCase):

    @unittest.skipUnless(BASH, _SKIP_NO_BASH)
    def test_install_sh_is_valid_bash(self) -> None:
        script = TEMPLATE_DIR.parent / "install.sh"
        self.assertTrue(script.exists(), f"install.sh not found at {script}")
        result = subprocess.run(
            [BASH, "-n", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, f"bash -n failed: {result.stderr}")

    @unittest.skipUnless(BASH, _SKIP_NO_BASH)
    def test_install_skills_dry_run(self) -> None:
        script = TEMPLATE_DIR / "install-skills.sh"
        self.assertTrue(script.exists())
        result = subprocess.run(
            [BASH, str(script), "--dry-run"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, f"dry-run failed: {result.stderr}\n{result.stdout}")
        self.assertIn("~/.claude/skills/", result.stdout)


if __name__ == "__main__":
    unittest.main()
