import queue
import threading
import unittest
from unittest.mock import Mock, patch

from quickcrop_ocr.hotkey import Hotkey, HotkeyRegistrationError, MOD_NOREPEAT, WM_HOTKEY


class HotkeyTests(unittest.TestCase):
    def test_start_timeout_is_not_reported_as_success(self):
        hotkey = Hotkey(Mock())
        hotkey.ready = Mock()
        hotkey.ready.wait.return_value = False
        with patch("quickcrop_ocr.hotkey.threading.Thread") as thread:
            thread.return_value.is_alive.return_value = False
            with self.assertRaisesRegex(HotkeyRegistrationError, "Timed out"):
                hotkey.start()
        self.assertFalse(hotkey.running)
        self.assertTrue(hotkey.stop_requested.is_set())
        hotkey.ready.clear.assert_called_once()

    def test_registration_failure_signals_ready_and_reports_failure(self):
        user32, kernel32 = Mock(), Mock()
        user32.RegisterHotKey.return_value = False
        hotkey = Hotkey(Mock())
        with patch("quickcrop_ocr.hotkey._load_apis", return_value=(user32, kernel32)):
            with self.assertRaisesRegex(HotkeyRegistrationError, "Another app"):
                hotkey.start()
            hotkey.stop()
        self.assertTrue(hotkey.ready.is_set())
        self.assertFalse(hotkey.running)
        user32.UnregisterHotKey.assert_not_called()

    def test_native_api_startup_exception_is_propagated(self):
        hotkey = Hotkey(Mock())
        with patch("quickcrop_ocr.hotkey._load_apis", side_effect=OSError("not available")):
            with self.assertRaisesRegex(HotkeyRegistrationError, "not available"):
                hotkey.start()
            hotkey.stop()
        self.assertFalse(hotkey.running)

    def test_stop_during_startup_unregisters_late_registration(self):
        user32, kernel32 = Mock(), Mock()
        user32.RegisterHotKey.return_value = True
        hotkey = Hotkey(Mock())
        hotkey.stop_requested.set()
        with patch("quickcrop_ocr.hotkey._load_apis", return_value=(user32, kernel32)):
            hotkey._message_loop()
        user32.GetMessageW.assert_not_called()
        user32.UnregisterHotKey.assert_called_once_with(None, hotkey.hotkey_id)
        self.assertFalse(hotkey.running)

    def test_message_loop_failure_is_reported_and_running_cleared(self):
        user32, kernel32 = Mock(), Mock()
        user32.RegisterHotKey.return_value = True
        user32.GetMessageW.return_value = -1
        report = Mock()
        hotkey = Hotkey(Mock(), on_error=report)
        with patch("quickcrop_ocr.hotkey._load_apis", return_value=(user32, kernel32)):
            hotkey._message_loop()
        self.assertFalse(hotkey.running)
        self.assertIsNone(hotkey.thread_id)
        report.assert_called_once()
        user32.UnregisterHotKey.assert_called_once()

    def test_start_stop_restart_and_no_repeat_registration(self):
        messages = queue.Queue()
        received = threading.Event()
        user32, kernel32 = Mock(), Mock()
        kernel32.GetCurrentThreadId.return_value = 123
        user32.RegisterHotKey.return_value = True
        user32.PostThreadMessageW.side_effect = lambda *_: messages.put("quit") or True
        hotkey = Hotkey(received.set)

        def get_message(pointer, *_args):
            if messages.get(timeout=2) == "quit":
                return 0
            pointer._obj.message = WM_HOTKEY
            pointer._obj.wParam = hotkey.hotkey_id
            return 1

        user32.GetMessageW.side_effect = get_message
        with patch("quickcrop_ocr.hotkey._load_apis", return_value=(user32, kernel32)):
            try:
                for _ in range(2):
                    received.clear()
                    hotkey.start()
                    self.assertTrue(hotkey.running)
                    messages.put("capture")
                    self.assertTrue(received.wait(timeout=1))
                    hotkey.stop()
                    self.assertFalse(hotkey.thread.is_alive())
            finally:
                hotkey.stop()
        self.assertEqual(user32.RegisterHotKey.call_count, 2)
        self.assertEqual(user32.UnregisterHotKey.call_count, 2)
        self.assertEqual(user32.PeekMessageW.call_count, 2)
        self.assertTrue(user32.RegisterHotKey.call_args.args[2] & MOD_NOREPEAT)


if __name__ == "__main__":
    unittest.main()
