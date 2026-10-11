from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class HotkeyRegistrationError(RuntimeError):
    pass


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class Hotkey:
    def __init__(
        self,
        on_hotkey: Callable[[], None],
        *,
        modifiers: int = MOD_CONTROL | MOD_SHIFT,
        virtual_key: int = ord("X"),
        hotkey_id: int = 0x5158,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.on_hotkey = on_hotkey
        self.modifiers = modifiers
        self.virtual_key = virtual_key
        self.hotkey_id = hotkey_id
        self.on_error = on_error
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.ready = threading.Event()
        self.stop_requested = threading.Event()
        self.running = False
        self.error: str | None = None
        self._user32 = None

    def start(self) -> None:
        if self.running:
            return
        if self.thread is not None and self.thread.is_alive():
            raise HotkeyRegistrationError("The previous hotkey listener is still stopping")
        self.ready.clear()
        self.stop_requested.clear()
        self.error = None
        self.thread = threading.Thread(target=self._message_loop, daemon=True, name="quickcrop-hotkey")
        self.thread.start()
        if not self.ready.wait(timeout=2):
            self.stop()
            raise HotkeyRegistrationError("Timed out starting the hotkey listener. Please restart QuickCrop OCR.")
        if not self.running:
            raise HotkeyRegistrationError(self.error or "The hotkey listener stopped during startup")

    def stop(self) -> None:
        self.running = False
        self.stop_requested.set()
        if self.thread is not None and self.thread.is_alive():
            if self.thread_id is not None and self._user32 is not None:
                self._user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            self.thread.join(timeout=1)

    def _message_loop(self) -> None:
        registered = False
        listening = False
        try:
            user32, kernel32 = _load_apis()
            self._user32 = user32
            self.thread_id = kernel32.GetCurrentThreadId()
            registered = bool(user32.RegisterHotKey(
                None, self.hotkey_id, self.modifiers | MOD_NOREPEAT, self.virtual_key
            ))
            if not registered:
                self.error = "Could not register the capture hotkey. Another app may already use it."
                return
            if self.stop_requested.is_set():
                return
            msg = MSG()
            # Create the thread message queue before reporting readiness, so a
            # concurrent stop can always post WM_QUIT without losing the wakeup.
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            self.running = listening = True
            self.ready.set()
            while not self.stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    if not self.stop_requested.is_set():
                        self.error = "Hotkey listener stopped unexpectedly. Please restart QuickCrop OCR."
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.on_hotkey()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = f"Hotkey listener failed: {exc}"
        finally:
            if registered:
                user32.UnregisterHotKey(None, self.hotkey_id)
            self.running = False
            self.thread_id = None
            self.ready.set()
            if listening and self.error and not self.stop_requested.is_set() and self.on_error is not None:
                self.on_error(self.error)


def _load_apis():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = [
        (user32.RegisterHotKey, [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (user32.UnregisterHotKey, [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        (user32.PostThreadMessageW, [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        (user32.GetMessageW, [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (user32.PeekMessageW, [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (user32.TranslateMessage, [ctypes.POINTER(MSG)], wintypes.BOOL),
        (user32.DispatchMessageW, [ctypes.POINTER(MSG)], ctypes.c_ssize_t),
        (kernel32.GetCurrentThreadId, [], wintypes.DWORD),
    ]
    for function, arguments, result in signatures:
        function.argtypes = arguments
        function.restype = result
    return user32, kernel32
