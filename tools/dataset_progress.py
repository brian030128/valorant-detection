"""Read-only progress monitor for synthetic rendering and labeling (stdlib only)."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[1]
SPLITS = ('train', 'val', 'test')


def count_files(directory, suffix):
    try:
        with os.scandir(directory) as entries:
            return sum(entry.name.endswith(suffix) and entry.is_file() for entry in entries)
    except FileNotFoundError:
        return 0


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def log_tail(path):
    try:
        with path.open('rb') as stream:
            prefix = stream.read(4)
            encoding = 'utf-16-le' if prefix.startswith(b'\xff\xfe') else 'utf-8'
            stream.seek(0, 2)
            offset = max(0, stream.tell() - 32768)
            if encoding == 'utf-16-le': offset -= offset % 2
            stream.seek(offset)
            return stream.read().decode(encoding, errors='replace')
    except OSError:
        return ''


def snapshot(root, total, log):
    # Metadata is saved last, so it is the render-completion marker for a frame.
    rendered = {split: count_files(root/'metadata'/split, '.json') for split in SPLITS}
    labels = {split: count_files(root/'labels'/split, '.txt') for split in SPLITS}
    audit = read_json(root/'audit.json')
    job = read_json(root/'generation_status.json') or {}
    if job.get('active_dataset') and job.get('phase')=='rendering':
        active=Path(job['active_dataset'])
        # Assembly copies completed stages; count IDs once across staging/output.
        for split in SPLITS:
            for kind,suffix,counts in [('metadata','.json',rendered),('labels','.txt',labels)]:
                counts[split]=len({p.name for source in [root,active] for p in (source/kind/split).glob('*'+suffix)})
        child=read_json(active/'generation_status.json') or {}
        job={**job,**child,'target':total}
    if job.get('current_log'):
        log = Path(job['current_log'])
    elif job:
        log = root/'logs/audit.log'
    tail = log_tail(log)
    validations = re.findall(r'VALIDATED\s+(\d+)/(\d+)', tail)
    checked = int(validations[-1][0]) if validations else 0
    audit_ok = bool(audit and audit.get('images') == total)
    if audit_ok:
        checked = total
    previews = all((root/name).is_file() for name in ('preview_scenes.jpg', 'preview_heads.jpg'))
    complete = audit_ok and sum(rendered.values()) == total and sum(labels.values()) == total and previews
    failure = job.get('phase')=='failed' or (not job and ('Traceback (most recent call last)' in tail or 'AssertionError' in tail))
    return {'rendered': rendered, 'labels': labels, 'checked': checked,
            'audit_ok': audit_ok, 'previews': previews, 'complete': complete,
            'failure': failure, 'audit': audit, 'job': job, 'log': log}


def bar(label, count, total, width=36):
    fraction = min(1, max(0, count/total))
    filled = int(width*fraction)
    return f'{label:<17} [{"#"*filled}{"-"*(width-filled)}] {fraction:6.1%}  {count:>6,}/{total:,}'


def enable_ansi():
    if not sys.stdout.isatty():
        return False
    if os.name != 'nt':
        return True
    try:
        kernel = ctypes.windll.kernel32
        kernel.GetStdHandle.restype = ctypes.c_void_p
        kernel.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and
                    kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def display(state, root, total, log, rate):
    columns = max(40, shutil.get_terminal_size((100, 24)).columns)
    width = max(8, min(36, columns-50))
    stage = 'COMPLETE' if state['complete'] else 'RENDERING' if sum(state['rendered'].values()) < total else 'LABELING / VALIDATING'
    if state['failure'] and not state['complete']:
        stage = 'JOB FAILED - see error below'
    lines = [f'VALORANT DATASET  |  {stage}  |  {time.strftime("%H:%M:%S")}',
             str(root), '',
             bar('Rendered images', sum(state['rendered'].values()), total, width),
             bar('Labels written', sum(state['labels'].values()), total, width),
             bar('Validated images', state['checked'], total, width), '',
             'Split images: ' + '  |  '.join(f'{s} {state["rendered"][s]:,}' for s in SPLITS),
             f'Final audit: {"PASSED" if state["audit_ok"] else "pending"}  |  Preview sheets: {"ready" if state["previews"] else "pending"}']
    if rate > 0 and not state['complete']:
        remaining = total - (sum(state['rendered'].values()) if stage == 'RENDERING' else state['checked'])
        eta = round(remaining/rate)
        lines.append(f'Current stage: {rate:.1f} images/s  |  Estimated remaining: {eta//60}m {eta%60:02d}s')
    else:
        lines.append('Validation progress updates every 1,000 images.')
    job=state.get('job',{})
    active=job.get('active_workers',{})
    if active:
        lines.append('Workers: '+' | '.join(f'{name} {p["batch_start"]+1}-{p["batch_start"]+p["batch_size"]} (try {p["attempt"]})' for name,p in sorted(active.items())))
    if job.get('current_map'):lines.append(f'Map: {job["current_map"]}  |  Job: {job.get("phase","unknown")}')
    if job.get('phase')=='rendering' and 'batch_start' in job:
        lines.append(f'Batch: {job["batch_start"]+1}-{job["batch_start"]+job["batch_size"]}  |  Attempt: {job.get("attempt",1)}')
    if job.get('error'):lines.append('Error: '+job['error'])
    lines.append(f'Log: {state.get("log",log)}')
    lines.append('Finished. Dataset ready.' if state['complete'] else 'Job stopped; completed images are retained.' if state['failure'] else 'Ctrl+C stops this monitor only; the dataset job keeps running.')
    # Avoid terminal wrapping so cursor-up refreshes replace exactly this block.
    def fit(line):
        if len(line) < columns: return line
        half = (columns-4)//2
        return line[:half]+'...'+line[-(columns-4-half):]
    return '\n'.join(map(fit, lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', nargs='?', type=Path, default=WORKSPACE/'datasets/valorant_synthetic_10k')
    parser.add_argument('--total', type=int, default=10000)
    parser.add_argument('--interval', type=float, default=2, help='Refresh interval in seconds (default: 2)')
    parser.add_argument('--log', type=Path, default=WORKSPACE/'environment/dataset_finalization.log')
    parser.add_argument('--once', action='store_true', help='Print one snapshot and exit')
    parser.add_argument('--watch', action='store_true', help='Keep watching after completion')
    args = parser.parse_args()
    if args.total <= 0 or args.interval <= 0:
        parser.error('--total and --interval must be positive')
    root = args.dataset.resolve(); log = args.log.resolve()
    ansi = enable_ansi(); previous_lines = 0; history = []; previous_stage = None
    try:
        while True:
            state = snapshot(root, args.total, log)
            stage = 'render' if sum(state['rendered'].values()) < args.total else 'validate'
            done = sum(state['rendered'].values()) if stage == 'render' else state['checked']
            now = time.monotonic()
            if stage != previous_stage:
                history = []; previous_stage = stage
            history.append((now, done))
            history = [(t, n) for t, n in history if now-t <= 120]
            rate = (done-history[0][1])/(now-history[0][0]) if len(history)>1 and now>history[0][0] else 0
            output = display(state, root, args.total, log, rate)
            if ansi and previous_lines:
                sys.stdout.write(f'\x1b[{previous_lines}F\x1b[J')
            print(output, flush=True)
            previous_lines = output.count('\n')+1
            if args.once or (state['complete'] and not args.watch):
                break
            if state['failure']:
                return 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\nMonitor stopped; rendering/labeling is unaffected.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
