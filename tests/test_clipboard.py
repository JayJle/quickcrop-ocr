import ctypes
import sys
import unittest

from quickcrop_ocr.clipboard import CF_UNICODETEXT, ClipboardError, ClipboardWriter, WindowsClipboardApi


class FakeClipboardApi:
    def __init__(self):
        self.contents = {13: "previous text", 0xC001: b"<b>rich text</b>"}
        self.handles = {}
        self.next_handle = 1
        self.busy = False
        self.backup_fails = False
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
        return [(fmt, self.allocate(value)) for fmt, value in self.contents.items()]

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


if __name__ == "__main__":
    unittest.main()
