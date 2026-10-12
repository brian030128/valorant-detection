"""Center-200 head selection, smooth paths and timed movement-only playback."""

from contextlib import nullcontext
import importlib.util
import math
import random
from pathlib import Path
import sys
import threading
import time

import numpy as np

if __package__:
    from .relay_mouse import open_relay, precise_timer, send_stream, WindowsCursor
else:
    from relay_mouse import open_relay, precise_timer, send_stream, WindowsCursor

ROOT = Path(__file__).resolve().parents[1]


def select_head(predictions, center=(200.0, 200.0)):
    """Head center must be inside the half-open 200px square; nearest wins."""
    candidates = []
    for item in predictions:
        if item['class'] != 'enemy_head':
            continue
        x0, y0, x1, y1 = item['crop_xyxy']
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
            continue
        point = ((x0 + x1) / 2, (y0 + y1) / 2)
        offset = np.asarray(point) - center
        if np.all(offset >= -100) and np.all(offset < 100):
            candidates.append((float(offset @ offset), -item['confidence'], point))
    return min(candidates)[2] if candidates else None


class SmoothTrajectory:
    """Model-free eased movement with a small randomized sideways curve."""

    def __init__(self, min_ms=50, max_ms=100, hz=250, rng=None):
        if not 50 <= min_ms <= max_ms <= 100 or not 1 <= hz <= 1000:
            raise ValueError('Duration bounds must be 50..100 ms and rate 1..1000 Hz')
        self.hz = hz
        self.rng = rng or random.Random()
        durations = sorted(set([min_ms, max_ms] + list(range(math.ceil(min_ms), math.floor(max_ms) + 1))))
        self.templates = []
        for duration in durations:
            times = np.append(np.arange(0., duration, 1000. / hz), duration)
            t = times / duration
            progress = t**3 * (10 - 15*t + 6*t*t)
            bend = 16 * progress**2 * (1 - progress)**2
            self.templates.append((times, progress, bend))

    def plan(self, target, center=(200., 200.)):
        times, progress, bend = self.rng.choice(self.templates)
        delta = np.asarray(target, dtype=float) - center
        distance = float(np.linalg.norm(delta))
        normal = np.array([-delta[1], delta[0]]) / distance if distance else np.zeros(2)
        amplitude = self.rng.uniform(-1, 1) * min(3., .05 * distance)
        xy = center + progress[:, None] * delta + (amplitude * bend)[:, None] * normal
        xy[0], xy[-1] = center, target
        return np.column_stack([times, xy])


