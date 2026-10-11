import ctypes
import sys
import unittest
from unittest.mock import Mock

from quickcrop_ocr.clipboard import (
    CF_UNICODETEXT, ClipboardBackup, ClipboardError, ClipboardWriter, WindowsClipboardApi,
)


class FakeClipboardApi:
    def __init__(self):
        self.contents = {13: "previous text", 0xC001: b"<b>rich text</b>"}
        self.handles = {}
        self.next_handle = 1
        self.busy = False
        self.backup_fails = False
        self.backup_incomplete = False
        self.write_fails = False
        self.restore_fails = False
        self.clear_calls = 0
        self.opened = False

    def allocate(self, value):
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = value
        return handle

    def allocate_text(self, text):
        return self.allocate(text)

    def open(self, _hwnd):
        self.opened = not self.busy
        return self.opened

    def close(self):
        self.opened = False

    def snapshot(self):
        if self.backup_fails:
            raise ClipboardError("backup unavailable")
        formats = self.contents.items()
        if self.backup_incomplete:
            formats = [(fmt, value) for fmt, value in formats if fmt == CF_UNICODETEXT]
        return ClipboardBackup(
            [(fmt, self.allocate(value)) for fmt, value in formats],
            complete=not self.backup_incomplete,
        )

    def clear(self):
        self.clear_calls += 1
        self.contents.clear()
        return True

    def set_data(self, fmt, handle):
        value = self.handles[handle]
        if (self.write_fails and value == "new text") or self.restore_fails:
            return False
        self.contents[fmt] = self.handles.pop(handle)
        return True

    def free(self, _fmt, handle):
        del self.handles[handle]


class ClipboardTransactionTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeClipboardApi()
        self.writer = ClipboardWriter(self.api)

    def tearDown(self):
        self.assertFalse(self.api.opened)
        self.assertEqual(self.api.handles, {}, "untransferred memory handles leaked")

    def test_success_transfers_new_text_and_frees_backups(self):
        self.writer.copy("new text", 123)
        self.assertEqual(self.api.contents, {13: "new text"})

    def test_busy_clipboard_is_not_cleared(self):
        previous = self.api.contents.copy()
        self.api.busy = True
        with self.assertRaises(ClipboardError) as error:
            self.writer.copy("new text", 123)
        self.assertTrue(error.exception.retryable)
        self.assertEqual(self.api.contents, previous)
        self.assertEqual(self.api.clear_calls, 0)

    def test_backup_failure_never_clears_original(self):
        previous = self.api.contents.copy()
        self.api.backup_fails = True
        with self.assertRaises(ClipboardError):
            self.writer.copy("new text", 123)
        self.assertEqual(self.api.contents, previous)
        self.assertEqual(self.api.clear_calls, 0)

    def test_incomplete_backup_does_not_block_normal_copy(self):
        self.api.backup_incomplete = True
        self.writer.copy("new text", 123)
        self.assertEqual(self.api.contents, {13: "new text"})

    def test_write_failure_with_incomplete_backup_reports_partial_recovery(self):
        self.api.backup_incomplete = True
        self.api.write_fails = True
        with self.assertRaisesRegex(ClipboardError, "could not be restored") as error:
            self.writer.copy("new text", 123)
        self.assertFalse(error.exception.retryable)
        self.assertEqual(self.api.contents, {13: "previous text"})

    def test_failed_write_restores_text_and_other_formats(self):
        previous = self.api.contents.copy()
        self.api.write_fails = True
        with self.assertRaisesRegex(ClipboardError, "previous clipboard restored") as error:
            self.writer.copy("new text", 123)
        self.assertTrue(error.exception.retryable)
        self.assertEqual(self.api.contents, previous)

    def test_restore_failure_is_explicit_not_reported_as_success(self):
        self.api.write_fails = True
        self.api.restore_fails = True
        with self.assertRaisesRegex(ClipboardError, "could not be restored") as error:
            self.writer.copy("new text", 123)
        self.assertFalse(error.exception.retryable)

    def test_empty_previous_clipboard_rolls_back_to_empty(self):
        self.api.contents = {}
        self.api.write_fails = True
        with self.assertRaises(ClipboardError):
            self.writer.copy("new text", 123)
        self.assertEqual(self.api.contents, {})


@unittest.skipUnless(sys.platform == "win32", "Windows memory handles")
class NativeClipboardMemoryTests(unittest.TestCase):
    def test_unicode_allocation_and_backup_without_touching_clipboard(self):
        api = WindowsClipboardApi()
        text = "\u4f60\u597d\n    exact text\n"
        handle = api.allocate_text(text)
        duplicate = 0
        try:
            duplicate = api.ole32.OleDuplicateData(handle, CF_UNICODETEXT, 2)
            self.assertTrue(duplicate)
            pointer = api.kernel32.GlobalLock(duplicate)
            self.assertTrue(pointer)
            try:
                self.assertEqual(ctypes.wstring_at(pointer), text)
            finally:
                api.kernel32.GlobalUnlock(duplicate)
        finally:
            if duplicate:
                api.free(CF_UNICODETEXT, duplicate)
            api.free(CF_UNICODETEXT, handle)

    def test_null_character_is_rejected_before_mutation(self):
        with self.assertRaisesRegex(ClipboardError, "null character"):
            WindowsClipboardApi().allocate_text("before\0after")


