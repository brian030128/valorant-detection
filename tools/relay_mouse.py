"""Windows cursor-to-UART movement/click relay. Q, Escape or Ctrl+C stops capture."""

import argparse
import ctypes
from collections import deque
from contextlib import contextmanager
from ctypes import wintypes
import importlib.util
import math
import queue
from pathlib import Path
import sys
import threading
import time


def load_protocol():
    path = Path(__file__).resolve().parents[1] / "mouse-spoofing" / "replay.py"
    if not path.is_file():
        raise RuntimeError("Run git submodule update --init --recursive first")
    spec = importlib.util.spec_from_file_location("mouse_spoofing_replay", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_firmware(reply, *, require_usb=True):
    """Return a conservative axis limit for verified UART protocol profiles.

    v2 also covers the installed M2K variant. Its identity does not determine
    motion limits; use the 127-count range accepted by both v2 variants.
    """
    profiles = {
        "OK HELLO 1 4096 1000 60000000 1500": 32767,
        "OK HELLO 2 4096 10000 60000000 1500": 127,
        "OK HELLO 3 4096 10000 60000000 1500": 32767,
    }
    prefix, _, usb = reply.rpartition(" ")
    if prefix not in profiles or usb not in ("USB=0", "USB=1"):
        raise RuntimeError(f"Unsupported firmware handshake: {reply}")
    if require_usb and usb == "USB=0":
        raise RuntimeError("Firmware supported, but native USB HID is not ready (USB=0); "
                           "connect the board's native USB port to the receiving PC")
    return profiles[prefix]


class PendingMotion:
    """Coalesce movement while UART is busy; keep fractional scaling remainder."""

    def __init__(self, scale):
        self.scale = scale
        self.x = self.y = 0.0
        self.lock = threading.Lock()

    def add(self, dx, dy):
        with self.lock:
            self.x += dx * self.scale
            self.y += dy * self.scale
            if max(abs(self.x), abs(self.y)) > 32767:
                raise RuntimeError("Movement backlog exceeds HID range; stopping")

    def take(self, max_axis=32767):
        with self.lock:
            dx, dy = round(self.x), round(self.y)
            largest = max(abs(dx), abs(dy))
            if largest > max_axis:
                ratio = max_axis / largest
                dx, dy = round(dx * ratio), round(dy * ratio)
            self.x -= dx
            self.y -= dy
            return dx, dy


def send_motion(relay, dx, dy, buttons=0):
    # Firmware requires a released final report, so clicks are bounded pulses.
    if buttons not in (0, 1, 2, 3):
        raise ValueError("Only left/right click masks are supported")
    count = 2 if buttons else 1
    commands = [f"LOAD {count}", f"E 0 0 {dx} {dy} {buttons} 0"]
    expected = ["OK LOAD", "OK E 0"]
    if buttons:
        hold_us = max(30000, round(getattr(relay, "min_gap_s", 0.01) * 1_000_000))
        commands.append(f"E 1 {hold_us} 0 0 0 0")
        expected.append("OK E 1")
    commands.append("RUN")
    expected.append("OK RUN")
    # Firmware consumes ordered lines. Send once instead of waiting for a
    # USB/UART round trip per command; still validate every acknowledgement.
    protocol = sys.modules[type(relay).__module__]
    relay.port.write(b"".join(protocol.frame(command) for command in commands))
    deadline = time.monotonic() + 0.5
    for acknowledgement in expected:
        reply = relay.read_line(deadline)
        if reply != acknowledgement:
            raise RuntimeError(f"expected {acknowledgement!r}, received {reply!r}")
    reply = relay.read_line(time.monotonic() + 0.5)
    parts = reply.split()
    if len(parts) != 3 or parts[:2] != ["DONE", str(count)] or not parts[2].isdigit():
        raise RuntimeError(f"Unexpected completion: {reply}")


class WindowsCursor:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Cursor capture requires Windows")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.SetProcessDPIAware()
        self.api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.api.GetCursorPos.restype = wintypes.BOOL
        self.api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.api.SetCursorPos.restype = wintypes.BOOL
        self.api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.api.GetAsyncKeyState.restype = ctypes.c_short
        self.center = (self.api.GetSystemMetrics(0) // 2,
                       self.api.GetSystemMetrics(1) // 2)

    def position(self):
        point = wintypes.POINT()
        if not self.api.GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return point.x, point.y

    def move(self, position):
        if not self.api.SetCursorPos(*position):
            raise ctypes.WinError(ctypes.get_last_error())

    def quit_pressed(self):
        return any(self.api.GetAsyncKeyState(key) & 0x8000 for key in (0x1B, 0x51))

    def buttons(self):
        return (int(bool(self.api.GetAsyncKeyState(0x01) & 0x8000)) |
                (int(bool(self.api.GetAsyncKeyState(0x02) & 0x8000)) << 1))


class ClickQueue:
    """Preserve observed down edges while serial transmission is busy."""

    def __init__(self):
        self.previous = 0
        self.pending = queue.Queue(maxsize=64)

    def sample(self, buttons):
        pressed = buttons & ~self.previous
        self.previous = buttons
        if pressed:
            try:
                self.pending.put_nowait(pressed)
            except queue.Full:
                raise RuntimeError("Click backlog exceeded; stopping") from None

    def take(self):
        try:
            return self.pending.get_nowait()
        except queue.Empty:
            return 0


class StreamInput:
    """Coalesce movement within each button state without losing drag edges."""

    def __init__(self, scale):
        self.scale = scale
        self.remainder_x = self.remainder_y = 0.0
        self.previous = 0
        self.pending = deque()
        self.lock = threading.Lock()

    def sample(self, dx, dy, buttons):
        with self.lock:
            x = dx * self.scale + self.remainder_x
            y = dy * self.scale + self.remainder_y
            ix, iy = round(x), round(y)
            self.remainder_x, self.remainder_y = x - ix, y - iy
            changed = buttons != self.previous
            self.previous = buttons
            if not (ix or iy or changed):
                return
            if self.pending and self.pending[-1][2] == buttons:
                self.pending[-1][0] += ix
                self.pending[-1][1] += iy
            else:
                self.pending.append([ix, iy, buttons])
            if len(self.pending) > 64 or max(abs(self.pending[-1][0]), abs(self.pending[-1][1])) > 32767:
                raise RuntimeError("Streaming input backlog exceeded; stopping")

    def discard_motion(self):
        """Drop overridden movement, retaining every queued button transition."""
        with self.lock:
            for event in self.pending:
                event[0] = event[1] = 0
            self.remainder_x = self.remainder_y = 0.

    def take(self, max_axis=32767):
        with self.lock:
            if not self.pending:
                return None
            dx, dy, buttons = self.pending[0]
            largest = max(abs(dx), abs(dy))
            if largest > max_axis:
                factor = max_axis / largest
                dx, dy = round(dx * factor), round(dy * factor)
                self.pending[0][0] -= dx
                self.pending[0][1] -= dy
            else:
                self.pending.popleft()
            return dx, dy, buttons


class MotionRouter:
    """Select manual or generated displacement while preserving button edges."""

    def __init__(self, inputs, aim=None):
        self.inputs, self.aim = inputs, aim
        self.held_buttons = 0
        self.was_replacing = False

    def take(self):
        override = self.aim.tick() if self.aim is not None else None
        if override is not None or self.was_replacing:
            self.inputs.discard_motion()
        self.was_replacing = override is not None
        event = self.inputs.take()
        if event is not None:
            self.held_buttons = event[2]
        if override is not None:
            # A queued release must be sent even if the AI is stationary.
            event = (*override, self.held_buttons) if event is not None or any(override) else None
        return event


def send_stream(relay, dx, dy, buttons):
    sequence = relay.sequence
    relay.request(f"M {sequence} {dx} {dy} {buttons} 0", f"OK M {sequence}", timeout=0.2)
    relay.sequence = (sequence + 1) & 0xffffffff


@contextmanager
def precise_timer():
    """Keep Windows' coarse timer from stretching 4 ms samples to ~16 ms."""
    timer = ctypes.WinDLL("winmm") if sys.platform == "win32" else None
    enabled = timer is not None and timer.timeBeginPeriod(1) == 0
    try:
        yield
    finally:
        if enabled:
            timer.timeEndPeriod(1)


@precise_timer()
def capture(relay, *, scale, hz, dry_run, stop=None, aim=None):
    if aim is not None and not (dry_run or getattr(relay, 'streaming', False)):
        raise RuntimeError('Head trajectories require streaming v3 firmware')
    cursor = WindowsCursor()
    original = cursor.position()
    pending = PendingMotion(scale)
    clicks = ClickQueue()
    streaming = dry_run or getattr(relay, "streaming", False)
    stream_input = StreamInput(scale)
    router = MotionRouter(stream_input, aim)
    stop = stop if stop is not None else threading.Event()
    errors = []

    def transmit():
        try:
            last_contact = time.monotonic()
            while not stop.wait(0.001):
                if streaming:
                    event = router.take()
                    if event is not None:
                        if dry_run:
                            print(f"dx={event[0]} dy={event[1]} buttons={event[2]}", flush=True)
                        else:
                            send_stream(relay, *event)
                        last_contact = time.monotonic()
                    elif not dry_run and time.monotonic() - last_contact >= 0.05:
                        relay.request("PING", "OK PING", timeout=0.2)
                        last_contact = time.monotonic()
                    if aim is not None:
                        aim.delivery_complete()
                    continue
                dx, dy = pending.take(getattr(relay, "max_axis", 32767))
                buttons = clicks.take()
                if dx or dy or buttons:
                    if dry_run:
                        print(f"dx={dx} dy={dy} click_buttons={buttons}", flush=True)
                    else:
                        sent_at = time.monotonic()
                        send_motion(relay, dx, dy, buttons)
                        # Respect the v2 minimum cadence even if RUN completes early.
                        stop.wait(max(0, getattr(relay, "min_gap_s", 0.001)
                                      - (time.monotonic() - sent_at)))
        except Exception as exc:
            errors.append(exc)
            stop.set()

    worker = threading.Thread(target=transmit, name="mouse-uart")
    worker.start()
    try:
        cursor.move(cursor.center)
        mode = "Live left/right button states: holding and dragging enabled." if streaming else (
            "Legacy firmware: 30 ms clicks only; holding/dragging unavailable.")
        print(f"Relaying movement; Q, Escape or Ctrl+C exits. {mode}")
        while not stop.is_set() and not cursor.quit_pressed():
            buttons = cursor.buttons()
            x, y = cursor.position()
            dx, dy = x - cursor.center[0], y - cursor.center[1]
            if dx or dy:
                cursor.move(cursor.center)
            if streaming:
                if aim is not None and aim.replacing:
                    dx = dy = 0
                stream_input.sample(dx, dy, buttons)
            else:
                clicks.sample(buttons)
                if dx or dy:
                    pending.add(dx, dy)
            stop.wait(1 / hz)
    finally:
        stop.set()
        # Restore immediately even when serial acknowledgement is still pending.
        try:
            cursor.move(original)
        finally:
            worker.join()
    if errors:
        raise errors[0]


@contextmanager
def open_relay(port_name, *, probe_only=False, wait_for_usb=False, stop=None):
    """Own the serial connection and always STOP before closing it."""
    protocol = load_protocol()
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.02, write_timeout=0.5)
    port.dtr = port.rts = False
    port.port = port_name
    with port:
        try:
            relay = protocol.Relay(port)
            reply = relay.probe()
            print(reply, flush=True)
            check_firmware(reply, require_usb=False)
            if wait_for_usb and not probe_only:
                while reply.endswith(" USB=0"):
                    if stop.wait(0.2):
                        raise InterruptedError("Mouse connection wait cancelled")
                    port.write(protocol.frame("HELLO"))
                    reply = relay.read_line(time.monotonic() + 0.5)
                    check_firmware(reply, require_usb=False)
            relay.max_axis = check_firmware(reply, require_usb=not probe_only)
            relay.min_gap_s = int(reply.split()[4]) / 1_000_000
            relay.streaming = reply.split()[2] == "3"
            print(relay.identity(), flush=True)
            print(f"Supported protocol v{reply.split()[2]}; "
                  f"using up to {relay.max_axis} counts per report.", flush=True)
            if relay.streaming:
                relay.request("CAPS", "OK CAPS STREAM=1 MAX_AXIS=32767 WATCHDOG_MS=250")
                if not probe_only:
                    relay.request("STREAM", "OK STREAM")
                    relay.sequence = 0
            yield relay
        finally:
            try:
                port.write(b"\nSTOP\n")
            except OSError:
                pass


class MouseSession:
    """Run cursor capture independently of video inference, with shared shutdown."""

    def __init__(self, port, stop, *, scale=1.0, hz=250, dry_run=False, aim=None):
        self.port, self.stop = port, stop
        self.scale, self.hz, self.dry_run = scale, hz, dry_run
        self.error = None
        self.thread = None
        self.streaming = dry_run
        self.state = "starting"
        self.aim = aim

    def __enter__(self):
        def run():
            try:
                if self.dry_run:
                    self.state = "dry-run drag"
                    capture(None, scale=self.scale, hz=self.hz,
                            dry_run=True, stop=self.stop, aim=self.aim)
                else:
                    self.state = "waiting for receiving USB"
                    with open_relay(self.port, wait_for_usb=True, stop=self.stop) as relay:
                        if self.stop.is_set():
                            return
                        self.streaming = getattr(relay, "streaming", False)
                        self.state = "drag" if self.streaming else "legacy clicks"
                        capture(relay, scale=self.scale, hz=self.hz,
                                dry_run=False, stop=self.stop, aim=self.aim)
            except InterruptedError as exc:
                if not self.stop.is_set():
                    self.error = exc
            except Exception as exc:
                self.error = exc
            finally:
                self.stop.set()

        self.thread = threading.Thread(target=run, name="mouse-capture")
        self.thread.start()
        return self

    def check(self):
        if self.error is not None:
            raise RuntimeError(f"Mouse relay failed: {self.error}") from self.error

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        self.thread.join()
        if exc_type is None:
            self.check()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="UART bridge, e.g. COM6")
    parser.add_argument("--dry-run", action="store_true", help="capture/recenter and print deltas without hardware")
    parser.add_argument("--probe", action="store_true", help="query firmware without capturing or sending movement")
    parser.add_argument("--counts-per-pixel", type=float, default=1.0)
    parser.add_argument("--hz", type=int, default=250, help="cursor sampling rate (default 250)")
    args = parser.parse_args()
    if not math.isfinite(args.counts_per_pixel) or not 0 < args.counts_per_pixel <= 100:
        parser.error("--counts-per-pixel must be finite and in (0, 100]")
    if not 1 <= args.hz <= 1000:
        parser.error("--hz must be in 1..1000")
    if args.dry_run and args.probe:
        parser.error("--dry-run and --probe cannot be combined")
    if not args.dry_run and not args.port:
        parser.error("provide --port or --dry-run")
    try:
        if args.dry_run:
            capture(None, scale=args.counts_per_pixel, hz=args.hz, dry_run=True)
            return
        with open_relay(args.port, probe_only=args.probe) as relay:
            if not args.probe:
                capture(relay, scale=args.counts_per_pixel, hz=args.hz, dry_run=False)
    except KeyboardInterrupt:
        print("Relay stopped.")
    except (ImportError, OSError, RuntimeError, TimeoutError) as exc:
        parser.exit(2, f"Relay failed: {exc}\n")


if __name__ == "__main__":
    main()