class TrajectoryBank:
    """Sample learned shapes once; endpoint-correct, rotate, scale and retime online."""

    def __init__(self, rows, min_ms=50, max_ms=100, hz=250, rng=None):
        if not 50 <= min_ms <= max_ms <= 100 or not 1 <= hz <= 1000:
            raise ValueError('Duration bounds must be 50..100 ms and rate 1..1000 Hz')
        self.min_ms, self.max_ms, self.hz = min_ms, max_ms, hz
        self.rng = rng or random.Random()
        self.shapes = []
        for row in rows:
            row = np.asarray(row, dtype=float)
            if row.ndim != 2 or row.shape[1] < 3 or len(row) < 2 or not np.isfinite(row).all():
                continue
            times = row[:, 0] - row[0, 0]
            if times[-1] <= 0 or np.any(np.diff(times) <= 0):
                continue
            phase = times / times[-1]
            xy = row[:, 1:3] - row[0, 1:3]
            # All source requests are (0,0)->(50,0). Correct residual error
            # smoothly; the learned model does not guarantee an exact endpoint.
            blend = phase * phase * (3 - 2 * phase)
            xy += blend[:, None] * (np.array([50., 0.]) - xy[-1])
            shape = xy / 50.
            # Desktop recordings can include large exploratory detours. Only
            # keep compact paths suited to a short target correction.
            if (np.linalg.norm(np.diff(shape, axis=0), axis=1).sum() > 1.6
                    or np.max(np.abs(shape[:, 1])) > .3
                    or shape[:, 0].min() < -.1 or shape[:, 0].max() > 1.1):
                continue
            self.shapes.append((phase, shape))
        if not self.shapes:
            raise RuntimeError('The generator produced no valid trajectories')
        self.index = 0
        # Fit a smooth lateral curve to each learned shape. Longitudinal
        # progress stays monotonic, eliminating inherited pauses/reversals.
        controls = []
        for _, shape in self.shapes:
            progress = np.clip(shape[:, 0], 0, 1)
            basis = np.column_stack([3 * (1 - progress)**2 * progress,
                                     3 * (1 - progress) * progress**2])
            control = np.linalg.lstsq(basis, shape[:, 1], rcond=None)[0]
            controls.append(np.clip(control, -.2, .2))
        # Cache every millisecond-duration variant to keep runtime planning cheap.
        durations = sorted(set([min_ms, max_ms] + list(range(math.ceil(min_ms), math.floor(max_ms) + 1))))
        self.templates = []
        for duration in durations:
            times = np.append(np.arange(0., duration, 1000. / hz), duration)
            t = times / duration
            progress = t**3 * (10 - 15*t + 6*t*t)
            basis = np.column_stack([3 * (1-progress)**2 * progress,
                                     3 * (1-progress) * progress**2])
            units = [np.column_stack([progress, basis @ control]) for control in controls]
            self.templates.append((times, units))

    @classmethod
    def load(cls, checkpoint=None, **kwargs):
        package = ROOT / 'mouse-generator/generator'
        spec = importlib.util.spec_from_file_location(
            '_aim_generator', package / '__init__.py', submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from _aim_generator.sample import load_model, generate_batch, default_checkpoint
        model = load_model(checkpoint or default_checkpoint(), device='cpu')
        rows = generate_batch(model, [(0, 0)] * 16, [(50, 0)] * 16,
                              max_steps=128, seed=42)
        return cls(rows, **kwargs)

    def plan(self, target, center=(200., 200.)):
        times, units = self.rng.choice(self.templates)
        unit = units[self.index % len(units)]
        self.index += 1
        dx, dy = np.asarray(target) - center
        xy = unit @ np.array([[dx, dy], [-dy, dx]]) + center
        xy[0], xy[-1] = center, target
        return np.column_stack([times, xy])


def play_path(rows, emit, stop, *, scale=1., valid=lambda: True,
              clock=time.monotonic, wait=None):
    """Absolute deadlines and cumulative rounding; late samples are coalesced."""
    wait = wait or stop.wait
    started = clock()
    sent = np.zeros(2, dtype=int)
    index = 1
    while index < len(rows):
        deadline = started + rows[index, 0] / 1000
        if wait(max(0, deadline - clock())) or stop.is_set() or not valid():
            return False
        now = clock()
        while index + 1 < len(rows) and started + rows[index + 1, 0] / 1000 <= now:
            index += 1
        desired = np.rint((rows[index, 1:3] - rows[0, 1:3]) * scale).astype(int)
        delta = desired - sent
        if np.max(np.abs(delta)) > 32767:
            raise RuntimeError('Trajectory exceeds streaming HID range')
        if np.any(delta):
            emit(int(delta[0]), int(delta[1]), 0)
        sent = desired
        index += 1
    return True


class HeadAimSession:
    """Single UART owner; observations replace one another, never queue moves."""

    def __init__(self, bank, stop, *, port=None, scale=1., deadzone=2., settle_ms=20):
        if not math.isfinite(settle_ms) or not 0 <= settle_ms <= 1000:
            raise ValueError('Feedback settling time must be in 0..1000 ms')
        self.bank, self.stop, self.port = bank, stop, port
        self.scale, self.deadzone = scale, deadzone
        self.lock = threading.Lock()
        self.observation = (None, 0., (200., 200.))
        self.rows = None
        self.state = 'starting'
        self.error = None
        self.completed_at = 0.
        self.last_duration_ms = None
        self.replacing = False
        self.active_rows = None
        self.active_started = 0.
        self.active_sent = np.zeros(2, dtype=int)
        self.settle_ms = settle_ms
        self.feedback_after = 0.
        self.awaiting_delivery = False
        self.last_source_age_ms = None
        self.last_feedback_wait_ms = None

    def delivery_complete(self, now=None):
        """Called by the UART owner after the final report is acknowledged."""
        with self.lock:
            if not self.awaiting_delivery:
                return
            now = time.monotonic() if now is None else now
            self.awaiting_delivery = False
            self.completed_at = now
            self.feedback_after = now + self.settle_ms / 1000
            self.last_duration_ms = (now - self.active_started) * 1000
            self.replacing = False
            self.state = 'waiting for feedback'

    def timing_status(self):
        with self.lock:
            return {'settle_ms': self.settle_ms,
                    'completed_monotonic': self.completed_at,
                    'required_frame_monotonic': self.feedback_after,
                    'last_source_age_ms': self.last_source_age_ms,
                    'last_feedback_wait_ms': self.last_feedback_wait_ms,
                    'awaiting_delivery': self.awaiting_delivery}

    def tick(self, now=None):
        """Called only by the UART owner: None means manual; a pair overrides motion."""
        with self.lock:
            return self._tick(now)

    def _tick(self, now=None):
        now = time.monotonic() if now is None else now
        target, stamp, center = self.observation
        eligible = target is not None and now - stamp <= .15
        if self.stop.is_set():
            if self.active_rows is not None:
                self.completed_at = now
            self.active_rows = None
            self.replacing = False
            self.state = 'manual'
            return None
        if self.active_rows is None:
            if self.awaiting_delivery:
                self.state = 'waiting for final acknowledgement'
                return (0, 0)
            if self.completed_at and (now < self.feedback_after or stamp <= self.feedback_after):
                self.replacing = False
                self.state = 'waiting for feedback'
                return None
            if (not eligible or stamp <= self.completed_at
                    or math.dist(target, center) <= self.deadzone):
                self.replacing = False
                self.state = 'manual'
                return None
            self.active_rows = self.bank.plan(target, center)
            self.rows = self.active_rows
            self.active_started = now
            self.last_source_age_ms = (now - stamp) * 1000
            self.last_feedback_wait_ms = (now - self.completed_at) * 1000 if self.completed_at else None
            self.active_sent = np.zeros(2, dtype=int)
        self.replacing = True
        self.state = 'trajectory + live buttons'
        rows = self.active_rows
        elapsed_ms = (now - self.active_started) * 1000
        index = min(len(rows) - 1, np.searchsorted(rows[:, 0], elapsed_ms, side='right') - 1)
        desired = np.rint((rows[index, 1:3] - rows[0, 1:3]) * self.scale).astype(int)
        delta = desired - self.active_sent
        if np.max(np.abs(delta)) > 32767:
            raise RuntimeError('Trajectory exceeds streaming HID range')
        self.active_sent = desired
        if elapsed_ms >= rows[-1, 0]:
            self.active_rows = None
            self.completed_at = now
            self.last_duration_ms = elapsed_ms
            self.awaiting_delivery = True
        return int(delta[0]), int(delta[1])

    def observe(self, target, captured_at, center=(200., 200.)):
        with self.lock:
            if captured_at <= self.observation[1]:
                return
            self.observation = (target, captured_at, center)

    def snapshot(self):
        with self.lock:
            return self.observation

    def __enter__(self):
        self.thread = threading.Thread(target=self.run, name='head-trajectory')
        self.thread.start()
        return self

    def run(self):
        try:
            self.state = 'waiting for USB' if self.port else 'preview'
            connection = open_relay(self.port, wait_for_usb=True, stop=self.stop) if self.port else nullcontext(None)
            with precise_timer(), connection as relay:
                if relay is not None and not relay.streaming:
                    raise RuntimeError('Head trajectories require streaming v3 firmware')
                last_contact = time.monotonic()
                keyboard = WindowsCursor() if sys.platform == 'win32' else None
                while not self.stop.wait(.002):
                    if keyboard is not None and keyboard.quit_pressed():
                        self.stop.set()
                        break
                    now = time.monotonic()
                    delta = self.tick(now)
                    if relay is not None and delta is not None and any(delta):
                        send_stream(relay, *delta, 0)
                        last_contact = time.monotonic()
                    elif relay is not None and now - last_contact >= .05:
                        relay.request('PING', 'OK PING', timeout=.2)
                        last_contact = time.monotonic()
                    self.delivery_complete()
        except InterruptedError as exc:
            if not self.stop.is_set():
                self.error = exc
                self.stop.set()
        except Exception as exc:
            self.error = exc
            self.stop.set()

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        self.thread.join()
        if exc_type is None and self.error:
            raise RuntimeError(f'Head trajectory failed: {self.error}') from self.error
