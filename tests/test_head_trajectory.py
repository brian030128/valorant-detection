import random
import threading

import numpy as np
import pytest

from tools.head_trajectory import SmoothTrajectory, TrajectoryBank, HeadAimSession, select_head, play_path


def head(x, y, name='enemy_head', confidence=.9):
    return {'class': name, 'confidence': confidence,
            'crop_xyxy': [x - 2, y - 2, x + 2, y + 2]}


def bank(**kwargs):
    return TrajectoryBank([[[0, 0, 0, 0], [10, 20, 5, 0], [30, 48, 1, 1]]], **kwargs)


def test_gate_and_nearest_head():
    assert select_head([head(200, 200, 'enemy_body'), head(99.9, 200), head(300, 200)]) is None
    assert select_head([head(100, 200)]) == (100, 200)
    assert select_head([head(299.9, 200)]) == (299.9, 200)
    assert select_head([head(220, 210), head(202, 205)]) == (202, 205)
    assert select_head([head(200, 99.9), head(200, 300)]) is None


def test_half_pixel_capture_center():
    assert select_head([head(100, 200)], center=(200.5, 200.5)) is None
    assert select_head([head(100.5, 200.5)], center=(200.5, 200.5)) == (100.5, 200.5)


def test_random_duration_and_exact_endpoints():
    generator = bank(rng=random.Random(2))
    durations = []
    for target in [(225, 260), (160, 180), (200, 240), (200, 200)] * 10:
        rows = generator.plan(target)
        np.testing.assert_array_equal(rows[0], [0, 200, 200])
        np.testing.assert_array_equal(rows[-1, 1:], target)
        assert 50 <= rows[-1, 0] <= 100
        assert np.all(np.diff(rows[:, 0]) > 0)
        durations.append(rows[-1, 0])
    assert len(set(durations)) > 10


def test_invalid_inputs():
    with pytest.raises(ValueError):
        bank(min_ms=201)
    with pytest.raises(RuntimeError):
        TrajectoryBank([[[0, 0, 0], [0, 50, 0]]])


@pytest.mark.parametrize('hz', [125, 250, 500, 1000])
def test_path_matches_manual_sampling_rate(hz):
    rows = bank(hz=hz).plan((250, 160))
    duration = rows[-1, 0]
    expected = np.append(np.arange(0., duration, 1000. / hz), duration)
    np.testing.assert_allclose(rows[:, 0], expected)
    np.testing.assert_array_equal(rows[-1, 1:], [250, 160])
    assert len(rows) == len(expected)


def test_fifty_ms_path_has_thirteen_movement_intervals():
    rows = bank(min_ms=50, max_ms=50).plan((250, 160))
    assert len(rows) == 14
    np.testing.assert_allclose(np.diff(rows[:, 0]), [4.] * 12 + [2.])


def test_cached_shapes_are_not_modified_by_planning():
    generator = bank()
    originals = [[unit.copy() for unit in units] for _, units in generator.templates]
    for target in [(240, 170), (150, 280), (210, 190)]:
        rows = generator.plan(target)
        np.testing.assert_array_equal(rows[-1, 1:], target)
    for (_, units), original_units in zip(generator.templates, originals):
        for unit, original in zip(units, original_units):
            np.testing.assert_array_equal(unit, original)


