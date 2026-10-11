import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from quickcrop_ocr.overlay import SelectionOverlay


class FrozenCaptureTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.callback = Mock()
        self.overlay = SelectionOverlay(self.root, self.callback)
        self.overlay.virtual_left = -100
        self.overlay.virtual_top = -50
        self.overlay.virtual_width = 200
        self.overlay.virtual_height = 100
        self.snapshot = Image.new("RGB", (200, 100), "red")
        self.snapshot.paste("blue", (20, 20, 40, 40))

    def tearDown(self):
        self.overlay.close()
        self.snapshot.close()
        for call in self.callback.call_args_list:
            if call.args[0] is not None:
                call.args[0].close()

    def test_snapshot_is_taken_before_overlay_and_not_on_release(self):
        order = []
        with patch.object(self.overlay, "_set_virtual_screen"), patch(
            "quickcrop_ocr.overlay.ImageGrab.grab", side_effect=lambda **_: order.append("capture") or self.snapshot
        ) as grab, patch(
            "quickcrop_ocr.overlay.tk.Toplevel", side_effect=lambda *_: order.append("overlay") or Mock()
        ), patch("quickcrop_ocr.overlay.tk.Canvas"), patch("quickcrop_ocr.overlay.ImageTk.PhotoImage"):
            self.overlay.show()
            self.overlay._on_press(SimpleNamespace(x_root=-80, y_root=-30))
            self.overlay._on_release(SimpleNamespace(x_root=-60, y_root=-10))

        self.assertEqual(order, ["capture", "overlay"])
        grab.assert_called_once_with(all_screens=True)
        crop = self.callback.call_args.args[0]
        self.assertEqual(crop.size, (20, 20))
        self.assertEqual(crop.getpixel((0, 0)), (0, 0, 255))
        self.root.after.assert_not_called()
        self.assertIsNone(self.overlay.snapshot)

    def test_reverse_drag_and_negative_monitor_coordinates(self):
        self.overlay.snapshot = self.snapshot
        self.overlay._on_press(SimpleNamespace(x_root=-60, y_root=-10))
        self.overlay._on_release(SimpleNamespace(x_root=-80, y_root=-30))
        crop = self.callback.call_args.args[0]
        self.assertEqual(crop.size, (20, 20))
        self.assertEqual(crop.getpixel((19, 19)), (0, 0, 255))

    def test_outside_screen_selection_is_clamped(self):
        self.overlay.snapshot = self.snapshot
        self.overlay._on_press(SimpleNamespace(x_root=-150, y_root=-100))
        self.overlay._on_release(SimpleNamespace(x_root=150, y_root=100))
        self.assertEqual(self.callback.call_args.args[0].size, (200, 100))

    def test_tiny_selection_and_escape_release_snapshot(self):
        for escape in (False, True):
            with self.subTest(escape=escape):
                self.overlay.snapshot = Image.new("RGB", (200, 100))
                self.overlay._on_press(SimpleNamespace(x_root=0, y_root=0))
                if escape:
                    self.overlay._cancel()
                else:
                    self.overlay._on_release(SimpleNamespace(x_root=2, y_root=2))
                self.assertIsNone(self.overlay.snapshot)
                self.assertIsNone(self.callback.call_args.args[0])

    def test_display_size_mismatch_fails_before_overlay(self):
        with patch.object(self.overlay, "_set_virtual_screen"), patch(
            "quickcrop_ocr.overlay.ImageGrab.grab", return_value=Image.new("RGB", (10, 10))
        ), patch("quickcrop_ocr.overlay.tk.Toplevel") as window:
            with self.assertRaisesRegex(OSError, "Display size changed"):
                self.overlay.show()
        window.assert_not_called()
        self.assertIsNone(self.overlay.snapshot)

    def test_crop_error_releases_snapshot_and_reports_failure(self):
        on_error = Mock()
        self.overlay.on_error = on_error
        self.overlay.snapshot = self.snapshot
        self.overlay._on_press(SimpleNamespace(x_root=-80, y_root=-30))
        with patch.object(self.snapshot, "crop", side_effect=OSError("crop failed")):
            self.overlay._on_release(SimpleNamespace(x_root=-60, y_root=-10))
        on_error.assert_called_once_with("crop failed")
        self.callback.assert_not_called()
        self.assertIsNone(self.overlay.snapshot)


if __name__ == "__main__":
    unittest.main()
