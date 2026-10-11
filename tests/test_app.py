import io
import json
import queue
import time
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import Mock, patch

from PIL import Image

from quickcrop_ocr.app import AppConfig, QuickCropApp, StatusWindow, UiEvent, main
from quickcrop_ocr.clipboard import ClipboardError
from quickcrop_ocr.config import RuntimeConfig, SetupCancelled
from quickcrop_ocr.hotkey import HotkeyRegistrationError
from quickcrop_ocr.layout import TEXT_LAYOUTS
from quickcrop_ocr.ocr import OcrError, OcrResult, RequestControl


def make_app():
    app = QuickCropApp.__new__(QuickCropApp)
    app.config = AppConfig(RuntimeConfig("test-only-key", "qwen3-vl-plus", "beijing", "preserve"))
    app.root = Mock()
    app.root.winfo_id.return_value = 123
    app.events = queue.Queue()
    app.status = Mock()
    app.overlay = Mock()
    app.clipboard = Mock()
    app.hotkey = Mock()
    app.ocr_thread = None
    app.is_capturing = False
    app.stopping = False
    app.job_id = 1
    app.control = None
    app.progress = "Reading text"
    app.last_result = None
    app.copy_generation = 0
    app.copying = False
    return app


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)

    def test_success_keeps_exact_text_and_allows_copy_again(self):
        result = OcrResult("    exact\n", "qwen:test")
        self.app._copy_result(result)
        self.app._copy_last()
        self.assertIs(self.app.last_result, result)
        self.assertEqual(self.app.clipboard.copy.call_count, 2)
        self.app.clipboard.copy.assert_called_with("    exact\n", 123)
        self.assertTrue(self.app.status.show.call_args.kwargs["can_copy"])

    def test_clipboard_busy_retries_three_times_and_retains_result(self):
        self.app.clipboard.copy.side_effect = ClipboardError("busy", retryable=True)
        result = OcrResult("recognized", "qwen:test")
        self.app._copy_result(result)
        self.app.root.after.call_args.args[1]()
        self.app.root.after.call_args.args[1]()
        self.assertEqual(self.app.clipboard.copy.call_count, 3)
        self.assertIs(self.app.last_result, result)
        self.assertFalse(self.app.copying)
        self.assertIn("retained", self.app.status.show.call_args.args[0])

    def test_retry_copy_succeeds_without_another_ocr_call(self):
        self.app.clipboard.copy.side_effect = [ClipboardError("busy", retryable=True), None]
        with patch("quickcrop_ocr.app.recognize_text") as recognize:
            self.app._copy_result(OcrResult("recognized", "qwen:test"))
            self.app.root.after.call_args.args[1]()
        recognize.assert_not_called()
        self.assertFalse(self.app.copying)
        self.assertIn("Copied", self.app.status.show.call_args.args[0])

    def test_cancel_pending_copy_invalidates_scheduled_retry(self):
        self.app.clipboard.copy.side_effect = ClipboardError("busy", retryable=True)
        self.app._copy_result(OcrResult("recognized", "qwen:test"))
        retry = self.app.root.after.call_args.args[1]
        self.app._cancel_operation()
        retry()
        self.app.clipboard.copy.assert_called_once()

    def test_cancel_ignores_late_result(self):
        control = self.app.control = RequestControl()
        self.app._cancel_operation()
        self.app._handle_job_event(UiEvent("result", 1, OcrResult("late", "qwen:test")))
        self.assertTrue(control.cancel_event.is_set())
        self.app.clipboard.copy.assert_not_called()

    def test_old_job_events_cannot_override_new_job(self):
        self.app.control = RequestControl()
        self.app.job_id = 2
        self.app._handle_job_event(UiEvent("result", 1, OcrResult("old", "qwen:test")))
        self.assertIsNotNone(self.app.control)
        self.app.clipboard.copy.assert_not_called()

    def test_busy_hotkey_reopens_status_instead_of_new_capture(self):
        self.app.control = RequestControl()
        self.app._start_capture()
        self.app.status.present.assert_called_once()
        self.app.overlay.show.assert_not_called()

    def test_worker_only_queues_events_and_never_calls_tk(self):
        image = Image.new("RGB", (10, 10))
        result = OcrResult("recognized", "qwen:test")
        with patch("quickcrop_ocr.app.recognize_text", return_value=result):
            self.app._recognize_in_background(image, 1, RequestControl())
        self.assertEqual(self.app.root.mock_calls, [])
        self.assertEqual(self.app.events.get_nowait(), UiEvent("result", 1, result))
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_ocr_errors_never_overwrite_clipboard_or_last_result(self):
        previous = self.app.last_result = OcrResult("previous", "qwen:test")
        self.app.control = RequestControl()
        with patch("quickcrop_ocr.app.recognize_text", side_effect=OcrError("truncated")):
            self.app._recognize_in_background(Image.new("RGB", (10, 10)), 1, self.app.control)
        self.app._drain_events()
        self.app.clipboard.copy.assert_not_called()
        self.assertIs(self.app.last_result, previous)
        self.assertIn("truncated", self.app.status.show.call_args.args[0])

    def test_total_deadline_clears_busy_state_and_rejects_late_result(self):
        control = self.app.control = RequestControl(started=time.monotonic() - 60)
        self.app._drain_events()
        self.assertIsNone(self.app.control)
        self.assertTrue(control.cancel_event.is_set())
        self.app._handle_job_event(UiEvent("result", 1, OcrResult("late", "qwen:test")))
        self.app.clipboard.copy.assert_not_called()
        self.assertIn("time budget", self.app.status.show.call_args.args[0])

    def test_capture_error_does_not_leave_app_busy(self):
        self.app.overlay.show.side_effect = OSError("capture unavailable")
        self.app._start_capture()
        self.assertFalse(self.app.is_capturing)
        self.app.overlay.close.assert_called_once()
        self.assertIn("Capture failed", self.app.status.show.call_args.args[0])

    def test_progress_keeps_elapsed_time_and_redacts_key(self):
        self.app.control = RequestControl()
        self.app.events.put(UiEvent("progress", 1, "Retrying test-only-key"))
        self.app._drain_events()
        text = self.app.status.update_message.call_args.args[0]
        self.assertIn("Retrying [redacted]", text)
        self.assertIn("/ 30s", text)
        self.assertIsNotNone(self.app.control)

    def test_terminal_error_is_labeled_and_key_is_redacted(self):
        with redirect_stdout(io.StringIO()) as output:
            self.app._show_status("Rejected test-only-key", is_error=True)
        self.assertEqual(output.getvalue(), "[Error] Rejected [redacted]\n")
        self.assertEqual(self.app.status.show.call_args.args[0], "Rejected [redacted]")

    def test_start_announces_readiness_only_after_registering_hotkey(self):
        with redirect_stdout(io.StringIO()) as output:
            self.app.start()
        self.app.hotkey.start.assert_called_once()
        self.app.root.mainloop.assert_called_once()
        self.assertIn("[Ready]", output.getvalue())
        self.assertIn("Ctrl+Shift+X", output.getvalue())
        self.assertNotIn("test-only-key", output.getvalue())
        self.app.hotkey.start.side_effect = HotkeyRegistrationError("busy")
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(HotkeyRegistrationError):
            self.app.start()
        self.assertNotIn("[Ready]", output.getvalue())

    def test_stop_cancels_active_work_and_is_idempotent(self):
        control = self.app.control = RequestControl()
        self.app.stop()
        self.app.stop()
        self.app._drain_events()
        self.assertTrue(control.cancel_event.is_set())
        self.app.root.destroy.assert_called_once()
        self.app.root.after.assert_not_called()

    def test_capture_to_response_to_copy_pipeline(self):
        text = "    Heading:\n\nParagraph!\n\n- List item: 3.14\n"
        for mode in TEXT_LAYOUTS:
            for reason in ("stop", "length"):
                app = make_app()
                app.config = AppConfig(replace(app.config.runtime, output_format=mode))
                payload = {"output": {"choices": [{
                    "finish_reason": reason,
                    "message": {"role": "assistant", "content": [{"text": text}]},
                }]}}
                with self.subTest(mode=mode, reason=reason), patch(
                    "quickcrop_ocr.ocr.urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps(payload).encode()),
                ):
                    app._on_capture(Image.new("RGB", (10, 10)))
                    app.ocr_thread.join(timeout=2)
                    self.assertFalse(app.ocr_thread.is_alive())
                    app._drain_events()
                if reason == "stop":
                    expected = " ".join(text.split()) if mode == "single_line" else text
                    app.clipboard.copy.assert_called_once_with(expected, 123)
                else:
                    app.clipboard.copy.assert_not_called()
                    self.assertIn("truncated", app.status.show.call_args.args[0])

    def test_crop_failure_resets_capture_state(self):
        self.app.is_capturing = True
        self.app._on_capture_error("image unavailable")
        self.assertFalse(self.app.is_capturing)
        self.assertIn("Capture failed", self.app.status.show.call_args.args[0])

    def test_unknown_event_does_not_end_active_job(self):
        control = self.app.control = RequestControl()
        self.app._handle_job_event(UiEvent("unknown", 1, "unexpected"))
        self.assertIs(self.app.control, control)
        self.app.status.show.assert_not_called()

    def test_hotkey_failure_cancels_active_work_and_reports_error(self):
        control = self.app.control = RequestControl()
        self.app.events.put(UiEvent("hotkey_error", value="Listener stopped; restart required"))
        self.app._drain_events()
        self.assertTrue(control.cancel_event.is_set())
        self.app.overlay.close.assert_called_once()
        self.assertIsNone(self.app.control)
        self.assertIn("restart", self.app.status.show.call_args.args[0])


