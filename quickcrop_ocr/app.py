from __future__ import annotations

import ctypes
import queue
import signal
import threading
import tkinter as tk
import time
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from .clipboard import ClipboardError, ClipboardWriter
from .config import RuntimeConfig, SetupCancelled, prompt_runtime_config
from .hotkey import Hotkey, HotkeyRegistrationError
from .layout import NO_TEXT_MARKER
from .ocr import OcrCancelled, OcrError, OcrResult, RequestControl, recognize_text
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


@dataclass(frozen=True)
class UiEvent:
    kind: str
    job_id: int = 0
    value: object = None


class QuickCropApp:
    def __init__(self, config: AppConfig) -> None:
        enable_dpi_awareness()
        self.config = config
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("QuickCrop OCR")

        self.events: queue.Queue[UiEvent] = queue.Queue()
        self.hotkey = Hotkey(
            on_hotkey=lambda: self.events.put(UiEvent("capture")),
            on_error=lambda message: self.events.put(UiEvent("hotkey_error", value=message)),
        )
        self.overlay = SelectionOverlay(
            self.root, on_capture=self._on_capture, on_error=self._on_capture_error
        )
        self.clipboard = ClipboardWriter()
        self.status = StatusWindow(self.root, self._cancel_operation, self._copy_last)
        self.ocr_thread: threading.Thread | None = None
        self.is_capturing = False
        self.stopping = False
        self.job_id = 0
        self.control: RequestControl | None = None
        self.progress = ""
        self.last_result: OcrResult | None = None
        self.copy_generation = 0
        self.copying = False

        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self.root.after(50, self._drain_events)

    def start(self) -> None:
        try:
            self.hotkey.start()
        except HotkeyRegistrationError as exc:
            self._show_status(str(exc), is_error=True)
            raise

        print("[Ready] QuickCrop OCR is running.")
        print(f"  Capture: {self.config.hotkey_label} | Cancel selection: Esc | Quit: Ctrl+C")
        print("  Cancel an OCR request in its status window.\n", flush=True)
        self.root.mainloop()

    def stop(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        if self.control is not None:
            self.control.cancel_event.set()
        self.control = None
        self.copy_generation += 1
        self.hotkey.stop()
        self.overlay.close()
        self.status.close()
        self.last_result = None
        self.root.destroy()

    def _drain_events(self) -> None:
        if self.stopping:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            if event.kind == "capture":
                self._start_capture()
            elif event.kind == "hotkey_error":
                self.overlay.close()
                self.is_capturing = False
                self._cancel_operation()
                self._show_status(str(event.value), is_error=True)
            else:
                self._handle_job_event(event)

        if self.control is not None:
            try:
                self.control.remaining()
            except OcrError as exc:
                self.control.cancel_event.set()
                self.control = None
                self._show_status(str(exc), is_error=True)
            else:
                elapsed = time.monotonic() - self.control.started
                self.status.update_message(f"{self.progress}\n{elapsed:.0f}s / {self.control.timeout:g}s")
        if not self.stopping:
            self.root.after(50, self._drain_events)

    def _handle_job_event(self, event: UiEvent) -> None:
        if event.kind not in {"progress", "result", "canceled", "error"}:
            return
        if self.control is None or event.job_id != self.job_id:
            return
        try:
            self.control.remaining()
        except OcrError as exc:
            self.control.cancel_event.set()
            self.control = None
            self._show_status(str(exc), is_error=True)
            return
        if event.kind == "progress":
            message = str(event.value)
            key = self.config.runtime.api_key
            if key:
                message = message.replace(key, "[redacted]")
            if message != self.progress:
                print(f"[OCR] {message}", flush=True)
            self.progress = message
            return
        self.control = None
        if event.kind == "result" and isinstance(event.value, OcrResult):
            self._copy_result(event.value)
        elif event.kind == "canceled":
            self._show_status("OCR canceled. Clipboard unchanged.")
        else:
            self._show_status(str(event.value), is_error=True)

    def _start_capture(self) -> None:
        if self.stopping or self.is_capturing:
            return
        if self.control is not None or self.copying:
            self.status.present()
            print("[Busy] Still processing; the status window has been reopened.", flush=True)
            return

        self.copy_generation += 1
        self.is_capturing = True
        self.status.hide()
        self.root.update_idletasks()
        try:
            self.overlay.show()
        except Exception as exc:
            self.overlay.close()
            self._on_capture_error(str(exc))

    def _on_capture_error(self, message: str) -> None:
        self.is_capturing = False
        if not self.stopping:
            self._show_status(f"Capture failed: {message}", is_error=True)

    def _on_capture(self, image: Image.Image | None) -> None:
        self.is_capturing = False
        if self.stopping:
            if image is not None:
                image.close()
            return
        if image is None:
            self._show_status("Capture canceled")
            return

        self.job_id += 1
        job_id = self.job_id
        self.control = RequestControl(
            on_progress=lambda message: self.events.put(UiEvent("progress", job_id, message))
        )
        self.progress = "Preparing image for Qwen"
        print(f"[OCR] {self.progress}", flush=True)
        self.status.show(self.progress, busy=True)
        self.ocr_thread = threading.Thread(
            target=self._recognize_in_background,
            args=(image, job_id, self.control),
            daemon=True,
            name="quickcrop-ocr",
        )
        try:
            self.ocr_thread.start()
        except RuntimeError as exc:
            self.control = None
            image.close()
            self._show_status(f"Could not start OCR: {exc}", is_error=True)

    def _recognize_in_background(self, image: Image.Image, job_id: int, control: RequestControl) -> None:
        try:
            result = recognize_text(image, self.config.runtime, control=control)
        except OcrCancelled:
            self.events.put(UiEvent("canceled", job_id))
        except OcrError as exc:
            self.events.put(UiEvent("error", job_id, f"OCR failed: {exc}"))
        except Exception as exc:  # Defensive boundary for a long-running utility.
            self.events.put(UiEvent("error", job_id, f"Unexpected OCR error: {exc}"))
        else:
            self.events.put(UiEvent("result", job_id, result))
        finally:
            image.close()

    def _cancel_operation(self) -> None:
        if self.control is not None:
            self.control.cancel_event.set()
            self.control = None
        self.copy_generation += 1
        self.copying = False
        self._show_status("Canceled. No further result will be copied.")

    def _copy_result(self, result: OcrResult) -> None:
        if not result.text.strip() or result.text.strip() == NO_TEXT_MARKER:
            self._show_status("No readable text found", is_error=True)
            return

        self.last_result = result
        self._copy_last()

    def _copy_last(self) -> None:
        if self.stopping or self.is_capturing or self.control is not None or self.copying or self.last_result is None:
            return
        self.copy_generation += 1
        self.copying = True
        self._try_copy(self.copy_generation)

    def _try_copy(self, generation: int, attempt: int = 1) -> None:
        if self.stopping or generation != self.copy_generation or self.last_result is None:
            return
        try:
            self.clipboard.copy(self.last_result.text, self.root.winfo_id())
        except ClipboardError as exc:
            if exc.retryable and attempt < 3:
                self.status.show(f"{exc}. Retrying copy {attempt + 1}/3...", busy=True)
                self.root.after(150, lambda: self._try_copy(generation, attempt + 1))
                return
            self.copying = False
            self._show_status(f"{exc}. OCR result retained for another copy attempt.", is_error=True)
        except Exception as exc:
            self.copying = False
            self._show_status(f"Clipboard error: {exc}. OCR result retained.", is_error=True)
        else:
            self.copying = False
            self._show_status(f"Copied {len(self.last_result.text)} characters")

    def _show_status(self, message: str, *, is_error: bool = False) -> None:
        key = self.config.runtime.api_key
        if key:
            message = message.replace(key, "[redacted]")
        print(f"[{'Error' if is_error else 'Status'}] {message}", flush=True)
        self.status.show(message, is_error=is_error, can_copy=self.last_result is not None)


class StatusWindow:
    def __init__(self, root: tk.Tk, on_cancel: Callable[[], None], on_copy: Callable[[], None]) -> None:
        self.root = root
        self.on_cancel = on_cancel
        self.on_copy = on_copy
        self.window: tk.Toplevel | None = None
        self.label: tk.Text | None = None
        self.message = ""

    def show(self, message: str, *, busy: bool = False, is_error: bool = False, can_copy: bool = False) -> None:
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.title("QuickCrop OCR")
            self.window.attributes("-topmost", True)
            self.window.resizable(False, False)
            self.window.protocol("WM_DELETE_WINDOW", self.hide)
            width = min(440, max(240, self.root.winfo_screenwidth() - 60))
            controls = tk.Frame(self.window, padx=12, pady=8)
            controls.pack(side="bottom", fill="x")
            self.cancel_button = tk.Button(controls, text="Cancel", command=self.on_cancel)
            self.copy_button = tk.Button(controls, text="Copy again", command=self.on_copy)
            self.close_button = tk.Button(controls, text="Close", command=self.hide)
            body = tk.Frame(self.window)
            body.pack(fill="both", expand=True)
            scrollbar = tk.Scrollbar(body)
            scrollbar.pack(side="right", fill="y")
            self.label = tk.Text(
                body, wrap="word", borderwidth=0, highlightthickness=0,
                padx=16, pady=14, font=("Segoe UI", 10), height=7,
                state="disabled", yscrollcommand=scrollbar.set,
            )
            self.label.pack(fill="both", expand=True)
            scrollbar.configure(command=self.label.yview)
            x = max(0, self.root.winfo_screenwidth() - width - 28)
            y = max(0, self.root.winfo_screenheight() - 300)
            self.window.geometry(f"{width}x220+{x}+{y}")
        assert self.label is not None
        self.label.configure(fg="#b91c1c" if is_error else "#161616")
        self.update_message(message)
        for button in (self.cancel_button, self.copy_button, self.close_button):
            button.pack_forget()
        if busy:
            self.cancel_button.pack(side="right")
        else:
            self.close_button.pack(side="right")
            if can_copy:
                self.copy_button.pack(side="left")
        self.present()

    def update_message(self, message: str) -> None:
        if self.label is not None and message != self.message:
            self.message = message
            self.label.configure(state="normal")
            self.label.delete("1.0", "end")
            self.label.insert("1.0", message)
            self.label.configure(state="disabled")

    def present(self) -> None:
        if self.window is not None:
            self.window.deiconify()
            self.window.lift()

    def hide(self) -> None:
        if self.window is not None:
            self.window.withdraw()

    def close(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        self.label = None
        self.message = ""


def main() -> int:
    try:
        runtime_config = prompt_runtime_config()
    except (SetupCancelled, EOFError, KeyboardInterrupt):
        print("\nSetup canceled.")
        return 0
    app = QuickCropApp(AppConfig(runtime=runtime_config))

    def handle_sigint(_signum: int, _frame: object) -> None:
        app.stop()

    previous_handler = signal.signal(signal.SIGINT, handle_sigint)

    try:
        app.start()
    except HotkeyRegistrationError:
        return 2
    except KeyboardInterrupt:
        return 0
    finally:
        app.stop()
        signal.signal(signal.SIGINT, previous_handler)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