@pytest.mark.parametrize('duration', [50, 75, 100])
def test_paused_source_becomes_continuous_eased_motion(duration):
    generator = TrajectoryBank([[[0, 0, 0], [10, 50, 0], [50, 50, 0]]],
                               min_ms=duration, max_ms=duration)
    rows = generator.plan((300, 200))
    steps = np.diff(rows[:, 1])
    speeds = steps / np.diff(rows[:, 0])
    assert np.all(steps > 0)
    assert speeds[0] < speeds[len(speeds)//2]
    assert speeds[-1] < speeds[len(speeds)//2]
    assert rows[-2, 1] < 300
    assert rows[-1, 1] == 300


def test_smoothed_path_preserves_learned_curvature_without_longitudinal_reversal():
    rows = bank(min_ms=100, max_ms=100).plan((300, 200))
    assert np.all(np.diff(rows[:, 1]) > 0)
    assert np.max(np.abs(rows[:, 2] - 200)) > 1
    assert np.max(np.abs(rows[:, 2] - 200)) <= 15


def test_large_detours_are_rejected():
    with pytest.raises(RuntimeError):
        TrajectoryBank([[[0, 0, 0], [10, 20, 900], [30, 50, 0]]])


class FakeClock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds
        return False


def test_playback_timing_endpoint_and_no_clicks():
    timer = FakeClock()
    rows = bank(rng=random.Random(5)).plan((223.5, 171.5))
    events = []
    assert play_path(rows, lambda *event: events.append(event), threading.Event(),
                     scale=1.3, clock=timer, wait=timer.wait)
    np.testing.assert_array_equal(np.sum(events, axis=0), [31, -37, 0])
    assert timer.now == pytest.approx(rows[-1, 0] / 1000)


def test_slow_uart_coalesces_without_losing_displacement():
    timer = FakeClock()
    rows = bank().plan((230, 180))
    events = []

    def emit(*event):
        events.append(event)
        timer.now += .025

    assert play_path(rows, emit, threading.Event(), clock=timer, wait=timer.wait)
    np.testing.assert_array_equal(np.sum(events, axis=0), [30, -20, 0])
    assert len(events) < len(rows) - 1


def test_cancellation_sends_nothing():
    timer = FakeClock()
    events = []
    assert not play_path(bank().plan((230, 180)), lambda *event: events.append(event),
                         threading.Event(), valid=lambda: False, clock=timer, wait=timer.wait)
    assert not events


def test_override_controller_completion_and_fresh_frame_requirement():
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event(), settle_ms=100)
    assert session.tick(1.) is None
    session.observe((230, 180), 1.)
    assert session.tick(1.) == (0, 0)
    assert session.replacing
    moves = [session.tick(1.025), session.tick(1.051)]
    assert tuple(np.sum(moves, axis=0)) == (30, -20)
    session.delivery_complete(1.055)
    assert session.tick(1.056) is None
    assert not session.replacing
    session.observe((230, 180), 1.09)
    assert session.tick(1.09) is None
    session.observe((230, 180), 1.16)
    assert session.tick(1.16) == (0, 0)


@pytest.mark.parametrize('target', [None, (160, 180), (200, 200)])
def test_active_movement_finishes_despite_detection_changes(target):
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event())
    session.observe((230, 180), 1.)
    session.observe((230, 180), 1.030)
    assert session.tick(1.03) == (0, 0)
    session.observe(target, 1.04)
    deltas = [session.tick(1.05), session.tick(1.081)]
    assert tuple(np.sum(deltas, axis=0)) == (30, -20)
    session.delivery_complete(1.082)
    assert session.tick(1.083) is None
    assert not session.replacing
    assert session.active_rows is None


@pytest.mark.parametrize('second,stamp', [(None, 1.015), ((160, 180), 1.015), ((230, 180), 1.07)])
def test_latest_eligible_detection_starts_without_confirmation(second, stamp):
    session = HeadAimSession(bank(), threading.Event())
    session.observe((230, 180), 1.)
    session.observe(second, stamp)
    session.observe((230, 180), stamp + .01)
    assert session.tick(stamp + .01) == (0, 0)


def test_stale_detection_cannot_start_movement():
    session = HeadAimSession(bank(), threading.Event())
    session.observe((230, 180), 1.)
    session.observe((230, 180), 1.)
    assert session.tick(1.151) is None


def test_shutdown_can_still_interrupt_active_movement():
    stop = threading.Event()
    session = HeadAimSession(bank(), stop)
    session.observe((230, 180), 1.)
    session.observe((230, 180), 1.03)
    session.tick(1.03)
    stop.set()
    assert session.tick(1.04) is None


def test_settling_starts_at_ack_and_requires_a_post_settle_frame():
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event(), settle_ms=100)
    session.observe((230, 180), 1.)
    session.tick(1.)
    session.tick(1.051)
    assert session.awaiting_delivery
    session.observe((230, 180), 1.07)
    assert session.tick(1.07) == (0, 0)
    session.delivery_complete(1.08)
    assert session.feedback_after == pytest.approx(1.18)
    session.observe((230, 180), 1.17)
    assert session.tick(1.19) is None  # Time passed, but frame predates feedback.
    session.observe((230, 180), 1.181)
    assert session.tick(1.19) == (0, 0)
    status = session.timing_status()
    assert status['last_feedback_wait_ms'] == pytest.approx(110)
    assert status['last_source_age_ms'] == pytest.approx(9)


