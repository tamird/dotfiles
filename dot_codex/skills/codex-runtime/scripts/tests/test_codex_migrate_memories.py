"""Verify durable Codex memory migration never breaks its native path."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from typing import Protocol, Union, cast
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-migrate-memories"
SPEC = importlib.util.spec_from_loader(
    "codex_migrate_memories", SourceFileLoader("codex_migrate_memories", str(SCRIPT))
)
assert SPEC is not None and SPEC.loader is not None


class MigrationModule(Protocol):
    Path: type[Path]

    def fingerprint(
        self, root: Path, *, exclude: Union[frozenset[str], None] = None
    ) -> tuple[dict[str, tuple[str, str, int, int]], int]: ...

    def migrate(
        self,
        source: Path,
        destination: Path,
        *,
        swap: Callable[[Path, Path], None] = ...,
    ) -> dict[str, Union[str, int]]: ...

    def main(self, arguments: Sequence[str]) -> int: ...

    def recover_restored(
        self,
        source: Path,
        destination: Path,
        healthy_git: Path,
        *,
        swap: Callable[[Path, Path], None] = ...,
    ) -> dict[str, Union[str, int]]: ...

    def _stop_duplicate_fsmonitor(self, directory: Path, worktree: Path) -> None: ...


module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
migration = cast(MigrationModule, cast(object, module))


class MigrateMemoriesTests(unittest.TestCase):
    root: Path
    source: Path
    destination: Path

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "native" / "memories"
        self.destination = self.root / "durable" / "memories"
        self.source.mkdir(parents=True)
        (self.source / ".git" / "objects").mkdir(parents=True)
        _ = (self.source / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (self.source / "rollout_summaries").mkdir()
        _ = (self.source / "rollout_summaries" / "session.md").write_text("context\n")
        _ = (self.source / "MEMORY.md").write_text("private memory\n")
        self.destination.parent.mkdir()

    def test_help_never_migrates_memories(self) -> None:
        with patch.object(migration, "migrate") as migrate:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(migration.main(["--help"]), 0)
        migrate.assert_not_called()

    def test_invalid_arguments_never_migrate_memories(self) -> None:
        with patch.object(migration, "migrate") as migrate:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(migration.main(["--unexpected"]), 2)
        migrate.assert_not_called()

    def test_main_migrates_memories_directly_into_shared_google_drive(self) -> None:
        with (
            patch.object(migration.Path, "home", return_value=self.root),
            patch.object(
                migration, "migrate", return_value={"status": "migrated"}
            ) as migrate,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(migration.main([]), 0)

        migrate.assert_called_once_with(
            self.root / ".codex" / "memories",
            self.root / "Google Drive" / "My Drive" / "Codex" / "memories",
        )

    def test_migrates_complete_git_history_and_preserves_native_path(self) -> None:
        original, expected_bytes = migration.fingerprint(self.source)
        result = migration.migrate(self.source, self.destination)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["files"], len(original))
        self.assertEqual(result["bytes"], expected_bytes)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination.resolve())
        self.assertEqual(migration.fingerprint(self.destination)[0], original)
        self.assertEqual(
            (self.source / ".git" / "HEAD").read_text(), "ref: refs/heads/main\n"
        )
        self.assertFalse(any(self.source.parent.glob(".memories.migration.*")))

    def test_already_migrated_path_is_idempotent(self) -> None:
        _ = migration.migrate(self.source, self.destination)
        result = migration.migrate(self.source, self.destination)
        self.assertEqual(result["status"], "already_migrated")

    def test_preserves_existing_empty_durable_directory_identity(self) -> None:
        self.destination.mkdir()
        identity = (self.destination.stat().st_dev, self.destination.stat().st_ino)

        result = migration.migrate(self.source, self.destination)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(
            (self.destination.stat().st_dev, self.destination.stat().st_ino),
            identity,
        )
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination.resolve())

    def test_preserves_existing_identical_durable_directory_identity(self) -> None:
        _ = shutil.copytree(self.source, self.destination)
        identity = (self.destination.stat().st_dev, self.destination.stat().st_ino)

        with patch.object(shutil, "copytree") as copytree:
            result = migration.migrate(self.source, self.destination)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(
            (self.destination.stat().st_dev, self.destination.stat().st_ino),
            identity,
        )
        copytree.assert_not_called()

    def test_refuses_to_overwrite_conflicting_durable_memory(self) -> None:
        self.destination.mkdir()
        _ = (self.destination / "MEMORY.md").write_text("different memory\n")
        identity = (self.destination.stat().st_dev, self.destination.stat().st_ino)

        with self.assertRaises(FileExistsError):
            _ = migration.migrate(self.source, self.destination)

        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(
            (self.destination.stat().st_dev, self.destination.stat().st_ino),
            identity,
        )
        self.assertEqual(
            (self.destination / "MEMORY.md").read_text(), "different memory\n"
        )

    def test_refuses_symbolic_durable_memory_directory(self) -> None:
        other = self.destination.parent / "other"
        other.mkdir()
        self.destination.symlink_to(other, target_is_directory=True)

        with self.assertRaises(FileExistsError):
            _ = migration.migrate(self.source, self.destination)

        self.assertTrue(self.source.is_dir())
        self.assertTrue(self.destination.is_symlink())

    def test_refuses_nonrepository_source(self) -> None:
        (self.source / ".git" / "HEAD").unlink()
        (self.source / ".git" / "objects").rmdir()
        (self.source / ".git").rmdir()
        with self.assertRaises(NotADirectoryError):
            _ = migration.migrate(self.source, self.destination)

    def test_refuses_preexisting_temporary_link(self) -> None:
        temporary = self.source.with_name(".memories.migration." + str(os.getpid()))
        _ = temporary.write_text("existing work\n")
        with self.assertRaises(FileExistsError):
            _ = migration.migrate(self.source, self.destination)
        self.assertEqual(temporary.read_text(), "existing work\n")

    def test_rolls_back_if_exchange_does_not_install_symlink(self) -> None:
        calls: list[tuple[Path, Path]] = []

        def invalid_swap(left: Path, right: Path) -> None:
            calls.append((left, right))

        with self.assertRaises(RuntimeError):
            _ = migration.migrate(self.source, self.destination, swap=invalid_swap)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.source.is_symlink())
        self.assertTrue((self.source / "MEMORY.md").is_file())

    def test_preserves_internal_symlinks_without_following_them(self) -> None:
        (self.source / "summary-link").symlink_to("MEMORY.md")
        _ = migration.migrate(self.source, self.destination)
        self.assertTrue((self.destination / "summary-link").is_symlink())
        self.assertEqual(
            (self.destination / "summary-link").readlink(), Path("MEMORY.md")
        )


class RecoverRestoredMemoriesTests(unittest.TestCase):
    root: Path
    source: Path
    destination: Path
    healthy_git: Path
    canonical_head: str
    recovered_head: str

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.destination = self.root / "shared" / "memories"
        healthy_root = self.root / "healthy"
        self.canonical_head = self._create_repository(self.destination, "current")
        self.recovered_head = self._create_repository(healthy_root, "previous")
        self.healthy_git = healthy_root / ".git"
        self.source = self.root / "native" / "memories"
        self.source.parent.mkdir()
        _ = shutil.copytree(self.destination, self.source)
        _ = (self.destination / "restored-only.md").write_text("restored memory\n")
        _ = shutil.copytree(self.healthy_git, self.destination / ".git (1)")
        shutil.rmtree(self.source / ".git" / "objects")
        (self.source / ".git" / "objects").mkdir()
        (self.source / ".git" / "refs" / "heads" / "main").unlink()

    def _git(self, directory: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test Author",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test Committer",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            },
        )
        return result.stdout.strip()

    def _create_repository(self, directory: Path, content: str) -> str:
        directory.mkdir(parents=True)
        _ = self._git(directory, "init", "--quiet", "--initial-branch=main")
        _ = (directory / "MEMORY.md").write_text(content + "\n")
        _ = self._git(directory, "add", "MEMORY.md")
        tree = self._git(directory, "write-tree")
        commit = self._git(directory, "commit-tree", tree, "-m", content)
        _ = self._git(directory, "update-ref", "refs/heads/main", commit)
        return commit

    def test_recovers_both_histories_without_replacing_provider_directories(
        self,
    ) -> None:
        root_identity = (self.destination.stat().st_dev, self.destination.stat().st_ino)
        git_root = self.destination / ".git"
        git_identity = (git_root.stat().st_dev, git_root.stat().st_ino)
        original_index = self._git(self.destination, "ls-files", "--stage")

        result = migration.recover_restored(
            self.source, self.destination, self.healthy_git
        )

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["head"], self.canonical_head)
        self.assertEqual(result["recovered_head"], self.recovered_head)
        self.assertEqual(
            (self.destination.stat().st_dev, self.destination.stat().st_ino),
            root_identity,
        )
        self.assertEqual((git_root.stat().st_dev, git_root.stat().st_ino), git_identity)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination.resolve())
        self.assertEqual(
            self._git(self.destination, "rev-parse", "HEAD"), self.canonical_head
        )
        self.assertEqual(
            self._git(
                self.destination, "rev-parse", "refs/recovered/pre-migration-main"
            ),
            self.recovered_head,
        )
        self.assertEqual(
            self._git(self.destination, "ls-files", "--stage"), original_index
        )
        self.assertEqual(
            (self.source / "restored-only.md").read_text(), "restored memory\n"
        )
        self.assertFalse((self.destination / ".git (1)").exists())
        _ = self._git(
            self.destination, "fsck", "--full", "--no-reflogs", "--no-progress"
        )

    def test_recovery_is_idempotent_after_relinking(self) -> None:
        _ = migration.recover_restored(self.source, self.destination, self.healthy_git)

        result = migration.recover_restored(
            self.source, self.destination, self.healthy_git
        )

        self.assertEqual(result["status"], "already_recovered")

    def test_recovery_rejects_differing_working_content_without_mutating_git(
        self,
    ) -> None:
        _ = (self.source / "MEMORY.md").write_text("divergent memory\n")

        with self.assertRaises(ValueError):
            _ = migration.recover_restored(
                self.source, self.destination, self.healthy_git
            )

        self.assertFalse(self.source.is_symlink())
        self.assertTrue((self.destination / ".git (1)").is_dir())
        self.assertEqual(
            self._git(self.destination, "rev-parse", "HEAD"), self.canonical_head
        )

    def test_recovery_rejects_a_different_duplicate_history(self) -> None:
        duplicate = self.destination / ".git (1)"
        shutil.rmtree(duplicate)
        another_root = self.root / "another"
        _ = self._create_repository(another_root, "third history")
        _ = shutil.copytree(another_root / ".git", duplicate)

        with self.assertRaises(ValueError):
            _ = migration.recover_restored(
                self.source, self.destination, self.healthy_git
            )

        self.assertFalse(self.source.is_symlink())
        self.assertTrue(duplicate.is_dir())

    def test_working_entries_never_traverse_git_sockets(self) -> None:
        path = self.destination / ".git (1)" / "fsmonitor--daemon-common-v1.ipc"
        with socket.socket(socket.AF_UNIX) as monitor:
            monitor.bind(str(path))
            entries, _ = migration.fingerprint(
                self.destination, exclude=frozenset({".git", ".git (1)"})
            )

        self.assertIn("MEMORY.md", entries)
        self.assertFalse(any(name.startswith(".git") for name in entries))

    def test_stops_only_the_duplicate_repository_fsmonitor(self) -> None:
        duplicate = self.destination / ".git (1)"
        path = duplicate / "fsmonitor--daemon-common-v1.ipc"
        with socket.socket(socket.AF_UNIX) as monitor:
            monitor.bind(str(path))

            def stop(_directory: Path, *_arguments: str) -> str:
                path.unlink()
                return ""

            with patch.object(module, "_git", side_effect=stop) as git:
                migration._stop_duplicate_fsmonitor(  # pyright: ignore[reportPrivateUsage]
                    duplicate, self.destination
                )

        git.assert_called_once_with(
            duplicate,
            "--work-tree=" + str(self.destination),
            "fsmonitor--daemon",
            "stop",
        )


if __name__ == "__main__":
    _ = unittest.main()
