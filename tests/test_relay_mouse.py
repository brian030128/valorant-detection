import pytest
import threading
from contextlib import contextmanager

from tools import relay_mouse

from tools.relay_mouse import PendingMotion, check_firmware, load_protocol, send_motion


def test_scaled_movement_preserves_fractional_counts():
    pending = PendingMotion(0.25)
    total = [0, 0]
    for _ in range(100):
        pending.add(1, -1)
        dx, dy = pending.take()
        total[0] += dx
        total[1] += dy
    assert total == [25, -25]
    assert pending.take() == (0, 0)


def test_backlog_fails_instead_of_clipping():
    pending = PendingMotion(1)
    with pytest.raises(RuntimeError, match="backlog"):
        pending.add(32768, 0)


def test_firmware_readiness_and_version():
    check_firmware("OK HELLO 1 4096 1000 60000000 1500 USB=1")
    with pytest.raises(RuntimeError, match="USB=0"):
        check_firmware("OK HELLO 1 4096 1000 60000000 1500 USB=0")
    with pytest.raises(RuntimeError, match="USB=0"):
        check_firmware("OK HELLO 2 4096 10000 60000000 1500 USB=0")
    assert check_firmware("OK HELLO 2 4096 10000 60000000 1500 USB=1") == 127
    assert check_firmware("OK HELLO 2 4096 10000 60000000 1500 USB=0", require_usb=False) == 127
    with pytest.raises(RuntimeError, match="Unsupported"):
        check_firmware("OK HELLO 4 4096 10000 60000000 1500 USB=1")
    assert check_firmware("OK HELLO 3 4096 10000 60000000 1500 USB=1") == 32767


@pytest.mark.parametrize('delta', [(1000, -400), (-32767, 32767), (0, -500)])
def test_v2_splitting_preserves_total_and_report_bounds(delta):
    pending = PendingMotion(1)
    pending.add(*delta)
    total = [0, 0]
    for _ in range(300):
        dx, dy = pending.take(127)
        assert max(abs(dx), abs(dy)) <= 127
        total[0] += dx
        total[1] += dy
    assert tuple(total) == delta
    assert pending.take(127) == (0, 0)


class Port:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def readline(self):
        return next(self.replies)


def test_movement_uses_submodule_protocol():
    protocol = load_protocol()
    port = Port([b"OK LOAD\n", b"OK E 0\n", b"OK RUN\n", b"DONE 1 50\n"])
    send_motion(protocol.Relay(port), 12, -5)
    assert port.writes == [b''.join(protocol.frame(command) for command in
                           ["LOAD 1", "E 0 0 12 -5 0 0", "RUN"])]


def test_board_error_is_not_retried():
    protocol = load_protocol()
    port = Port([b"OK LOAD\n", b"OK E 0\n", b"OK RUN\n", b"ERR HID_SEND\n"])
    with pytest.raises(RuntimeError, match="HID_SEND"):
        send_motion(protocol.Relay(port), 1, 2)
    assert len(port.writes) == 1


def test_session_joins_capture_before_closing_serial(monkeypatch):
    events = []
    entered = threading.Event()
    stop = threading.Event()

    @contextmanager
    def connection(port, **kwargs):
        assert port == 'COM6'
        events.append('open')
        yield 'relay'
        events.append('close')

    def capture(relay, **kwargs):
        assert relay == 'relay'
        entered.set()
        kwargs['stop'].wait(2)
        events.append('restored')

    monkeypatch.setattr(relay_mouse, 'open_relay', connection)
    monkeypatch.setattr(relay_mouse, 'capture', capture)
    with relay_mouse.MouseSession('COM6', stop):
        assert entered.wait(2)
    assert stop.is_set()
    assert events == ['open', 'restored', 'close']


def test_session_failure_stops_preview_and_surfaces_error(monkeypatch):
    stop = threading.Event()

    def fail(*args, **kwargs):
        raise RuntimeError('UART disconnected')

    monkeypatch.setattr(relay_mouse, 'capture', fail)
    with pytest.raises(RuntimeError, match='UART disconnected'):
        with relay_mouse.MouseSession(None, stop, dry_run=True):
            assert stop.wait(2)


def test_capture_restores_cursor_on_shared_shutdown(monkeypatch):
    stop = threading.Event()
    moves = []

    class Cursor:
        center = (100, 100)

        def position(self):
            return (25, 30)

        def move(self, position):
            moves.append(position)
            stop.set()

    monkeypatch.setattr(relay_mouse, 'WindowsCursor', Cursor)
    relay_mouse.capture(None, scale=1, hz=250, dry_run=True, stop=stop)
    assert moves == [(100, 100), (25, 30)]


