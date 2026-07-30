"""Verify lossless, private, collision-safe Codex artifact archival."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-collate-session-artifacts"
SPEC = importlib.util.spec_from_loader(
    "codex_collate_session_artifacts", SourceFileLoader("codex_collate_session_artifacts", str(SCRIPT))
)
assert SPEC is not None and SPEC.loader is not None
collator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collator
SPEC.loader.exec_module(collator)


class CollateSessionArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir()
        self.destination = self.home / "recovered"
        self.relative = Path("code/project/notes.md")
        self.original = self.home / self.relative
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b"private session context\n")
        self.source = collator.Source("test-notes", self.relative)
        self.configuration = (
            self.home
            / "Google Drive"
            / "My Drive"
            / "Codex"
            / "runtime"
            / "artifact-sources.json"
        )
        self.configuration.parent.mkdir(parents=True)
        self.configure()

    def configure(
        self,
        directories: list[dict[str, str]] | None = None,
        files: list[dict[str, str]] | None = None,
    ) -> None:
        self.configuration.write_text(json.dumps({
            "version": 1,
            "directories": [] if directories is None else directories,
            "files": [] if files is None else files,
        }))
        self.configuration.chmod(0o600)

    def test_help_never_collates_artifacts(self) -> None:
        with patch.object(collator, "collate") as collate:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collator.main(["--help"]), 0)
        collate.assert_not_called()

    def test_invalid_arguments_never_collate_artifacts(self) -> None:
        with patch.object(collator, "collate") as collate:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(collator.main(["--unexpected"]), 2)
        collate.assert_not_called()

    def test_copies_original_and_writes_private_digest_manifest(self) -> None:
        records = collator.collate(self.home, self.destination, [self.source])
        recovered = self.destination / self.relative
        manifest = self.destination / "MANIFEST.jsonl"
        self.assertEqual(recovered.read_bytes(), self.original.read_bytes())
        self.assertEqual(records[0].sha256, hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual(json.loads(manifest.read_text()), {
            "bytes": len(self.original.read_bytes()), "captured_at": records[0].captured_at,
            "category": "test-notes", "original_mode": records[0].original_mode,
            "recovered": str(self.relative), "sha256": records[0].sha256,
            "source": str(self.relative),
        })
        for path in (self.destination, recovered.parent):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for path in (recovered, manifest):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_same_content_is_idempotent(self) -> None:
        collator.collate(self.home, self.destination, [self.source])
        recovered = self.destination / self.relative
        previous = recovered.stat().st_mtime_ns
        collator.collate(self.home, self.destination, [self.source])
        self.assertEqual(recovered.stat().st_mtime_ns, previous)

    def test_different_existing_content_is_never_overwritten(self) -> None:
        collator.collate(self.home, self.destination, [self.source])
        self.original.write_bytes(b"changed session context\n")
        with self.assertRaises(FileExistsError):
            collator.collate(self.home, self.destination, [self.source])
        self.assertEqual((self.destination / self.relative).read_bytes(), b"private session context\n")

    def test_preserves_existing_manifest_when_adding_artifacts(self) -> None:
        collator.collate(self.home, self.destination, [self.source])
        next_relative = Path("code/project/second.md")
        (self.home / next_relative).write_bytes(b"another session artifact\n")
        collator.collate(self.home, self.destination,
                         [collator.Source("next-notes", next_relative)])
        entries = [json.loads(line) for line in
                   (self.destination / "MANIFEST.jsonl").read_text().splitlines()]
        self.assertEqual({entry["source"] for entry in entries},
                         {str(self.relative), str(next_relative)})

    def test_missing_note_roots_and_explicit_originals_select_no_sources(self) -> None:
        self.assertEqual(collator.selected_sources(self.home), [])

    def test_preserves_manifest_after_archived_original_is_removed(self) -> None:
        collator.collate(self.home, self.destination, [self.source])
        manifest = self.destination / "MANIFEST.jsonl"
        previous_manifest = manifest.read_bytes()
        self.original.unlink()
        self.assertEqual(collator.collate(self.home, self.destination), [])
        self.assertEqual(manifest.read_bytes(), previous_manifest)
        self.assertEqual((self.destination / self.relative).read_bytes(),
                         b"private session context\n")

    def test_refuses_existing_note_root_that_is_not_a_directory(self) -> None:
        root = self.home / "records"
        root.mkdir()
        (root / "notes").write_text("not a directory")
        self.configure(directories=[{"category": "notes", "path": "records/notes"}])
        with self.assertRaises(NotADirectoryError):
            collator.selected_sources(self.home)

    def test_refuses_existing_note_root_symlink(self) -> None:
        root = self.home / "records"
        root.mkdir()
        outside = self.home / "outside"
        outside.mkdir()
        (root / "notes").symlink_to(outside, target_is_directory=True)
        self.configure(directories=[{"category": "notes", "path": "records/notes"}])
        with self.assertRaises(NotADirectoryError):
            collator.selected_sources(self.home)

    def test_directory_selection_never_enters_configuration_or_nested_files(self) -> None:
        root = self.home / "records"
        initiatives = root / "tasks"
        handoffs = root / "handoffs"
        environments = root / "nested"
        for directory in (initiatives, handoffs, environments):
            directory.mkdir(parents=True)
        (initiatives / "task.md").write_text("task")
        (handoffs / "owner.md").write_text("handoff")
        (root / "notes.md").write_text("context")
        (root / "config.toml").write_text("excluded")
        (environments / "private.toml").write_text("excluded")
        sources = (
            collator._direct_files(self.home, "records/tasks", "tasks")
            + collator._direct_files(self.home, "records/handoffs", "handoffs")
            + collator._direct_files(self.home, "records", "markdown", ".md")
            + collator._direct_files(self.home, "records", "markdown", ".markdown")
        )
        self.assertEqual({source.relative_path for source in sources}, {
            Path("records/tasks/task.md"),
            Path("records/handoffs/owner.md"),
            Path("records/notes.md"),
        })

    def test_configured_selection_preserves_direct_files_without_entering_nested_directories(self) -> None:
        worktrees = self.home / "records"
        handoff = worktrees / "handoff"
        metadata = worktrees / "metadata"
        virtualenv = metadata / ".venv"
        handoff.mkdir(parents=True)
        virtualenv.mkdir(parents=True)
        (worktrees / "session.md").write_text("recoverable history")
        (handoff / "document-result.json").write_text("private document")
        (handoff / "manifest.json").write_text("private provenance")
        (metadata / ".metadata.json").write_text("{}")
        (metadata / ".metadata-root").write_text("metadata")
        (virtualenv / "secret.txt").write_text("excluded")
        self.configure(directories=[
            {"category": "notes", "path": "records", "suffix": ".md"},
            {"category": "handoff", "path": "records/handoff"},
        ], files=[
            {"category": "metadata", "path": "records/metadata/.metadata.json"},
            {"category": "metadata", "path": "records/metadata/.metadata-root"},
        ])

        sources = collator.selected_sources(self.home)

        self.assertEqual({source.relative_path for source in sources}, {
            Path("records/session.md"),
            Path("records/handoff/document-result.json"),
            Path("records/handoff/manifest.json"),
            Path("records/metadata/.metadata.json"),
            Path("records/metadata/.metadata-root"),
        })

    def test_refuses_missing_or_nonprivate_configuration(self) -> None:
        self.configuration.unlink()
        with self.assertRaises(FileNotFoundError):
            collator.selected_sources(self.home)
        self.configure()
        self.configuration.chmod(0o644)
        with self.assertRaises(PermissionError):
            collator.selected_sources(self.home)

    def test_refuses_configuration_symlink(self) -> None:
        target = self.home / "configuration.json"
        self.configuration.replace(target)
        self.configuration.symlink_to(target)
        with self.assertRaises(ValueError):
            collator.selected_sources(self.home)

    def test_refuses_escaping_configured_paths(self) -> None:
        for path in ("../outside", "/outside", "records/../outside", "records//outside"):
            with self.subTest(path=path):
                self.configure(files=[{"category": "notes", "path": path}])
                with self.assertRaises(ValueError):
                    collator.selected_sources(self.home)

    def test_refuses_unknown_configuration_fields(self) -> None:
        self.configure(files=[{"category": "notes", "path": "records/note.md",
                              "unexpected": "rejected"}])
        with self.assertRaises(ValueError):
            collator.selected_sources(self.home)

    def test_refuses_source_symlink(self) -> None:
        self.original.unlink()
        self.original.symlink_to(self.home / "outside")
        with self.assertRaises(ValueError):
            collator.collate(self.home, self.destination, [self.source])

    def test_refuses_destination_directory_symlink(self) -> None:
        self.destination.mkdir(mode=0o700)
        outside = self.home / "outside"
        outside.mkdir()
        (self.destination / "code").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(NotADirectoryError):
            collator.collate(self.home, self.destination, [self.source])

    def test_refuses_duplicate_and_escaping_destinations(self) -> None:
        with self.assertRaises(ValueError):
            collator.collate(self.home, self.destination, [self.source, self.source])
        with self.assertRaises(ValueError):
            collator.collate(self.home, self.destination, [collator.Source("escape", Path("../outside"))])


if __name__ == "__main__":
    unittest.main()
