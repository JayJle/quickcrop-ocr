from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class ClipboardError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class ClipboardBackup:
    handles: list[tuple[int, int]] = field(default_factory=list)
    complete: bool = True


class ClipboardWriter:
    def __init__(self, api: WindowsClipboardApi | None = None) -> None:
        self.api = api or WindowsClipboardApi()

    def copy(self, text: str, hwnd: int) -> None:
        api = self.api
        new_handle = api.allocate_text(text)
        backup = ClipboardBackup()
        opened = False
        try:
            if not api.open(hwnd):
                raise ClipboardError("Clipboard is busy", retryable=True)
            opened = True
            # Backup is best-effort: unreadable formats must not block copying.
            # Allocate the new text first and keep the lock through recovery.
            backup = api.snapshot()
            if not api.clear():
                raise ClipboardError("Could not open clipboard for replacement", retryable=True)
            if api.set_data(CF_UNICODETEXT, new_handle):
                new_handle = 0  # Ownership was transferred to Windows.
                return

            failed: list[tuple[int, int]] = []
            for format_id, handle in backup.handles:
                if not api.set_data(format_id, handle):
                    failed.append((format_id, handle))
            backup.handles = failed
            if failed:
                # Retry restoration before releasing the lock, never later when
                # another application may have put new data on the clipboard.
                backup.handles = [(fmt, handle) for fmt, handle in failed if not api.set_data(fmt, handle)]
            if backup.handles or not backup.complete:
                raise ClipboardError("Copy failed; some previous clipboard formats could not be restored")
            raise ClipboardError("Copy failed; previous clipboard restored", retryable=True)
        finally:
            if opened:
                api.close()
            if new_handle:
                api.free(CF_UNICODETEXT, new_handle)
            for format_id, handle in backup.handles:
                api.free(format_id, handle)


class WindowsClipboardApi:
    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        signatures = [
            (self.user32.OpenClipboard, [wintypes.HWND], wintypes.BOOL),
            (self.user32.CloseClipboard, [], wintypes.BOOL),
            (self.user32.EmptyClipboard, [], wintypes.BOOL),
            (self.user32.EnumClipboardFormats, [wintypes.UINT], wintypes.UINT),
            (self.user32.GetClipboardData, [wintypes.UINT], wintypes.HANDLE),
            (self.user32.SetClipboardData, [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE),
            (self.kernel32.GlobalAlloc, [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL),
            (self.kernel32.GlobalLock, [wintypes.HGLOBAL], ctypes.c_void_p),
            (self.kernel32.GlobalUnlock, [wintypes.HGLOBAL], wintypes.BOOL),
            (self.kernel32.GlobalFree, [wintypes.HGLOBAL], wintypes.HGLOBAL),
            (self.ole32.OleDuplicateData, [wintypes.HANDLE, wintypes.WORD, wintypes.UINT], wintypes.HANDLE),
            (self.gdi32.CopyEnhMetaFileW, [wintypes.HANDLE, wintypes.LPCWSTR], wintypes.HANDLE),
            (self.gdi32.DeleteEnhMetaFile, [wintypes.HANDLE], wintypes.BOOL),
            (self.gdi32.DeleteMetaFile, [wintypes.HANDLE], wintypes.BOOL),
            (self.gdi32.DeleteObject, [wintypes.HANDLE], wintypes.BOOL),
        ]
        for function, arguments, result in signatures:
            function.argtypes = arguments
            function.restype = result

    def allocate_text(self, text: str) -> int:
        if "\0" in text:
            raise ClipboardError("The result contains a null character; clipboard was not changed")
        data = (text + "\0").encode("utf-16-le")
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ClipboardError("Could not allocate clipboard memory")
        pointer = self.kernel32.GlobalLock(handle)
        if not pointer:
            self.kernel32.GlobalFree(handle)
            raise ClipboardError("Could not lock clipboard memory")
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            self.kernel32.GlobalUnlock(handle)
        return handle

    def open(self, hwnd: int) -> bool:
        return bool(self.user32.OpenClipboard(hwnd))

    def close(self) -> None:
        self.user32.CloseClipboard()

    def clear(self) -> bool:
        return bool(self.user32.EmptyClipboard())

    def set_data(self, format_id: int, handle: int) -> bool:
        return bool(self.user32.SetClipboardData(format_id, handle))

    def snapshot(self) -> ClipboardBackup:
        backup = ClipboardBackup()
        format_id = 0
        try:
            while True:
                ctypes.set_last_error(0)
                format_id = self.user32.EnumClipboardFormats(format_id)
                if not format_id:
                    if ctypes.get_last_error():
                        backup.complete = False
                    return backup
                if format_id == 0x80 or 0x200 <= format_id <= 0x2FF:
                    backup.complete = False
                    continue
                source = self.user32.GetClipboardData(format_id)
                if not source:
                    backup.complete = False
                    continue
                base_format = {0x82: 2, 0x83: 3, 0x8E: 14}.get(format_id, format_id)
                if base_format == 14:
                    handle = self.gdi32.CopyEnhMetaFileW(source, None)
                else:
                    handle = self.ole32.OleDuplicateData(source, base_format, GMEM_MOVEABLE)
                if not handle:
                    backup.complete = False
                    continue
                backup.handles.append((format_id, handle))
        except Exception:
            for fmt, handle in backup.handles:
                self.free(fmt, handle)
            raise

    def free(self, format_id: int, handle: int) -> None:
        if format_id in (2, 9, 0x82):
            self.gdi32.DeleteObject(handle)
        elif format_id in (14, 0x8E):
            self.gdi32.DeleteEnhMetaFile(handle)
        else:
            if format_id in (3, 0x83):
                pointer = self.kernel32.GlobalLock(handle)
                if pointer:
                    try:
                        metafile = ctypes.cast(pointer, ctypes.POINTER(_MetafilePicture)).contents
                        self.gdi32.DeleteMetaFile(metafile.handle)
                    finally:
                        self.kernel32.GlobalUnlock(handle)
            self.kernel32.GlobalFree(handle)


class _MetafilePicture(ctypes.Structure):
    _fields_ = [
        ("mapping_mode", wintypes.LONG), ("x_extent", wintypes.LONG),
        ("y_extent", wintypes.LONG), ("handle", wintypes.HANDLE),
    ]
