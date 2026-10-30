import pytest

from tools import mouse_circle_test as circle


def test_circle_command_defaults_and_drawing():
    assert circle.circle_command(240, 1, 3) == 'CIRCLE 240 1000 3 0'
    assert circle.circle_command(120, .5, 2, True) == 'CIRCLE 120 500 2 1'


@pytest.mark.parametrize('radius,period,turns', [
    (0, 1, 3), (1001, 1, 3), (240, float('nan'), 3),
    (240, .49, 3), (240, 10, 7), (240, 1, 0), (240, 1, 21)])
def test_invalid_circle_parameters(radius, period, turns):
    with pytest.raises(ValueError):
        circle.circle_command(radius, period, turns)


class Relay:
    frame = staticmethod(lambda command: command.encode())

    def __init__(self, replies):
        self.replies = iter(replies)
        self.commands = []
        self.writes = []
        self.port = self

    def write(self, data):
        self.writes.append(data)

    def request(self, command, expected, timeout=1):
        self.commands.append(command)

    def read_line(self, deadline):
        return next(self.replies)


def test_stats_uses_intervals_not_report_count_for_rate():
    relay = Relay(['OK STATS REPORTS=1001 ELAPSED_US=1000000 MIN_US=990 MAX_US=1010 GAPS=0 CIRCLE=0'])
    stats = circle.read_stats(relay)
    assert stats['average_hz'] == 1000
    assert relay.writes == [b'STATS']


def test_circle_queries_completion_and_keeps_watchdog_alive():
    relay = Relay([
        'OK STATS REPORTS=501 ELAPSED_US=500000 MIN_US=990 MAX_US=1010 GAPS=0 CIRCLE=1',
        'OK STATS REPORTS=1001 ELAPSED_US=1000000 MIN_US=990 MAX_US=1010 GAPS=0 CIRCLE=0',
    ])
    elapsed = [0.]
    def wait(seconds):
        elapsed[0] += seconds
    result = circle.run_circle(relay, 'CIRCLE 240 1000 1 0', clock=lambda: elapsed[0], wait=wait)
    assert result['average_hz'] == 1000
    assert relay.commands == ['PACE', 'CIRCLE 240 1000 1 0', 'PING', 'PING']


def test_incomplete_circle_times_out_without_restarting_motion(monkeypatch):
    relay = Relay([])
    monkeypatch.setattr(circle, 'read_stats', lambda _: {'circle': 1})
    elapsed = [0.]
    def wait(seconds):
        elapsed[0] += seconds
    with pytest.raises(TimeoutError):
        circle.run_circle(relay, 'CIRCLE 240 1000 1 0', clock=lambda: elapsed[0], wait=wait)
    assert relay.commands.count('CIRCLE 240 1000 1 0') == 1
