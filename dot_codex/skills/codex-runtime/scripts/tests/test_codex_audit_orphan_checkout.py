from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "codex-audit-orphan-checkout"
LOADER = importlib.machinery.SourceFileLoader("codex_audit_orphan_checkout", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = MODULE
LOADER.exec_module(MODULE)


class AuditOrphanCheckoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.repository = self.base / "repository"
        self.orphan = self.base / "orphan"
        self.repository.mkdir()
        self.orphan.mkdir()
        self.git("init", "--quiet")
        for name, text in {
            "api/match.py": "match\n",
            "api/modified.py": "before\n",
            "project/match.py": "project\n",
        }.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Audit Fixture",
            "-c",
            "user.email=audit@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def write(self, path: str, text: str) -> None:
        target = self.orphan / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def audit(self, *, max_files: int = 100, max_hash_bytes: int = 1024):
        return MODULE.audit(
            self.orphan,
            self.repository,
            max_files=max_files,
            max_hash_bytes=max_hash_bytes,
        )

    def test_main_requires_explicit_repository(self) -> None:
        self.write("api/match.py", "match\n")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.orphan)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--repository", result.stderr)
        self.assertEqual((self.orphan / "api" / "match.py").read_text(), "match\n")

    def test_main_audits_explicit_repository(self) -> None:
        self.write("api/match.py", "match\n")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.orphan),
                "--repository",
                str(self.repository),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["repository"], str(self.repository))
        self.assertEqual(payload["root"], str(self.orphan))
        self.assertEqual(payload["matched"], 1)

    def test_distinguishes_matches_modified_and_untracked(self) -> None:
        self.write("api/match.py", "match\n")
        self.write("api/modified.py", "after\n")
        self.write("api/new.py", "new\n")
        self.write("project/match.py", "project\n")
        result = self.audit()
        self.assertTrue(result.complete)
        self.assertEqual(result.matched, 2)
        self.assertEqual(result.modified, ["api/modified.py"])
        self.assertEqual(result.untracked, ["api/new.py"])

    def test_does_not_walk_real_nested_repository(self) -> None:
        self.write("api/nested/.git", "gitdir: /not/entered\n")
        self.write("api/nested/valuable.txt", "preserve\n")
        result = self.audit()
        self.assertEqual(result.protected, ["api/nested"])
        self.assertFalse(result.untracked)

    def test_does_not_follow_symlinks(self) -> None:
        (self.orphan / "api").mkdir()
        (self.orphan / "api" / "link").symlink_to(self.repository)
        result = self.audit()
        self.assertEqual(result.special, ["api/link"])
        self.assertFalse(result.untracked)

    def test_stops_at_file_budget(self) -> None:
        self.write("api/match.py", "match\n")
        self.write("api/modified.py", "after\n")
        result = self.audit(max_files=1)
        self.assertEqual(result.scanned_files, 1)
        self.assertFalse(result.complete)

    def test_stops_at_hash_budget(self) -> None:
        self.write("api/match.py", "match\n")
        result = self.audit(max_hash_bytes=1)
        self.assertEqual(result.scanned_files, 0)
        self.assertFalse(result.complete)

    def test_refuses_real_git_root(self) -> None:
        (self.orphan / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "genuine Git checkout"):
            self.audit()

    def test_refuses_to_archive_incomplete_audit(self) -> None:
        result = MODULE.Result(complete=False)
        with self.assertRaisesRegex(ValueError, "incompletely audited"):
            MODULE.archive(result, self.orphan, self.base)

    def test_refuses_to_remove_unexpected_snapshot_count(self) -> None:
        self.write("api/match.py", "match\n")
        with self.assertRaisesRegex(ValueError, "expected 88"):
            MODULE.remove_snapshot(self.orphan, self.repository, expected_roots=88, home=self.base)
        self.assertTrue((self.orphan / "api" / "match.py").is_file())

    def test_removes_only_verified_snapshot_roots(self) -> None:
        self.write("api/match.py", "match\n")
        self.write("project/match.py", "project\n")
        self.write("unrelated/keep.py", "preserve\n")
        result = MODULE.remove_snapshot(
            self.orphan, self.repository, expected_roots=2, home=self.base
        )
        self.assertEqual(result["removed_roots"], 2)
        self.assertFalse((self.orphan / "api").exists())
        self.assertFalse((self.orphan / "project").exists())
        self.assertEqual((self.orphan / "unrelated" / "keep.py").read_text(), "preserve\n")

    def test_refuses_to_remove_nested_git_checkout(self) -> None:
        self.write("api/nested/.git", "gitdir: /not/entered\n")
        with self.assertRaisesRegex(ValueError, "nested Git checkout"):
            MODULE.remove_snapshot(self.orphan, self.repository, expected_roots=1, home=self.base)
        self.assertTrue((self.orphan / "api" / "nested" / ".git").is_file())


if __name__ == "__main__":
    unittest.main()
