from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HOOK_PATH = Path(__file__).resolve().parents[1] / ".codex/hooks/stop_auto_pr.py"


def load_hook_module():
    spec = importlib.util.spec_from_file_location("stop_auto_pr_hook", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load hook module from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = load_hook_module()


class StopAutoPrTests(unittest.TestCase):
    def test_sensitive_path_patterns_match_requested_files(self) -> None:
        self.assertTrue(hook.is_sensitive_path(".env"))
        self.assertTrue(hook.is_sensitive_path(".env.local"))
        self.assertTrue(hook.is_sensitive_path("config/.env.example"))
        self.assertTrue(hook.is_sensitive_path("app/secrets/private.key"))
        self.assertTrue(hook.is_sensitive_path("app/api-secret.json"))
        self.assertTrue(hook.is_sensitive_path("app/api-token.json"))
        self.assertFalse(hook.is_sensitive_path("docs/readme.md"))

    def test_runtime_artifacts_are_ignored(self) -> None:
        self.assertTrue(hook.is_runtime_artifact(".codex-runs/stop-123.jsonl"))
        self.assertFalse(hook.is_runtime_artifact("src/app.py"))

    def test_detect_verification_commands_prefers_package_manager_and_python_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "name": "demo",
                        "scripts": {
                            "lint": "eslint .",
                            "typecheck": "tsc --noEmit",
                            "test": "vitest",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
            (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

            def fake_which(name: str) -> str | None:
                return {
                    "ruff": "ruff",
                    "pytest": "pytest",
                }.get(name)

            with mock.patch.object(hook.shutil, "which", side_effect=fake_which):
                commands = hook.detect_verification_commands(repo)

        self.assertEqual(
            [command.args for command in commands],
            [
                ["pnpm", "run", "lint"],
                ["pnpm", "run", "typecheck"],
                ["pnpm", "run", "test"],
                ["ruff", "check", "."],
                ["pytest"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
