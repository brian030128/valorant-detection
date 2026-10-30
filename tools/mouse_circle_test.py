"""Run USB-clocked circles on the receiving PC and save firmware timing stats.

python tools/mouse_circle_test.py --port COM6
python tools/mouse_circle_test.py --port COM6 --draw  # focus a blank Paint canvas
"""

import argparse
import json
import math
from pathlib import Path
import time

if __package__:
    from .relay_mouse import open_relay
else:
    from relay_mouse import open_relay


def circle_command(radius, period, turns, draw=False):
    if not isinstance(radius, int) or not 1 <= radius <= 1000:
        raise ValueError('radius must be an integer in 1..1000 HID counts')
    if not math.isfinite(period) or not .5 <= period <= 10:
        raise ValueError('period must be in 0.5..10 seconds')
    if not isinstance(turns, int) or not 1 <= turns <= 20:
        raise ValueError('turns must be an integer in 1..20')
    slots = round(period * 1000)
    if slots * turns > 60000:
        raise ValueError('total duration must not exceed 60 seconds')
    return f'CIRCLE {radius} {slots} {turns} {int(draw)}'


def read_stats(relay):
    relay.port.write(relay.frame('STATS'))
    reply = relay.read_line(time.monotonic() + 1)
    if not reply.startswith('OK STATS '):
        raise RuntimeError(f'Invalid firmware statistics: {reply}')
    values = dict(part.split('=', 1) for part in reply.split()[2:])
    required = {'REPORTS', 'ELAPSED_US', 'MIN_US', 'MAX_US', 'GAPS', 'CIRCLE'}
    if set(values) != required:
        raise RuntimeError(f'Invalid firmware statistics: {reply}')
    stats = {key.lower(): int(value) for key, value in values.items()}
    if stats['reports'] < 0 or stats['elapsed_us'] < 0 or stats['circle'] not in (0, 1):
        raise RuntimeError(f'Invalid firmware statistics: {reply}')
    stats['average_hz'] = ((stats['reports'] - 1) * 1_000_000 / stats['elapsed_us']
                           if stats['reports'] > 1 and stats['elapsed_us'] else None)
    return stats


def run_circle(relay, command, *, clock=time.monotonic, wait=time.sleep):
    """Keep the watchdog alive; query completion rather than assuming a duration."""
    relay.request('PACE', 'OK PACE HZ=1000 SOURCE=USB', timeout=1)
    relay.request(command, 'OK CIRCLE', timeout=1)
    started = clock()
    _, _, period_slots, turns, _ = command.split()
    deadline = started + int(period_slots) * int(turns) / 1000 + 5
    while clock() < deadline:
        # 50 ms also satisfies the 250 ms communication watchdog.
        wait(.05)
        relay.request('PING', 'OK PING', timeout=.2)
        stats = read_stats(relay)
        if not stats['circle']:
            stats['wall_seconds'] = clock() - started
            stats['measurement'] = 'firmware USB-completion task timestamps; not receiver-side timestamps'
            return stats
    raise TimeoutError('Circle did not complete; stopping without replaying movement')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM6')
    parser.add_argument('--radius', type=int, default=240, help='Radius in HID counts, not screen pixels (default 240).')
    parser.add_argument('--period', type=float, default=1, help='Seconds per turn at 1000 reports/sec (default 1).')
    parser.add_argument('--turns', type=int, default=3)
    parser.add_argument('--draw', action='store_true', help='Hold left button for the circles; focus a blank drawing canvas first.')
    parser.add_argument('--countdown', type=int, default=5)
    parser.add_argument('--dry-run', action='store_true', help='Print the command without opening serial or moving either cursor.')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'runs/mouse_circle_test.json')
    args = parser.parse_args()
    try:
        command = circle_command(args.radius, args.period, args.turns, args.draw)
        if not 0 <= args.countdown <= 60:
            raise ValueError('countdown must be in 0..60 seconds')
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({'command': command, 'usb_hz': 1000, 'draw': args.draw}))
        return
    try:
        with open_relay(args.port) as relay:
            if not relay.streaming:
                raise RuntimeError('Circle test requires the updated streaming firmware')
            relay.request('PACE', 'OK PACE HZ=1000 SOURCE=USB', timeout=1)
            print('Position the RECEIVING cursor with room for a circle extending left of it.'
                  ' Press Ctrl+C here or use the board stop switch to stop.', flush=True)
            if args.draw:
                print('Drawing enabled: focus a blank canvas on the receiving PC.', flush=True)
            # STREAM is already active; maintain its watchdog during countdown.
            for remaining in range(args.countdown * 20, 0, -1):
                if remaining % 20 == 0:
                    print(f'Starting in {remaining // 20}...', flush=True)
                time.sleep(.05)
                relay.request('PING', 'OK PING', timeout=.2)
            stats = run_circle(relay, command)
            result = {'command': command, 'advertised_hz': 1000, **stats}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            hz = stats['average_hz']
            if hz is None or not 980 <= hz <= 1020:
                raise RuntimeError('Measured report rate is outside 980..1020 Hz; inspect the saved timing results')
    except KeyboardInterrupt:
        print('Stopped; relay closed with STOP.')


if __name__ == '__main__':
    main()
