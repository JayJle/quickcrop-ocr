from __future__ import annotations

import ctypes
import tkinter as tk
from collections.abc import Callable

from PIL import Image, ImageGrab, ImageTk


SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class SelectionOverlay:
    def __init__(
        self, root: tk.Tk, on_capture: Callable[[Image.Image | None], None],
        *, on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root
        self.on_capture = on_capture
        self.on_error = on_error
        self.window: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self.start_x = 0
        self.start_y = 0
        self.current_rect: int | None = None
        self.dim_label: int | None = None
        self.virtual_left = 0
        self.virtual_top = 0
        self.virtual_width = 0
        self.virtual_height = 0
        self.snapshot: Image.Image | None = None
        self.preview: ImageTk.PhotoImage | None = None

    def show(self) -> None:
        self._set_virtual_screen()
        # Freeze before creating the overlay. Only the selected crop leaves here.
        self.snapshot = ImageGrab.grab(all_screens=True)
        if self.snapshot.size != (self.virtual_width, self.virtual_height):
            self.close()
            raise OSError("Display size changed during capture. Please try again.")
        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="black", cursor="crosshair")
        self.window.geometry(
            f"{self.virtual_width}x{self.virtual_height}+{self.virtual_left}+{self.virtual_top}"
        )

        self.canvas = tk.Canvas(
            self.window,
            width=self.virtual_width,
            height=self.virtual_height,
            highlightthickness=0,
            bg="black",
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        self.preview = ImageTk.PhotoImage(self.snapshot, master=self.window)
        self.canvas.create_image(0, 0, image=self.preview, anchor="nw")

        self.window.bind("<ButtonPress-1>", self._on_press)
        self.window.bind("<B1-Motion>", self._on_drag)
        self.window.bind("<ButtonRelease-1>", self._on_release)
        self.window.bind("<Escape>", self._cancel)
        self.window.focus_force()

    def _set_virtual_screen(self) -> None:
        user32 = ctypes.windll.user32
        self.virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self.virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self.virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        self.virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    def _on_press(self, event: tk.Event) -> None:
        self.start_x = int(event.x_root)
        self.start_y = int(event.y_root)
        self._draw_selection(self.start_x, self.start_y, self.start_x, self.start_y)

    def _on_drag(self, event: tk.Event) -> None:
        self._draw_selection(self.start_x, self.start_y, int(event.x_root), int(event.y_root))

    def _on_release(self, event: tk.Event) -> None:
        end_x = int(event.x_root)
        end_y = int(event.y_root)
        left, top, right, bottom = _normalize_rect(self.start_x, self.start_y, end_x, end_y)

        image = None
        error: Exception | None = None
        try:
            if self.snapshot is not None:
                bbox = (
                    max(0, left - self.virtual_left),
                    max(0, top - self.virtual_top),
                    min(self.virtual_width, right - self.virtual_left),
                    min(self.virtual_height, bottom - self.virtual_top),
                )
                if bbox[2] - bbox[0] >= 4 and bbox[3] - bbox[1] >= 4:
                    image = self.snapshot.crop(bbox)
        except (OSError, ValueError, MemoryError) as exc:
            error = exc
        finally:
            self.close()
        if error is not None:
            if self.on_error is None:
                raise error
            self.on_error(str(error))
        else:
            self.on_capture(image)

    def _cancel(self, _event: tk.Event | None = None) -> None:
        self.close()
        self.on_capture(None)

    def _draw_selection(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        if self.canvas is None:
            return

        left, top, right, bottom = _normalize_rect(start_x, start_y, end_x, end_y)
        canvas_left = left - self.virtual_left
        canvas_top = top - self.virtual_top
        canvas_right = right - self.virtual_left
        canvas_bottom = bottom - self.virtual_top

        if self.current_rect is not None:
            self.canvas.delete(self.current_rect)
        if self.dim_label is not None:
            self.canvas.delete(self.dim_label)

        self.current_rect = self.canvas.create_rectangle(
            canvas_left,
            canvas_top,
            canvas_right,
            canvas_bottom,
            outline="#38bdf8",
            width=2,
        )
        width = max(0, right - left)
        height = max(0, bottom - top)
        label_x = canvas_left + 8
        label_y = max(16, canvas_top - 14)
        self.dim_label = self.canvas.create_text(
            label_x,
            label_y,
            anchor="w",
            text=f"{width} x {height} px",
            fill="white",
            font=("Segoe UI", 10),
        )

    def close(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        self.canvas = None
        self.current_rect = None
        self.dim_label = None
        self.preview = None
        if self.snapshot is not None:
            self.snapshot.close()
            self.snapshot = None


def _normalize_rect(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