def test_manual_movement_and_clicks_forward_during_feedback_wait():
    from tools.relay_mouse import StreamInput, MotionRouter
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event(), settle_ms=100)
    session.observe((230, 180), 1.)
    session.tick(1.)
    session.tick(1.051)
    session.delivery_complete(1.055)
    # Router calls without a timestamp, so fix only that clock for this test.
    class WaitingAim:
        def tick(self):
            return session.tick(1.06)
    inputs = StreamInput(1)
    router = MotionRouter(inputs, WaitingAim())
    inputs.sample(7, -3, 1)
    inputs.sample(2, 1, 0)
    assert router.take() == (7, -3, 1)
    assert router.take() == (2, 1, 0)
    assert not session.replacing


@pytest.mark.parametrize('delay', [-1, float('nan'), float('inf'), 1001])
def test_invalid_settling_time(delay):
    with pytest.raises(ValueError):
        HeadAimSession(bank(), threading.Event(), settle_ms=delay)


def test_zero_settling_still_requires_frame_after_delivery():
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event(), settle_ms=0)
    session.observe((230, 180), 1.)
    session.tick(1.)
    session.tick(1.051)
    session.delivery_complete(1.055)
    assert session.tick(1.056) is None
    session.observe((230, 180), 1.057)
    assert session.tick(1.058) == (0, 0)


def test_default_wait_is_twenty_ms_and_does_not_delay_first_aim():
    session = HeadAimSession(bank(min_ms=50, max_ms=50), threading.Event())
    session.observe((230, 180), 1.)
    assert session.tick(1.) == (0, 0)
    session.tick(1.051)
    session.delivery_complete(1.055)
    assert session.feedback_after == pytest.approx(1.075)
    session.observe((230, 180), 1.074)
    assert session.tick(1.076) is None
    session.observe((230, 180), 1.077)
    assert session.tick(1.077) == (0, 0)


@pytest.mark.parametrize('target', [(270, 240), (160, 180), (200, 280), (200, 200)])
def test_function_paths_have_exact_endpoints_and_bounded_random_curvature(target):
    generator = SmoothTrajectory(rng=random.Random(8))
    delta = np.asarray(target) - [200, 200]
    distance = np.linalg.norm(delta)
    durations = []
    for _ in range(50):
        rows = generator.plan(target)
        durations.append(rows[-1, 0])
        assert 50 <= rows[-1, 0] <= 100
        np.testing.assert_array_equal(rows[0, 1:], [200, 200])
        np.testing.assert_array_equal(rows[-1, 1:], target)
        np.testing.assert_allclose(np.diff(rows[:-1, 0]), 4)
        relative = rows[:, 1:3] - [200, 200]
        if distance:
            forward = relative @ (delta / distance)
            sideways = relative @ np.array([-delta[1], delta[0]]) / distance
            assert np.all(np.diff(forward) > 0)
            assert np.max(np.abs(sideways)) <= min(3, distance * .05) + 1e-10
        else:
            assert not np.any(relative)
    assert len(set(durations)) > 10


def test_function_curve_randomizes_shape_even_at_fixed_duration():
    generator = SmoothTrajectory(min_ms=75, max_ms=75, rng=random.Random(4))
    first, second = generator.plan((300, 200)), generator.plan((300, 200))
    np.testing.assert_array_equal(first[:, 0:2], second[:, 0:2])
    assert not np.array_equal(first[:, 2], second[:, 2])


def test_function_planner_integrates_with_uninterrupted_controller():
    session = HeadAimSession(SmoothTrajectory(min_ms=50, max_ms=50), threading.Event())
    session.observe((230, 180), 1.)
    assert session.tick(1.) == (0, 0)
    session.observe(None, 1.02)
    moves = [session.tick(1.025), session.tick(1.051)]
    assert tuple(np.sum(moves, axis=0)) == (30, -20)
    session.delivery_complete(1.055)
    assert session.tick(1.056) is None
