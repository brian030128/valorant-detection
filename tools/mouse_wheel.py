"""Collect vertical Windows wheel deltas without consuming local input."""

from collections import deque
import ctypes
from ctypes import wintypes
import sys
import threading


class WheelBuffer:
    """Convert Windows' 120 units per detent to signed HID wheel counts."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pending = deque()
        self.remainder = 0

    def add(self, delta):
        with self.lock:
            total = self.remainder + delta
            steps = (abs(total) // 120) * (1 if total >= 0 else -1)
            self.remainder = total - steps * 120
            if steps:
                if self.pending and self.pending[-1] * steps > 0:
                    self.pending[-1] += steps
                else:
                    self.pending.append(steps)
                if len(self.pending) > 64 or abs(self.pending[-1]) > 32767:
                    raise RuntimeError('Wheel input backlog exceeded; stopping')

    def take(self):
        with self.lock:
            return self.pending.popleft() if self.pending else 0


class WindowsWheel(WheelBuffer):
    """A dedicated WH_MOUSE_LL message loop; cursor polling has no wheel API."""

    def __init__(self):
        super().__init__()
        self.ready = threading.Event()
        self.closing = threading.Event()
        self.error = None
        self.thread = None
        self.thread_id = None
        self.api = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='mouse-wheel')
        self.thread.start()
        if not self.ready.wait(2):
            raise RuntimeError('Timed out starting wheel capture')
        if self.error:
            raise RuntimeError(f'Wheel capture failed: {self.error}') from self.error

    def _run(self):
        hook = None
        try:
            if sys.platform != 'win32':
                raise RuntimeError('Wheel capture requires Windows')
            api = ctypes.WinDLL('user32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                               wintypes.WPARAM, wintypes.LPARAM)

            class MouseEvent(ctypes.Structure):
                _fields_ = [('point', wintypes.POINT), ('mouseData', wintypes.DWORD),
                            ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                            ('extraInfo', ctypes.c_size_t)]

            api.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
            api.SetWindowsHookExW.restype = wintypes.HANDLE
            api.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            api.CallNextHookEx.restype = ctypes.c_ssize_t
            api.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            api.UnhookWindowsHookEx.restype = wintypes.BOOL
            api.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            api.GetMessageW.restype = ctypes.c_int
            api.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            api.PeekMessageW.restype = wintypes.BOOL
            api.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            api.PostThreadMessageW.restype = wintypes.BOOL
            kernel.GetCurrentThreadId.restype = wintypes.DWORD
            kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel.GetModuleHandleW.restype = wintypes.HMODULE
            self.api = api
            self.thread_id = kernel.GetCurrentThreadId()

            @callback_type
            def callback(code, message, pointer):
                if code >= 0 and message == 0x020A and not self.closing.is_set():
                    try:
                        event = ctypes.cast(pointer, ctypes.POINTER(MouseEvent)).contents
                        self.add(ctypes.c_short(event.mouseData >> 16).value)
                    except Exception as exc:
                        self.error = exc
                        api.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
                return api.CallNextHookEx(hook, code, message, pointer)

            message = wintypes.MSG()
            # Create this thread's queue before start() allows close() to post QUIT.
            api.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            if self.closing.is_set():
                return
            hook = api.SetWindowsHookExW(14, callback, kernel.GetModuleHandleW(None), 0)
            if not hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self.ready.set()
            while not self.closing.is_set():
                result = api.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                # This queue receives only hook notifications and QUIT; hook
                # callbacks are dispatched by GetMessage itself.
        except Exception as exc:
            self.error = exc
        finally:
            if hook:
                if not self.api.UnhookWindowsHookEx(hook):
                    self.error = ctypes.WinError(ctypes.get_last_error())
            self.ready.set()

    def take(self):
        if self.error:
            raise RuntimeError(f'Wheel capture failed: {self.error}') from self.error
        return super().take()

    def close(self):
        self.closing.set()
        if self.api and self.thread_id:
            self.api.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError('Wheel capture did not stop')
