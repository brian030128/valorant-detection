"""Live USB HDMI preview with native center-crop YOLO predictions."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
COLORS = [(232, 110, 255), (255, 220, 70), (50, 240, 255)]
TARGET_CLASSES = {'enemy_body', 'enemy_head'}


def text(image, label, position, color=(235, 235, 235), scale=0.55):
    cv2.putText(image, label, position, cv2.FONT_HERSHEY_SIMPLEX, scale,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(image, label, position, cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, 1, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--model', type=Path, default=ROOT / 'models/valorant-center400-yolo11s-9460cdaf8b55')
    parser.add_argument('--frames', type=int, default=0, help='Stop after N frames (0: interactive).')
    parser.add_argument('--mouse', action='store_true', help='Recenter local cursor and relay movement through the mouse spoofer.')
    parser.add_argument('--mouse-port', default='COM6', help='Mouse spoofer UART port (default: COM6).')
    parser.add_argument('--mouse-scale', type=float, default=1.0, help='HID counts per local cursor pixel.')
    parser.add_argument('--mouse-hz', type=int, default=250, help='Manual cursor and generated trajectory sampling rate (default: 250).')
    parser.add_argument('--mouse-dry-run', action='store_true', help='With --mouse, recenter and print movement without serial output.')
    parser.add_argument('--aim', action='store_true', help='Generate paths to heads in the central 200x200 square; add --mouse for UART movement.')
    parser.add_argument('--aim-min-ms', type=float, default=50, help='Minimum random movement duration (default 50 ms).')
    parser.add_argument('--aim-max-ms', type=float, default=100, help='Maximum random movement duration (default 100 ms).')
    parser.add_argument('--aim-checkpoint', type=Path, help='Override the mouse-generator GRU checkpoint.')
    parser.add_argument('--aim-generator', choices=['smooth', 'ai'], default='smooth', help='Trajectory source (default: smooth function, without an AI model).')
    parser.add_argument('--aim-scale', type=float, default=1., help='Receiving-system HID counts per capture pixel; calibrate for game sensitivity.')
    parser.add_argument('--aim-settle-ms', type=float, default=20, help='Wait after final HID acknowledgement, then require a newer frame (default 20 ms; calibrate for capture delay).')
    args = parser.parse_args()
    if args.mouse_dry_run and not args.mouse:
        parser.error('--mouse-dry-run requires --mouse')
    if args.aim_checkpoint is not None and args.aim_generator != 'ai':
        parser.error('--aim-checkpoint requires --aim-generator ai')
    if not math.isfinite(args.mouse_scale) or not 0 < args.mouse_scale <= 100:
        parser.error('--mouse-scale must be finite and in (0, 100]')
    if not 1 <= args.mouse_hz <= 1000:
        parser.error('--mouse-hz must be in 1..1000')
    if not 50 <= args.aim_min_ms <= args.aim_max_ms <= 100:
        parser.error('aim duration bounds must satisfy 50 <= min <= max <= 100 ms')
    if not math.isfinite(args.aim_scale) or not 0 < args.aim_scale <= 100:
        parser.error('--aim-scale must be finite and in (0, 100]')
    if not math.isfinite(args.aim_settle_ms) or not 0 <= args.aim_settle_ms <= 1000:
        parser.error('--aim-settle-ms must be finite and in 0..1000')
    config = json.loads((args.model / 'thresholds.json').read_text())
    provenance = json.loads((args.model / 'download_provenance.json').read_text())
    digest = hashlib.sha256((args.model / 'best.pt').read_bytes()).hexdigest()
    if digest != provenance['best_sha256']:
        raise RuntimeError('Checkpoint checksum does not match its provenance.')
    torch.set_num_threads(4)
    device = 0 if torch.cuda.is_available() else 'cpu'
    model = YOLO(str(args.model / 'best.pt'))
    thresholds = config['confidence']
    if set(model.names.values()) != TARGET_CLASSES or set(thresholds) != TARGET_CLASSES:
        raise RuntimeError('Live detection requires the two-class enemy_body/enemy_head checkpoint and matching thresholds.')
    if config['input_size'] != 416 or config['padding'] != [8, 8, 8, 8]:
        raise RuntimeError('Expected native 400px input with eight pixels of padding on each side.')
    model.predict(np.full((416, 416, 3), 114, np.uint8), imgsz=416,
                  device=device, verbose=False)
    if args.aim:
        if __package__:
            from .head_trajectory import TrajectoryBank, SmoothTrajectory, HeadAimSession, select_head
        else:
            from head_trajectory import TrajectoryBank, SmoothTrajectory, HeadAimSession, select_head
        print(f'Preparing {args.aim_generator} trajectories...', flush=True)
        options = dict(min_ms=args.aim_min_ms, max_ms=args.aim_max_ms, hz=args.mouse_hz)
        aim_bank = (TrajectoryBank.load(args.aim_checkpoint, **options)
                    if args.aim_generator == 'ai' else SmoothTrajectory(**options))
    capture = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not capture.isOpened():
        raise RuntimeError('Cannot open capture device.')
    latest = [None, 0, 0.0]
    lock = threading.Lock()
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            ok, frame = capture.read()
            if not ok:
                stop.set()
                break
            with lock:
                latest[:] = [frame, latest[1] + 1, time.monotonic()]

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    output = ROOT / 'runs/live_capture'
    output.mkdir(parents=True, exist_ok=True)
    title = 'USB HDMI - YOLO center400 | Q / Esc to quit'
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, 1500, 680)
    previous = 0
    count = 0
    started = time.monotonic()
    last_report = 0.0
    print(json.dumps({'event': 'started', 'device': str(device), 'model': provenance,
                      'thresholds': thresholds}), flush=True)
    mouse_stack = ExitStack()
    try:
        if args.aim:
            aim_session = HeadAimSession(aim_bank, stop, scale=args.aim_scale, settle_ms=args.aim_settle_ms)
            if not args.mouse:
                mouse_stack.enter_context(aim_session)
        if args.mouse:
            if __package__:
                from .relay_mouse import MouseSession
            else:
                from relay_mouse import MouseSession
            mouse_session = mouse_stack.enter_context(MouseSession(args.mouse_port, stop,
                                      scale=args.mouse_scale, hz=args.mouse_hz,
                                      dry_run=args.mouse_dry_run,
                                      aim=aim_session if args.aim else None))
        while not stop.is_set():
            with lock:
                frame, sequence, captured_at = latest
            if frame is None or sequence == previous:
                if cv2.waitKey(1) & 255 in (27, ord('q')):
                    break
                if time.monotonic() - (captured_at or started) > 10:
                    raise RuntimeError('Capture has not delivered a new frame for 10 seconds.')
                continue
            previous = sequence
            height, width = frame.shape[:2]
            if min(height, width) < 400:
                raise RuntimeError('Capture resolution must be at least 400x400.')
            x, y = (width - 400) // 2, (height - 400) // 2
            raw_crop = frame[y:y + 400, x:x + 400].copy()
            crop = raw_crop.copy()
            padded = cv2.copyMakeBorder(crop, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(114, 114, 114))
            begin = time.perf_counter()
            result = model.predict(padded, imgsz=416, device=device,
                                   conf=min(thresholds.values()), iou=config['nms_iou'],
                                   max_det=config['max_det'], verbose=False)[0]
            inference_ms = (time.perf_counter() - begin) * 1000
            full = frame.copy()
            predictions = []
            for box in result.boxes.data.cpu().numpy():
                cls, confidence = int(box[5]), float(box[4])
                name = model.names[cls]
                if name not in TARGET_CLASSES or confidence < thresholds[name]:
                    continue
                coords = np.clip(box[:4] - 8, 0, 399).astype(int)
                x0, y0, x1, y1 = coords.tolist()
                label = f'{name} {confidence:.2f}'
                color = COLORS[cls % len(COLORS)]
                cv2.rectangle(crop, (x0, y0), (x1, y1), color, 2)
                text(crop, label, (min(x0, 265), max(16, y0 - 5)), color, 0.45)
                cv2.rectangle(full, (x + x0, y + y0), (x + x1, y + y1), color, 2)
                text(full, label, (x + x0, max(20, y + y0 - 5)), color)
                predictions.append({'class': name, 'confidence': confidence, 'crop_xyxy': coords.tolist()})
            # The capture's exact center can lie on a half pixel for odd dimensions.
            center = (width / 2 - x, height / 2 - y)
            lo = tuple(round(v - 100) for v in center)
            hi = tuple(round(v + 100) for v in center)
            cv2.rectangle(crop, lo, hi, (90, 240, 90), 1)
            cv2.rectangle(full, (x + lo[0], y + lo[1]), (x + hi[0], y + hi[1]), (90, 240, 90), 1)
            text(crop, 'AIM 200x200', (lo[0], lo[1] - 7), (90, 240, 90), 0.40)
            text(full, 'AIM 200x200', (x + lo[0], y + lo[1] - 7), (90, 240, 90), 0.45)
            if args.aim:
                target = select_head(predictions, center)
                aim_session.observe(target, captured_at, center)
                rows = aim_session.rows
                if rows is not None:
                    points = np.rint(rows[:, 1:3]).astype(np.int32).reshape(-1, 1, 2)
                    cv2.polylines(crop, [points], False, (80, 180, 255), 1, cv2.LINE_AA)
                if target is not None:
                    cv2.circle(crop, tuple(round(v) for v in target), 4, (90, 240, 90), 1)
            cv2.rectangle(full, (x, y), (x + 400, y + 400), (220, 220, 220), 2)
            canvas = np.full((680, 1500, 3), (27, 24, 21), np.uint8)
            ratio = min(960 / width, 540 / height)
            view = cv2.resize(full, (round(width * ratio), round(height * ratio)))
            canvas[70:70 + view.shape[0], :view.shape[1]] = view
            canvas[70:610, 960:1500] = cv2.resize(crop, (540, 540))
            text(canvas, f'USB HDMI {width}x{height} | center 400x400 detection', (15, 27), scale=0.7)
            text(canvas, f'YOLO11s {provenance["revision"][:12]} | {inference_ms:.1f} ms inference', (15, 53))
            text(canvas, 'CENTER CROP / PREDICTIONS', (970, 45))
            text(canvas, f'Torso >= {thresholds["enemy_body"]:.2f} (pink) | Head >= {thresholds["enemy_head"]:.2f} (cyan)', (15, 636))
            text(canvas, f'{len(predictions)} detections | Q/Esc: quit | S: save snapshot + native crop', (15, 662))
            if args.aim:
                mode = args.mouse_port if args.mouse and not args.mouse_dry_run else 'PREVIEW'
                duration = f'{rows[-1, 0]:g}ms' if rows is not None else f'{args.aim_min_ms:g}-{args.aim_max_ms:g}ms'
                text(canvas, f'Aim {mode} {duration}: {aim_session.state}', (970, 636), scale=0.36)
            elif args.mouse:
                mode = 'DRY RUN' if args.mouse_dry_run else args.mouse_port
                text(canvas, f'Mouse {mode}: {mouse_session.state} | Q/Esc', (970, 636), scale=0.40)
            cv2.imshow(title, canvas)
            key = cv2.waitKey(1) & 255
            count += 1
            now = time.monotonic()
            if now - last_report >= 5:
                status = {'frames': count, 'capture_sequence': sequence, 'resolution': [width, height],
                          'model_revision': provenance['revision'], 'model_classes': model.names,
                          'native_crop_size': [400, 400], 'inference_input_size': [416, 416],
                          'inference_ms': inference_ms, 'predictions': predictions, 'time': time.time()}
                if args.aim:
                    status['aim'] = {'region_size': [200, 200], 'target': target,
                                     'generator': args.aim_generator,
                                     'sample_hz': aim_bank.hz,
                                     'duration_ms': float(rows[-1, 0]) if rows is not None else None,
                                     'duration_range_ms': [args.aim_min_ms, args.aim_max_ms], 'state': aim_session.state,
                                     'last_playback_ms': aim_session.last_duration_ms,
                                     'feedback_timing': aim_session.timing_status(),
                                     'trajectory_txy': rows.tolist() if rows is not None else None}
                (output / 'status.json').write_text(json.dumps(status, indent=2))
                cv2.imwrite(str(output / 'preview.jpg'), canvas)
                print(json.dumps(status), flush=True)
                last_report = now
            if key == ord('s'):
                snapshot_id = time.time_ns()
                cv2.imwrite(str(output / f'snapshot_{snapshot_id}.png'), canvas)
                cv2.imwrite(str(output / f'crop_{snapshot_id}_native.png'), raw_crop)
                cv2.imwrite(str(output / f'frame_{snapshot_id}_native.png'), frame)
            if key in (27, ord('q')) or (args.frames and count >= args.frames):
                break
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        stop.set()
        try:
            mouse_stack.close()
        finally:
            thread.join(timeout=2)
            capture.release()
            cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