@pytest.mark.parametrize('buttons', [1, 2, 3])
def test_click_batch_always_ends_with_release(buttons):
    protocol = load_protocol()
    port = Port([b'OK LOAD\n', b'OK E 0\n', b'OK E 1\n', b'OK RUN\n', b'DONE 2 0\n'])
    send_motion(protocol.Relay(port), 4, -2, buttons)
    assert port.writes == [b''.join(protocol.frame(command) for command in [
        'LOAD 2', f'E 0 0 4 -2 {buttons} 0', 'E 1 30000 0 0 0 0', 'RUN'])]


def test_click_edges_survive_busy_serial_without_repeating_holds():
    clicks = relay_mouse.ClickQueue()
    for mask in [0, 1, 1, 0, 2, 2, 0, 3, 3, 0]:
        clicks.sample(mask)
    assert [clicks.take() for _ in range(4)] == [1, 2, 3, 0]


@pytest.mark.parametrize('key', [0x51, 0x1B])
def test_global_quit_keys(key):
    class API:
        def GetAsyncKeyState(self, candidate):
            return 0x8000 if candidate == key else 0
    cursor = relay_mouse.WindowsCursor.__new__(relay_mouse.WindowsCursor)
    cursor.api = API()
    assert cursor.quit_pressed()


def test_global_q_restores_cursor_and_stops_capture(monkeypatch):
    moves = []
    stop = threading.Event()

    class Cursor:
        center = (100, 100)

        def position(self):
            return (20, 30)

        def move(self, position):
            moves.append(position)

        def quit_pressed(self):
            return True

    monkeypatch.setattr(relay_mouse, 'WindowsCursor', Cursor)
    relay_mouse.capture(None, scale=1, hz=250, dry_run=True, stop=stop)
    assert stop.is_set()
    assert moves == [(100, 100), (20, 30)]


def test_drag_preserves_down_movement_and_release():
    inputs = relay_mouse.StreamInput(1)
    inputs.sample(0, 0, 1)
    inputs.sample(10, 2, 1)
    inputs.sample(20, -2, 1)
    inputs.sample(0, 0, 0)
    inputs.sample(4, 5, 0)
    assert inputs.take() == (30, 0, 1)
    assert inputs.take() == (4, 5, 0)
    assert inputs.take() is None


def test_quick_right_click_is_not_coalesced_away():
    inputs = relay_mouse.StreamInput(1)
    for buttons in (2, 0, 2, 0):
        inputs.sample(0, 0, buttons)
    assert [inputs.take()[2] for _ in range(4)] == [2, 0, 2, 0]


def test_stream_fractional_scaling_and_split_preserve_button_state():
    inputs = relay_mouse.StreamInput(.25)
    for _ in range(100):
        inputs.sample(1, -1, 3)
    assert inputs.take(10) == (10, -10, 3)
    assert inputs.take(10) == (10, -10, 3)
    assert inputs.take(10) == (5, -5, 3)


def test_stream_acknowledgements_advance_sequence_without_retries():
    protocol = load_protocol()
    port = Port([b'OK M 0\n', b'ERR HID_SEND\n'])
    relay = protocol.Relay(port)
    relay.sequence = 0
    relay_mouse.send_stream(relay, 50, -20, 1)
    assert relay.sequence == 1
    with pytest.raises(RuntimeError, match='HID_SEND'):
        relay_mouse.send_stream(relay, 0, 0, 0)
    assert relay.sequence == 1
    assert port.writes == [protocol.frame('M 0 50 -20 1 0'), protocol.frame('M 1 0 0 0 0')]


def test_aim_replaces_motion_preserves_clicks_and_resumes_without_backlog():
    class Aim:
        output = None

        def tick(self):
            return self.output

    aim = Aim()
    inputs = relay_mouse.StreamInput(1)
    router = relay_mouse.MotionRouter(inputs, aim)
    inputs.sample(12, -3, 1)
    assert router.take() == (12, -3, 1)
    aim.output = (5, 6)
    inputs.sample(999, 999, 1)
    inputs.sample(999, 999, 0)
    inputs.sample(999, 999, 2)
    inputs.sample(999, 999, 0)
    assert router.take() == (5, 6, 1)
    aim.output = (0, 0)
    assert router.take() == (0, 0, 0)
    assert router.take() == (0, 0, 2)
    assert router.take() == (0, 0, 0)
    assert router.take() is None
    inputs.sample(900, 800, 0)
    aim.output = None
    assert router.take() == (0, 0, 0)
    inputs.sample(7, -4, 1)
    assert router.take() == (7, -4, 1)
    assert router.take() is None


def test_aim_movement_keeps_held_button_without_new_cursor_events():
    class Aim:
        def tick(self):
            return (3, 4)

    inputs = relay_mouse.StreamInput(1)
    inputs.sample(0, 0, 3)
    router = relay_mouse.MotionRouter(inputs, Aim())
    assert router.take() == (3, 4, 3)
    assert router.take() == (3, 4, 3)
    inputs.sample(0, 0, 0)
    assert router.take() == (3, 4, 0)
