"""Verify atomic, zero-copy migration of complete portable session state."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
from typing import Callable, Protocol, cast
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-migrate-session-state"
SPEC = importlib.util.spec_from_loader(
    "codex_migrate_session_state",
    SourceFileLoader("codex_migrate_session_state", str(SCRIPT)),
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Migrator(Protocol):
    def migrate_path(
        self, source: Path, target: Path, *, dry_run: bool
    ) -> dict[str, object]: ...

    def migrate(
        self, codex_home: Path, shared_root: Path, *, dry_run: bool
    ) -> dict[str, object]: ...

    def link_path(self, source: Path, target: Path) -> dict[str, object]: ...

    def link(
        self, codex_home: Path, shared_root: Path, *, wait_seconds: float = 30
    ) -> dict[str, object]: ...


migrator = cast(Migrator, cast(object, module))


class SessionMigrationTests(unittest.TestCase):
    temporary: tempfile.TemporaryDirectory[str]
    codex_home: Path
    shared_root: Path

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.codex_home = root / "codex"
        self.shared_root = root / "shared"
        self.codex_home.mkdir()
        self.shared_root.mkdir()
        runtime = self.shared_root / "runtime"
        runtime.mkdir()
        _ = (runtime / "backup-leader.json").write_text(
            json.dumps({"hostname": socket.gethostname()})
        )

    def create_directory(self, name: str) -> tuple[Path, Path, Path]:
        source = self.codex_home / name
        target = self.shared_root / name
        child = source / "thread" / "segment" / "rollout.jsonl"
        child.parent.mkdir(parents=True)
        _ = child.write_text('{"type":"session_meta"}\ncontent\n', encoding="utf-8")
        return source, target, child

    def test_provider_owned_destination_root_survives_directory_reconciliation(
        self,
    ) -> None:
        source, target, child = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)
        inode = target.stat().st_ino
        provider_file = target / "thread" / "segment" / "rollout.jsonl"
        provider_file_inode = provider_file.stat().st_ino

        result = migrator.migrate_path(source, target, dry_run=False)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["removed_duplicate_files"], 1)
        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), target.resolve())
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(provider_file.stat().st_ino, provider_file_inode)
        self.assertEqual(
            child.read_text(encoding="utf-8"), '{"type":"session_meta"}\ncontent\n'
        )
        self.assertFalse(
            (self.shared_root / ".rotated_rollout_segments.pre-migration").exists()
        )

    def test_regular_file_migrates_without_copying(self) -> None:
        source = self.codex_home / "session_index.jsonl"
        target = self.shared_root / source.name
        _ = source.write_text("session\n", encoding="utf-8")
        _ = target.write_text("session\n", encoding="utf-8")
        inode = target.stat().st_ino

        result = migrator.migrate_path(source, target, dry_run=False)

        self.assertEqual(result["status"], "migrated")
        self.assertTrue(source.is_symlink())
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(source.read_text(encoding="utf-8"), "session\n")

    def test_stale_provider_session_index_receives_missing_records_in_place(
        self,
    ) -> None:
        source = self.codex_home / "session_index.jsonl"
        target = self.shared_root / source.name
        _ = source.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
        _ = target.write_text('{"id":1}\n', encoding="utf-8")
        inode = target.stat().st_ino

        _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(target.read_text(), '{"id":1}\n{"id":2}\n')
        self.assertTrue(source.is_symlink())

    def test_divergent_provider_session_index_is_never_replaced(self) -> None:
        source = self.codex_home / "session_index.jsonl"
        target = self.shared_root / source.name
        _ = source.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
        _ = target.write_text('{"id":3}\n', encoding="utf-8")
        inode = target.stat().st_ino

        with self.assertRaisesRegex(ValueError, "conflicts"):
            _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(target.read_text(), '{"id":3}\n')

    def test_repeat_migration_is_idempotent(self) -> None:
        source, target, _ = self.create_directory("attachments")
        _ = migrator.migrate_path(source, target, dry_run=False)

        result = migrator.migrate_path(source, target, dry_run=False)

        self.assertEqual(result, {"directory": "attachments", "status": "linked"})

    def test_different_shared_content_is_rejected_without_modification(self) -> None:
        source, target, child = self.create_directory("archived_sessions")
        _ = shutil.copytree(source, target)
        _ = (target / "thread" / "segment" / "rollout.jsonl").write_text(
            '{"type":"session_meta"}\nchanged\n'
        )

        with self.assertRaisesRegex(ValueError, "differs"):
            _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertTrue(child.is_file())
        self.assertTrue(target.is_dir())

    def test_failed_exchange_restores_existing_shared_directory(self) -> None:
        source, target, child = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)

        with patch.object(module, "_exchange", side_effect=OSError("unsupported")):
            with self.assertRaisesRegex(OSError, "unsupported"):
                _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertTrue(child.is_file())
        self.assertTrue(target.is_dir())
        self.assertFalse(
            (self.shared_root / ".rotated_rollout_segments.pre-migration").exists()
        )

    def test_post_exchange_failure_rolls_back_both_paths(self) -> None:
        source, target, child = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)

        with patch.object(
            module,
            "_sync_directory",
            side_effect=[None, None, RuntimeError("sync failed"), None, None],
        ):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertTrue(child.is_file())
        self.assertTrue(target.is_dir())
        self.assertFalse(
            (self.shared_root / ".rotated_rollout_segments.pre-migration").exists()
        )

    def test_dry_run_leaves_both_paths_untouched(self) -> None:
        source, target, _ = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)

        result = migrator.migrate_path(source, target, dry_run=True)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["duplicate_files"], 1)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertTrue(target.is_dir())

    def test_concurrent_reader_never_observes_a_missing_native_path(self) -> None:
        source, target, child = self.create_directory("rotated_rollout_segments")
        errors: list[Exception] = []
        stop = threading.Event()

        def read() -> None:
            while not stop.is_set():
                try:
                    _ = child.read_text(encoding="utf-8")
                except OSError as error:
                    errors.append(error)
                    stop.set()

        reader = threading.Thread(target=read)
        reader.start()
        try:
            _ = migrator.migrate_path(source, target, dry_run=False)
        finally:
            stop.set()
            reader.join()

        self.assertEqual(errors, [])

    def test_late_real_file_is_never_deleted_during_link_shell_cleanup(self) -> None:
        source, target, _ = self.create_directory("rotated_rollout_segments")
        target.mkdir()
        original_rmdir = Path.rmdir
        injected = False

        def inject_file(path: Path) -> None:
            nonlocal injected
            if path.name == ".rotated_rollout_segments.migration-link" and not injected:
                injected = True
                _ = (path / "late-rollout.jsonl").write_text("must survive\n")
            original_rmdir(path)

        with patch.object(Path, "rmdir", autospec=True, side_effect=inject_file):
            with self.assertRaises(OSError):
                _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertEqual((source / "late-rollout.jsonl").read_text(), "must survive\n")
        self.assertTrue((source / "thread").is_symlink())
        self.assertTrue((target / "thread" / "segment" / "rollout.jsonl").is_file())

    def test_all_session_state_paths_are_migrated(self) -> None:
        for name in ("rotated_rollout_segments", "archived_sessions", "attachments"):
            _ = self.create_directory(name)
        _ = (self.codex_home / "session_index.jsonl").write_text("session\n")

        result = migrator.migrate(self.codex_home, self.shared_root, dry_run=False)

        self.assertEqual(result["status"], "completed")
        for name in (
            "rotated_rollout_segments",
            "archived_sessions",
            "attachments",
            "session_index.jsonl",
        ):
            self.assertTrue((self.codex_home / name).is_symlink())
            self.assertTrue((self.shared_root / name).exists())

    def test_follower_cannot_migrate_any_session_state(self) -> None:
        source, _, _ = self.create_directory("rotated_rollout_segments")
        _ = (self.shared_root / "runtime" / "backup-leader.json").write_text(
            json.dumps({"hostname": "another-host"})
        )

        with self.assertRaisesRegex(PermissionError, "elected backup leader"):
            _ = migrator.migrate(self.codex_home, self.shared_root, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertFalse((self.shared_root / "rotated_rollout_segments").exists())

    def test_changed_provider_file_rolls_back_without_replacing_its_identity(
        self,
    ) -> None:
        source, target, _ = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)
        provider_file = target / "thread" / "segment" / "rollout.jsonl"
        provider_inode = provider_file.stat().st_ino
        original_exchange = cast(
            Callable[[Path, Path], None], module.__dict__["_exchange"]
        )
        changed = False

        def mutate_after_exchange(left: Path, right: Path) -> None:
            nonlocal changed
            original_exchange(left, right)
            if not changed:
                changed = True
                _ = provider_file.write_text('{"type":"session_meta"}\nchanged\n')

        with patch.object(module, "_exchange", side_effect=mutate_after_exchange):
            with self.assertRaisesRegex(ValueError, "differs"):
                _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertTrue(target.is_dir())
        self.assertEqual(
            (target / "thread" / "segment" / "rollout.jsonl").read_text(),
            '{"type":"session_meta"}\nchanged\n',
        )
        self.assertEqual(provider_file.stat().st_ino, provider_inode)

    def test_new_destination_root_is_never_replaced(self) -> None:
        source, target, child = self.create_directory("archived_sessions")

        _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), target.resolve())
        self.assertEqual(
            child.read_text(encoding="utf-8"), '{"type":"session_meta"}\ncontent\n'
        )

    def test_nonidentical_provider_contents_prevent_any_reconciliation(self) -> None:
        source, target, child = self.create_directory("rotated_rollout_segments")
        _ = shutil.copytree(source, target)
        provider_inode = target.stat().st_ino
        _ = (target / "thread" / "segment" / "rollout.jsonl").write_text(
            '{"type":"session_meta"}\nchanged\n'
        )

        with self.assertRaisesRegex(ValueError, "differs"):
            _ = migrator.migrate_path(source, target, dry_run=False)

        self.assertFalse(source.is_symlink())
        self.assertTrue(child.is_file())
        self.assertEqual(target.stat().st_ino, provider_inode)

    def test_follower_links_absent_session_directory(self) -> None:
        target = self.shared_root / "rotated_rollout_segments"
        target.mkdir()
        source = self.codex_home / target.name

        result = migrator.link_path(source, target)

        self.assertEqual(result["status"], "linked")
        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), target.resolve())

    def test_follower_replaces_only_empty_local_directory(self) -> None:
        target = self.shared_root / "archived_sessions"
        target.mkdir()
        source = self.codex_home / target.name
        source.mkdir()

        _ = migrator.link_path(source, target)

        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), target.resolve())

    def test_follower_replaces_only_empty_local_file(self) -> None:
        target = self.shared_root / "session_index.jsonl"
        _ = target.write_text("shared\n")
        source = self.codex_home / target.name
        _ = source.write_text("")

        _ = migrator.link_path(source, target)

        self.assertTrue(source.is_symlink())
        self.assertEqual(source.read_text(), "shared\n")

    def test_follower_refuses_nonempty_local_directory(self) -> None:
        source, _, child = self.create_directory("attachments")
        target = self.shared_root / source.name
        target.mkdir()

        with self.assertRaisesRegex(ValueError, "nonempty local session state"):
            _ = migrator.link_path(source, target)

        self.assertTrue(child.is_file())
        self.assertFalse(source.is_symlink())

    def test_follower_refuses_nonempty_local_file(self) -> None:
        target = self.shared_root / "session_index.jsonl"
        _ = target.write_text("shared\n")
        source = self.codex_home / target.name
        _ = source.write_text("local\n")

        with self.assertRaisesRegex(ValueError, "nonempty local session state"):
            _ = migrator.link_path(source, target)

        self.assertEqual(source.read_text(), "local\n")

    def test_follower_link_is_idempotent(self) -> None:
        target = self.shared_root / "attachments"
        target.mkdir()
        source = self.codex_home / target.name
        source.symlink_to(target, target_is_directory=True)

        self.assertEqual(
            migrator.link_path(source, target),
            {"directory": "attachments", "status": "linked"},
        )

    def test_follower_refuses_other_destination(self) -> None:
        target = self.shared_root / "attachments"
        target.mkdir()
        other = self.shared_root / "other"
        other.mkdir()
        source = self.codex_home / target.name
        source.symlink_to(other, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "another destination"):
            _ = migrator.link_path(source, target)

        self.assertEqual(source.resolve(), other.resolve())

    def test_follower_requires_existing_shared_target(self) -> None:
        target = self.shared_root / "attachments"
        source = self.codex_home / target.name

        with self.assertRaisesRegex(ValueError, "unavailable"):
            _ = migrator.link_path(source, target)

        self.assertFalse(source.exists())

    def test_follower_links_all_paths_without_being_leader(self) -> None:
        _ = (self.shared_root / "runtime" / "backup-leader.json").write_text(
            json.dumps({"hostname": "another-host"})
        )
        for name in ("rotated_rollout_segments", "archived_sessions", "attachments"):
            (self.shared_root / name).mkdir()
        _ = (self.shared_root / "session_index.jsonl").write_text("index\n")

        result = migrator.link(self.codex_home, self.shared_root)

        self.assertEqual(result["status"], "linked")
        for name in (
            "rotated_rollout_segments",
            "archived_sessions",
            "attachments",
            "session_index.jsonl",
        ):
            self.assertEqual(
                (self.codex_home / name).resolve(), (self.shared_root / name).resolve()
            )

    def test_follower_reports_google_drive_sync_delay_without_touching_local_state(
        self,
    ) -> None:
        source = self.codex_home / "rotated_rollout_segments"
        source.mkdir()

        with self.assertRaisesRegex(
            FileNotFoundError,
            "Google Drive has not synchronized.*rotated_rollout_segments",
        ):
            _ = migrator.link(self.codex_home, self.shared_root, wait_seconds=0)

        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())

    def test_follower_waits_for_google_drive_to_expose_shared_state(self) -> None:
        def finish_sync() -> None:
            time.sleep(0.01)
            for name in (
                "rotated_rollout_segments",
                "archived_sessions",
                "attachments",
            ):
                (self.shared_root / name).mkdir()
            _ = (self.shared_root / "session_index.jsonl").write_text("index\n")

        sync = threading.Thread(target=finish_sync)
        sync.start()
        try:
            result = migrator.link(self.codex_home, self.shared_root, wait_seconds=2)
        finally:
            sync.join()

        self.assertEqual(result["status"], "linked")


if __name__ == "__main__":
    _ = unittest.main()
