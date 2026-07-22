import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_helpers.asset_types import SoundAsset, SpriteAsset
from gms_helpers.sprite_frames import remove_frame
from gms_helpers.sprite_import import import_strip_to_sprite
from gms_helpers import transactions as transactions_module
from gms_helpers.exceptions import ValidationError
from gms_helpers.transactions import (
    GameMakerProjectTransaction,
    ProjectValidationResult,
    mark_transaction_path_owned,
    mark_transaction_tree_owned,
    transaction_is_active,
    validate_project_after_mutation,
)


class TestGameMakerProjectTransactions(unittest.TestCase):
    def _project(self, parent: Path) -> Path:
        root = parent / "project"
        root.mkdir()
        (root / "TestProject.yyp").write_text("{}", encoding="utf-8")
        (root / "tracked.txt").write_text("before", encoding="utf-8")
        return root

    def test_transaction_active_guard_tracks_context_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GMS_MCP_TRANSACTION_ROOT", None)
                os.environ.pop("GMS_MCP_TRANSACTION_JOURNAL", None)
                os.environ.pop("GMS_MCP_TRANSACTION_BACKUP_ROOT", None)
                self.assertFalse(transaction_is_active())
                transaction = GameMakerProjectTransaction(root, "active-guard")
                transaction.begin()
                try:
                    self.assertTrue(transaction_is_active())
                finally:
                    transaction.cleanup()
                self.assertFalse(transaction_is_active())

    @unittest.skipIf(os.name == "nt", "Symlink containment test requires POSIX symlinks")
    def test_transaction_rejects_an_existing_symlink_outside_the_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = self._project(parent)
            outside = parent / "private.txt"
            outside.write_text("private", encoding="utf-8")
            (root / "linked.txt").symlink_to(outside)

            transaction = GameMakerProjectTransaction(root, "unsafe-link")
            with self.assertRaises(ValidationError):
                transaction.begin()

            self.assertEqual(outside.read_text(encoding="utf-8"), "private")

    @unittest.skipIf(os.name == "nt", "Symlink containment test requires POSIX symlinks")
    def test_transaction_blocks_creation_of_a_link_to_an_external_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = self._project(parent)
            outside = parent / "private.txt"
            outside.write_text("private", encoding="utf-8")
            link = root / "linked.txt"
            transaction = GameMakerProjectTransaction(root, "unsafe-link-create")
            transaction.begin()
            try:
                with self.assertRaises(ValidationError):
                    link.symlink_to(outside)
                self.assertFalse(link.exists())
                self.assertEqual(outside.read_text(encoding="utf-8"), "private")
            finally:
                transaction.cleanup()

    def test_journal_ignores_windows_reserved_device_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            journal = root / "journal.jsonl"
            journal.write_text("", encoding="utf-8")
            backup = root / "backup"
            backup.mkdir()
            context = transactions_module._TransactionJournalContext(root, journal, backup)

            with patch.object(transactions_module.os, "name", "nt"):
                self.assertIsNone(transactions_module._journal_relative_path(context, "nul"))
                self.assertIsNone(transactions_module._journal_relative_path(context, "NUL.txt"))
                self.assertIsNone(transactions_module._journal_relative_path(context, r"\\.\COM1"))

    def test_journal_rejects_lexical_project_path_that_resolves_outside(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = self._project(parent).resolve()
            journal = root / "journal.jsonl"
            journal.write_text("", encoding="utf-8")
            backup = root / "backup"
            backup.mkdir()
            context = transactions_module._TransactionJournalContext(root, journal, backup)
            lexical = root / "junction" / "private.txt"
            resolved = parent / "private" / "private.txt"

            with (
                patch.object(transactions_module, "_lexical_absolute_path", return_value=lexical),
                patch.object(transactions_module, "_audit_absolute_path", return_value=resolved),
                self.assertRaises(ValidationError),
            ):
                transactions_module._journal_relative_path(context, lexical)

    def test_validation_accepts_inherited_option_envelopes_and_metadata_only_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            object_path = root / "objects" / "o_empty" / "o_empty.yy"
            object_path.parent.mkdir(parents=True)
            inherited_path = root / "options" / "main" / "inherited" / "options_main.inherited.yy"
            inherited_path.parent.mkdir(parents=True)
            inherited_path.write_text('1.0.0←id|{"option": true}', encoding="utf-8")
            (root / "TestProject.yyp").write_text(
                '{"Folders":[{"folderPath":"folders/Objects.yy"}],'
                '"resources":[{"id":{"name":"o_empty","path":"objects/o_empty/o_empty.yy"}}]}',
                encoding="utf-8",
            )
            object_path.write_text(
                '{"$GMObject":"","resourceType":"GMObject",'
                '"parent":{"path":"folders/Objects.yy"},'
                '"eventList":[{"$GMEvent":"v1","%Name":"","name":"",'
                '"eventNum":0,"eventType":3,"collisionObjectId":null}]}',
                encoding="utf-8",
            )

            validation = validate_project_after_mutation(root)

            self.assertTrue(validation.success, msg=validation.errors)
            self.assertEqual(validation.errors, [])
            self.assertIn("metadata-only empty event: Step_0.gml", validation.warnings[0])

    def test_validation_still_rejects_named_missing_event_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            object_path = root / "objects" / "o_broken" / "o_broken.yy"
            object_path.parent.mkdir(parents=True)
            (root / "TestProject.yyp").write_text(
                '{"Folders":[{"folderPath":"folders/Objects.yy"}],'
                '"resources":[{"id":{"name":"o_broken","path":"objects/o_broken/o_broken.yy"}}]}',
                encoding="utf-8",
            )
            object_path.write_text(
                '{"$GMObject":"","resourceType":"GMObject",'
                '"parent":{"path":"folders/Objects.yy"},'
                '"eventList":[{"$GMEvent":"v1","%Name":"Step_0","name":"Step_0",'
                '"eventNum":0,"eventType":3,"collisionObjectId":null}]}',
                encoding="utf-8",
            )

            validation = validate_project_after_mutation(root)

            self.assertFalse(validation.success)
            self.assertIn("Object 'o_broken' event file is missing: Step_0.gml", validation.errors)

    def test_transaction_active_guard_recognizes_inherited_journal_environment(self):
        with patch.dict(
            os.environ,
            {
                "GMS_MCP_TRANSACTION_ROOT": "/tmp/project",
                "GMS_MCP_TRANSACTION_JOURNAL": "/tmp/transaction.jsonl",
                "GMS_MCP_TRANSACTION_BACKUP_ROOT": "/tmp/transaction-backup",
            },
            clear=False,
        ):
            self.assertTrue(transaction_is_active())

    def test_threaded_transactions_serialize_until_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            first = GameMakerProjectTransaction(root, "first")
            second = GameMakerProjectTransaction(root, "second")
            second_started = threading.Event()
            second_acquired = threading.Event()

            first.begin()
            (root / "tracked.txt").write_text("committed", encoding="utf-8")
            first.commit()

            def begin_second():
                second_started.set()
                second.begin()
                second_acquired.set()

            thread = threading.Thread(target=begin_second)
            thread.start()
            self.assertTrue(second_started.wait(timeout=5))
            try:
                self.assertFalse(second_acquired.wait(timeout=0.2), "lock was released before transaction cleanup")
            finally:
                first.cleanup()

            self.assertTrue(second_acquired.wait(timeout=5))
            second.cleanup()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_begin_uses_empty_lazy_backup_and_snapshots_only_touched_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            untouched = root / "untouched.bin"
            untouched.write_bytes(b"x" * (1024 * 1024))
            transaction = GameMakerProjectTransaction(root, "lazy-backup")
            transaction.begin()
            try:
                assert transaction._backup_root is not None
                self.assertEqual(list(transaction._backup_root.rglob("*")), [])

                (root / "tracked.txt").write_text("changed", encoding="utf-8")

                self.assertEqual(
                    (transaction._backup_root / "tracked.txt").read_text(encoding="utf-8"),
                    "before",
                )
                self.assertFalse((transaction._backup_root / "untouched.bin").exists())
            finally:
                transaction.cleanup()

    def test_process_transactions_serialize_until_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = self._project(parent)
            ready_path = parent / "child-ready"
            acquired_path = parent / "child-acquired"
            first = GameMakerProjectTransaction(root, "parent")
            first.begin()
            child_code = "\n".join(
                [
                    "import sys",
                    "from pathlib import Path",
                    "from gms_helpers.transactions import GameMakerProjectTransaction",
                    "root, ready, acquired = map(Path, sys.argv[1:])",
                    "ready.write_text('ready', encoding='utf-8')",
                    "tx = GameMakerProjectTransaction(root, 'child')",
                    "tx.begin()",
                    "acquired.write_text('acquired', encoding='utf-8')",
                    "tx.cleanup()",
                ]
            )
            child = subprocess.Popen(
                [sys.executable, "-c", child_code, str(root), str(ready_path), str(acquired_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready_path.exists(), "child did not reach transaction begin")
                self.assertFalse(acquired_path.exists(), "child acquired the cross-process lock too early")
            finally:
                first.cleanup()

            stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, msg=stdout + stderr)
            self.assertTrue(acquired_path.exists())

    def test_rollback_restores_only_journaled_paths_and_preserves_external_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            transaction = GameMakerProjectTransaction(root, "journal-test")
            transaction.begin()
            try:
                (root / "tracked.txt").write_text("transaction change", encoding="utf-8")
                mark_transaction_path_owned(root / "tracked.txt")
                owned_created = root / "owned" / "created.txt"
                owned_created.parent.mkdir()
                owned_created.write_text("transaction file", encoding="utf-8")
                mark_transaction_path_owned(owned_created)

                external_path = root / "external-save.txt"
                external_thread = threading.Thread(
                    target=lambda: external_path.write_text("IDE save", encoding="utf-8")
                )
                transaction.capture_mutation_state()
                external_thread.start()
                external_thread.join(timeout=5)

                self.assertFalse(transaction.rollback())
                self.assertEqual((root / "tracked.txt").read_text(encoding="utf-8"), "before")
                self.assertFalse(owned_created.exists())
                self.assertFalse(owned_created.parent.exists())
                self.assertEqual(external_path.read_text(encoding="utf-8"), "IDE save")
                self.assertTrue(
                    any(conflict["path"] == "external-save.txt" for conflict in transaction.rollback_conflicts)
                )
            finally:
                transaction.cleanup()

    def test_rollback_preserves_same_path_external_change_after_mutation_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            transaction = GameMakerProjectTransaction(root, "conflict-test")
            transaction.begin()
            try:
                tracked = root / "tracked.txt"
                tracked.write_text("transaction change", encoding="utf-8")
                mark_transaction_path_owned(tracked)
                transaction.capture_mutation_state()
                external_thread = threading.Thread(target=lambda: tracked.write_text("external wins", encoding="utf-8"))
                external_thread.start()
                external_thread.join(timeout=5)

                self.assertFalse(transaction.rollback())

                self.assertEqual(tracked.read_text(encoding="utf-8"), "external wins")
                self.assertFalse(transaction.rolled_back)
                self.assertTrue(transaction.rollback_conflicts)
            finally:
                transaction.cleanup()

    def test_rollback_preserves_external_process_write_before_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            tracked = root / "tracked.txt"
            transaction = GameMakerProjectTransaction(root, "external-process-conflict")
            transaction.begin()
            try:
                tracked.write_text("transaction change", encoding="utf-8")
                mark_transaction_path_owned(tracked)
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('IDE save', encoding='utf-8')",
                        str(tracked),
                    ],
                    check=True,
                )
                transaction.capture_mutation_state()

                self.assertFalse(transaction.rollback())
                self.assertEqual(tracked.read_text(encoding="utf-8"), "IDE save")
                self.assertTrue(
                    any(
                        conflict["path"] == "tracked.txt" and "recorded transaction output" in conflict["reason"]
                        for conflict in transaction.rollback_conflicts
                    )
                )
            finally:
                transaction.cleanup()

    def test_directory_rename_rollback_restores_all_original_descendants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            source = root / "assets" / "original"
            nested = source / "nested"
            nested.mkdir(parents=True)
            (source / "asset.yy").write_text("yy-before", encoding="utf-8")
            (nested / "code.gml").write_text("gml-before", encoding="utf-8")
            destination = source.with_name("renamed")
            transaction = GameMakerProjectTransaction(root, "directory-rename")
            transaction.begin()
            try:
                source.rename(destination)
                mark_transaction_tree_owned(source)
                mark_transaction_tree_owned(destination)
                transaction.capture_mutation_state()

                self.assertTrue(transaction.rollback())
                self.assertEqual((source / "asset.yy").read_text(encoding="utf-8"), "yy-before")
                self.assertEqual((source / "nested" / "code.gml").read_text(encoding="utf-8"), "gml-before")
                self.assertFalse(destination.exists())
                self.assertTrue(transaction.rollback_complete)
            finally:
                transaction.cleanup()

    def test_directory_rename_rollback_preserves_external_destination_edit_as_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            source = root / "assets" / "original"
            source.mkdir(parents=True)
            (source / "asset.yy").write_text("before", encoding="utf-8")
            destination = source.with_name("renamed")
            transaction = GameMakerProjectTransaction(root, "directory-rename-conflict")
            transaction.begin()
            try:
                source.rename(destination)
                mark_transaction_tree_owned(source)
                mark_transaction_tree_owned(destination)
                transaction.capture_mutation_state()
                moved_file = destination / "asset.yy"
                external_thread = threading.Thread(
                    target=lambda: moved_file.write_text("external edit", encoding="utf-8")
                )
                external_thread.start()
                external_thread.join(timeout=5)

                self.assertFalse(transaction.rollback())
                self.assertEqual((source / "asset.yy").read_text(encoding="utf-8"), "before")
                self.assertEqual(moved_file.read_text(encoding="utf-8"), "external edit")
                self.assertFalse(transaction.rollback_complete)
                self.assertTrue(
                    any(conflict["path"].endswith("renamed/asset.yy") for conflict in transaction.rollback_conflicts)
                )
            finally:
                transaction.cleanup()

    def test_directory_delete_rollback_restores_nested_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            deleted = root / "assets" / "deleted"
            nested = deleted / "nested"
            nested.mkdir(parents=True)
            (deleted / "asset.yy").write_text("yy-before", encoding="utf-8")
            (nested / "code.gml").write_text("gml-before", encoding="utf-8")
            transaction = GameMakerProjectTransaction(root, "directory-delete")
            transaction.begin()
            try:
                shutil.rmtree(deleted)
                mark_transaction_tree_owned(deleted)
                transaction.capture_mutation_state()

                self.assertTrue(transaction.rollback())
                self.assertEqual((deleted / "asset.yy").read_text(encoding="utf-8"), "yy-before")
                self.assertEqual((deleted / "nested" / "code.gml").read_text(encoding="utf-8"), "gml-before")
                self.assertTrue(transaction.rollback_complete)
            finally:
                transaction.cleanup()

    def test_sprite_frame_remove_rollback_restores_metadata_and_png_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            relative = SpriteAsset().create_files(
                root,
                "spr_transaction",
                "folders/Sprites.yy",
                frame_count=2,
                width=2,
                height=2,
            )
            sprite_yy = root / relative
            before = {
                path.relative_to(root): path.read_bytes() for path in sprite_yy.parent.rglob("*") if path.is_file()
            }
            transaction = GameMakerProjectTransaction(root, "sprite-remove")
            transaction.begin()
            try:
                remove_frame(root, relative, 1)
                transaction.capture_mutation_state()

                self.assertTrue(transaction.rollback())
                after = {
                    path.relative_to(root): path.read_bytes() for path in sprite_yy.parent.rglob("*") if path.is_file()
                }
                self.assertEqual(after, before)
            finally:
                transaction.cleanup()

    def test_sound_creation_rollback_removes_owned_wav_and_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            transaction = GameMakerProjectTransaction(root, "sound-create")
            transaction.begin()
            try:
                SoundAsset().create_files(root, "snd_transaction", "folders/Sounds.yy")
                transaction.capture_mutation_state()

                self.assertTrue(transaction.rollback())
                self.assertFalse((root / "sounds" / "snd_transaction").exists())
            finally:
                transaction.cleanup()

    def test_sprite_strip_import_rollback_removes_replaced_png_outputs(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = self._project(parent)
            source = parent / "strip.png"
            image = Image.new("RGBA", (4, 2), (255, 0, 0, 255))
            image.save(source, "PNG")
            transaction = GameMakerProjectTransaction(root, "sprite-strip-import")
            transaction.begin()
            try:
                import_strip_to_sprite(
                    root,
                    "spr_transaction_strip",
                    source,
                    parent_path="",
                    frame_width=2,
                    frame_height=2,
                )
                transaction.capture_mutation_state()

                self.assertTrue(transaction.rollback())
                self.assertFalse((root / "sprites" / "spr_transaction_strip").exists())
            finally:
                transaction.cleanup()

    def test_async_transactions_serialize_and_cancelled_waiter_releases_cleanly(self):
        async def exercise(root: Path):
            first = GameMakerProjectTransaction(root, "first-async")
            cancelled_waiter = GameMakerProjectTransaction(root, "cancelled-async")
            successor = GameMakerProjectTransaction(root, "successor-async")
            await first.begin_async()
            waiter_task = asyncio.create_task(cancelled_waiter.begin_async())
            await asyncio.sleep(0.1)
            self.assertFalse(waiter_task.done())
            waiter_task.cancel()
            await first.cleanup_async()
            with self.assertRaises(asyncio.CancelledError):
                await waiter_task
            await asyncio.wait_for(successor.begin_async(), timeout=5)
            await successor.rollback_async()
            await successor.cleanup_async()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            asyncio.run(exercise(root))

    def test_cancelled_async_commit_finishes_before_cancellation_propagates(self):
        validation_started = threading.Event()
        release_validation = threading.Event()

        def blocking_validation(_root):
            validation_started.set()
            release_validation.wait(timeout=5)
            return ProjectValidationResult(success=True, yyp="TestProject.yyp")

        async def exercise(root: Path):
            transaction = GameMakerProjectTransaction(root, "cancelled-commit")
            await transaction.begin_async()
            (root / "tracked.txt").write_text("committed", encoding="utf-8")
            await transaction.capture_mutation_state_async()
            with patch.object(transactions_module, "validate_project_after_mutation", side_effect=blocking_validation):
                commit_task = asyncio.create_task(transaction.commit_async())
                while not validation_started.is_set():
                    await asyncio.sleep(0.01)
                commit_task.cancel()
                await asyncio.sleep(0.05)
                self.assertFalse(commit_task.done())
                release_validation.set()
                with self.assertRaises(asyncio.CancelledError):
                    await commit_task
            self.assertTrue(transaction.committed)
            await transaction.cleanup_async()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            asyncio.run(exercise(root))

    def test_cancelled_async_rollback_finishes_before_cancellation_propagates(self):
        restore_started = threading.Event()
        release_restore = threading.Event()
        original_restore = transactions_module._restore_file_atomically

        def blocking_restore(backup_path, target_path, expected):
            restore_started.set()
            release_restore.wait(timeout=5)
            return original_restore(backup_path, target_path, expected)

        async def exercise(root: Path):
            transaction = GameMakerProjectTransaction(root, "cancelled-rollback")
            await transaction.begin_async()
            (root / "tracked.txt").write_text("mutation", encoding="utf-8")
            mark_transaction_path_owned(root / "tracked.txt")
            await transaction.capture_mutation_state_async()
            with patch.object(transactions_module, "_restore_file_atomically", side_effect=blocking_restore):
                rollback_task = asyncio.create_task(transaction.rollback_async())
                while not restore_started.is_set():
                    await asyncio.sleep(0.01)
                rollback_task.cancel()
                await asyncio.sleep(0.05)
                self.assertFalse(rollback_task.done())
                release_restore.set()
                with self.assertRaises(asyncio.CancelledError):
                    await rollback_task
            self.assertTrue(transaction.rolled_back)
            self.assertEqual((root / "tracked.txt").read_text(encoding="utf-8"), "before")
            await transaction.cleanup_async()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            asyncio.run(exercise(root))

    def test_cancelled_async_cleanup_releases_lock_before_cancellation_propagates(self):
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()

        async def exercise(root: Path):
            transaction = GameMakerProjectTransaction(root, "cancelled-cleanup")
            await transaction.begin_async()
            original_cleanup = transaction._cleanup_locked

            def blocking_cleanup():
                cleanup_started.set()
                release_cleanup.wait(timeout=5)
                original_cleanup()

            with patch.object(transaction, "_cleanup_locked", side_effect=blocking_cleanup):
                current_task = asyncio.current_task()
                assert current_task is not None

                async def cancel_and_release():
                    await asyncio.to_thread(cleanup_started.wait, 5)
                    current_task.cancel()
                    await asyncio.sleep(0.05)
                    release_cleanup.set()

                controller = asyncio.create_task(cancel_and_release())
                with self.assertRaises(asyncio.CancelledError):
                    await transaction.cleanup_async()
                await controller

            successor = GameMakerProjectTransaction(root, "after-cancelled-cleanup")
            await successor.begin_async()
            await successor.cleanup_async()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._project(Path(temp_dir))
            asyncio.run(exercise(root))


if __name__ == "__main__":
    unittest.main()
