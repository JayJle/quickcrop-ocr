from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
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
    ) -> None:
        self.on_hotkey = on_hotkey
        self.modifiers = modifiers
        self.virtual_key = virtual_key
        self.hotkey_id = hotkey_id
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.ready = threading.Event()
        self.running = False

    def start(self) -> None:
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._message_loop, daemon=True, name="quickcrop-hotkey")
        self.thread.start()
        self.ready.wait(timeout=2)
        if not self.running:
            raise HotkeyRegistrationError("Could not register Ctrl+Shift+X. Another app may already use it.")

    def stop(self) -> None:
        self.running = False
        if self.thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=1)

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, self.hotkey_id, self.modifiers, self.virtual_key):
            self.running = False
            self.ready.set()
            return

        self.ready.set()
        msg = MSG()
        try:
            while self.running:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.on_hotkey()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)