class StartupTests(unittest.TestCase):
    def test_canceling_setup_does_not_create_a_window(self):
        for error in (SetupCancelled(), EOFError(), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), patch(
                "quickcrop_ocr.app.prompt_runtime_config", side_effect=error
            ), patch("quickcrop_ocr.app.QuickCropApp") as app, redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
                app.assert_not_called()

    def test_startup_failure_and_interrupt_cleanup_and_restore_signal(self):
        for error, exit_code in ((HotkeyRegistrationError("busy"), 2), (KeyboardInterrupt(), 0), (None, 0)):
            with self.subTest(error=type(error).__name__), patch(
                "quickcrop_ocr.app.prompt_runtime_config", return_value=make_app().config.runtime
            ), patch("quickcrop_ocr.app.QuickCropApp") as app, patch(
                "quickcrop_ocr.app.signal.signal", return_value="old-handler"
            ) as set_signal:
                app.return_value.start.side_effect = error
                self.assertEqual(main(), exit_code)
                app.return_value.stop.assert_called_once()
                self.assertEqual(set_signal.call_args.args[1], "old-handler")


class StatusWindowTests(unittest.TestCase):
    def test_persistent_window_reuses_widgets_and_has_cancel_and_copy_controls(self):
        root = Mock()
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        cancel = Mock()
        copy = Mock()
        with patch("quickcrop_ocr.app.tk.Toplevel") as window, patch(
            "quickcrop_ocr.app.tk.Frame"
        ), patch("quickcrop_ocr.app.tk.Scrollbar"), patch(
            "quickcrop_ocr.app.tk.Text"
        ), patch("quickcrop_ocr.app.tk.Button") as button:
            status = StatusWindow(root, cancel, copy)
            status.show("Reading text", busy=True)
            status.update_message("Retrying 2/3\n5s / 30s")
            status.show("Copied", can_copy=True)
            status.show("Failed", can_copy=True, is_error=True)
            window.assert_called_once()
            window.return_value.after.assert_not_called()
            commands = {c.kwargs["text"]: c.kwargs["command"] for c in button.call_args_list}
            commands["Cancel"]()
            commands["Copy again"]()
            cancel.assert_called_once()
            copy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
