import sys

import pytest

from tools.mouse_wheel import WheelBuffer, WindowsWheel


def test_high_resolution_wheel_accumulates_fractional_detents():
    wheel = WheelBuffer()
    wheel.add(30)
    wheel.add(30)
    wheel.add(30)
    assert wheel.take() == 0
    wheel.add(30)
    assert wheel.take() == 1
    wheel.add(-60)
    assert wheel.take() == 0
    wheel.add(-60)
    assert wheel.take() == -1
    assert wheel.remainder == 0


def test_wheel_direction_changes_are_never_cancelled_in_backlog():
    wheel = WheelBuffer()
    for delta in (120, 240, -120, -120, 120):
        wheel.add(delta)
    assert [wheel.take() for _ in range(4)] == [3, -2, 1, 0]


def test_wheel_fraction_sign_changes_preserve_net_fraction():
    wheel = WheelBuffer()
    for delta in (90, -60, -60):
        wheel.add(delta)
    assert wheel.take() == 0
    assert wheel.remainder == -30
    wheel.add(-90)
    assert wheel.take() == -1


@pytest.mark.skipif(sys.platform != 'win32', reason='requires Windows hook APIs')
def test_windows_wheel_hook_can_start_and_stop_without_input():
    wheel = WindowsWheel()
    try:
        wheel.start()
        assert wheel.ready.is_set() and wheel.thread.is_alive()
    finally:
        wheel.close()
    assert not wheel.thread.is_alive()
    assert wheel.error is None
