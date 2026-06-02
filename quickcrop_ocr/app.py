from __future__ import annotations

import queue
import signal
import threading
import tkinter as tk
import ctypes
from dataclasses import dataclass

from PIL import Image

from .config import RuntimeConfig, prompt_runtime_config
from .hotkey import Hotkey, HotkeyRegistrationError
from .ocr import NoOcrBackendError, OcrError, OcrResult, recognize_text
from .overlay import SelectionOverlay


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    hotkey_label: str = "Ctrl+Shift+X"


class QuickCropApp:
    def __init__(self, config: AppConfig) -> None:
        enable_dpi_awareness()
        self.config = config
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("QuickCrop OCR")

        self.events: queue.Queue[str] = queue.Queue()
        self.hotkey = Hotkey(on_hotkey=lambda: self.events.put("capture"))
        self.overlay = SelectionOverlay(self.root, on_capture=self._on_capture)
        self.ocr_thread: threading.Thread | None = None
        self.is_capturing = False

        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self.root.after(50, self._drain_events)

    def start(self) -> None:
        try:
            self.hotkey.start()
        except HotkeyRegistrationError as exc:
            self._show_toast(str(exc), is_error=True)
            raise

        print("QuickCrop OCR is running.")
        print(f"Press {self.config.hotkey_label} to capture text. Press Ctrl+C here to quit.")
        self._show_toast(f"QuickCrop OCR ready ({self.config.hotkey_label})")
        self.root.mainloop()

    def stop(self) -> None:
        self.hotkey.stop()
        self.root.quit()

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "capture":
                self._start_capture()

        self.root.after(50, self._drain_events)

    def _start_capture(self) -> None:
        if self.is_capturing or self.ocr_thread and self.ocr_thread.is_alive():
            return

        self.is_capturing = True
        self.overlay.show()

    def _on_capture(self, image: Image.Image | None) -> None:
        self.is_capturing = False
        if image is None:
            self._show_toast("Capture canceled")
            return

        self._show_toast("Reading text...")
        self.ocr_thread = threading.Thread(
            target=self._recognize_and_copy,
            args=(image.copy(),),
            daemon=True,
            name="quickcrop-ocr",
        )
        self.ocr_thread.start()

    def _recognize_and_copy(self, image: Image.Image) -> None:
        try:
            result = recognize_text(image, self.config.runtime)
        except NoOcrBackendError as exc:
            message = str(exc)
            print(message)
            self.root.after(0, lambda message=message: self._show_toast(message, is_error=True))
            return
        except OcrError as exc:
            message = f"OCR failed: {exc}"
            print(message)
            self.root.after(0, lambda message=message: self._show_toast(message, is_error=True))
            return
        except Exception as exc:  # Defensive boundary for a long-running utility.
            message = f"Unexpected OCR error: {exc}"
            print(message)
            self.root.after(0, lambda message=message: self._show_toast(message, is_error=True))
            return

        self.root.after(0, lambda: self._copy_result(result))

    def _copy_result(self, result: OcrResult) -> None:
        text = result.text.strip()
        if not text or text == "[NO_TEXT_DETECTED]":
            self._show_toast("No readable text found", is_error=True)
            return

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
        except tk.TclError as exc:
            self._show_toast(f"Clipboard error: {exc}", is_error=True)
            return

        self._show_toast(f"Copied {len(text)} characters")

    def _show_toast(self, message: str, *, is_error: bool = False) -> None:
        Toast(self.root, message, is_error=is_error).show()


class Toast:
    def __init__(self, root: tk.Tk, message: str, *, is_error: bool = False) -> None:
        self.root = root
        self.message = message
        self.is_error = is_error
        self.window: tk.Toplevel | None = None

    def show(self) -> None:
        if self.window is not None:
            self.window.destroy()

        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.95)

        bg = "#7f1d1d" if self.is_error else "#111827"
        fg = "#ffffff"
        label = tk.Label(
            self.window,
            text=self.message,
            bg=bg,
            fg=fg,
            padx=16,
            pady=10,
            font=("Segoe UI", 10),
        )
        label.pack()

        self.window.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = screen_w - width - 28
        y = screen_h - height - 48
        self.window.geometry(f"+{x}+{y}")
        self.window.after(2200, self._close)

    def _close(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()


def main() -> int:
    runtime_config = prompt_runtime_config()
    app = QuickCropApp(AppConfig(runtime=runtime_config))

    def handle_sigint(_signum: int, _frame: object) -> None:
        app.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        app.start()
    except HotkeyRegistrationError:
        return 2
    except KeyboardInterrupt:
        app.stop()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