@unittest.skipUnless(sys.platform == "win32", "Windows API adapter")
class NativeSnapshotRegressionTests(unittest.TestCase):
    """Exercise the real snapshot algorithm, without touching the system clipboard."""

    def setUp(self):
        self.api = WindowsClipboardApi()
        self.api.user32 = Mock()
        self.api.ole32 = Mock()
        self.api.gdi32 = Mock()
        self.api.allocate_text = Mock(return_value=999)
        self.api.free = Mock()
        self.api.user32.OpenClipboard.return_value = 1
        self.api.user32.EmptyClipboard.return_value = 1
        self.api.user32.SetClipboardData.return_value = 1
        self.api.user32.GetClipboardData.return_value = 100
        self.api.ole32.OleDuplicateData.return_value = 200
        self.writer = ClipboardWriter(self.api)

    def tearDown(self):
        ctypes.set_last_error(0)

    def test_unreadable_extra_format_does_not_block_text_copy(self):
        self.api.user32.EnumClipboardFormats.side_effect = [13, 0xC001, 0]
        self.api.user32.GetClipboardData.side_effect = [100, 0]
        self.writer.copy("recognized", 123)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)
        self.api.user32.CloseClipboard.assert_called_once()
        self.api.free.assert_called_once_with(13, 200)

    def test_no_readable_backup_still_allows_copy(self):
        self.api.user32.EnumClipboardFormats.side_effect = [0xC001, 0]
        self.api.user32.GetClipboardData.return_value = 0
        self.writer.copy("recognized", 123)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)
        self.api.free.assert_not_called()

    def test_unreadable_first_format_does_not_prevent_later_text_backup(self):
        self.api.user32.EnumClipboardFormats.side_effect = [0xC001, 13, 0]
        self.api.user32.GetClipboardData.side_effect = [0, 100]
        snapshot = self.api.snapshot()
        self.assertEqual(snapshot.handles, [(13, 200)])
        self.assertFalse(snapshot.complete)

    def test_private_and_owner_display_formats_are_skipped_without_reading(self):
        self.api.user32.EnumClipboardFormats.side_effect = [0x80, 0x200, 0x2FF, 13, 0]
        self.writer.copy("recognized", 123)
        self.api.user32.GetClipboardData.assert_called_once_with(13)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)

    def test_duplicate_failure_does_not_block_copy(self):
        self.api.user32.EnumClipboardFormats.side_effect = [13, 0]
        self.api.ole32.OleDuplicateData.return_value = 0
        self.writer.copy("recognized", 123)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)

    def test_enhanced_metafile_backup_failure_does_not_block_copy(self):
        self.api.user32.EnumClipboardFormats.side_effect = [14, 0]
        self.api.gdi32.CopyEnhMetaFileW.return_value = 0
        self.writer.copy("recognized", 123)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)
        self.api.free.assert_not_called()

    def test_clear_failure_leaves_backup_handles_owned_by_the_app(self):
        self.api.user32.EnumClipboardFormats.side_effect = [13, 0]
        self.api.user32.EmptyClipboard.return_value = 0
        with self.assertRaises(ClipboardError) as error:
            self.writer.copy("recognized", 123)
        self.assertTrue(error.exception.retryable)
        self.api.user32.SetClipboardData.assert_not_called()
        self.api.free.assert_any_call(13, 200)
        self.api.free.assert_any_call(13, 999)
        self.assertEqual(self.api.free.call_count, 2)

    def test_allocation_failure_never_opens_or_clears_clipboard(self):
        self.api.allocate_text.side_effect = ClipboardError("allocation failed")
        with self.assertRaisesRegex(ClipboardError, "allocation failed"):
            self.writer.copy("recognized", 123)
        self.api.user32.OpenClipboard.assert_not_called()
        self.api.user32.EmptyClipboard.assert_not_called()

    def test_enumeration_error_marks_backup_incomplete_without_blocking_copy(self):
        def fail_enumeration(_format):
            ctypes.set_last_error(5)
            return 0

        self.api.user32.EnumClipboardFormats.side_effect = fail_enumeration
        snapshot = self.api.snapshot()
        self.assertFalse(snapshot.complete)
        self.assertEqual(snapshot.handles, [])
        self.writer.copy("recognized", 123)
        self.api.user32.SetClipboardData.assert_called_once_with(13, 999)

    def test_partial_restore_never_claims_complete_recovery(self):
        self.api.user32.EnumClipboardFormats.side_effect = [13, 0xC001, 0]
        self.api.user32.GetClipboardData.side_effect = [100, 0]
        self.api.user32.SetClipboardData.side_effect = [0, 200]
        with self.assertRaisesRegex(ClipboardError, "could not be restored") as error:
            self.writer.copy("recognized", 123)
        self.assertFalse(error.exception.retryable)
        self.api.free.assert_called_once_with(13, 999)
        self.api.user32.CloseClipboard.assert_called_once()

    def test_unexpected_snapshot_exception_frees_backups_before_propagating(self):
        self.api.user32.EnumClipboardFormats.side_effect = [13, RuntimeError("unexpected")]
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            self.writer.copy("recognized", 123)
        self.api.user32.EmptyClipboard.assert_not_called()
        self.api.free.assert_any_call(13, 200)
        self.api.free.assert_any_call(13, 999)
        self.assertEqual(self.api.free.call_count, 2)
        self.api.user32.CloseClipboard.assert_called_once()


if __name__ == "__main__":
    unittest.main()
