"""Measure fixed-threshold precision/recall on validation frames with one visible player."""
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def main():
    torch.set_num_threads(4)
    dataset = ROOT / 'datasets/valorant_synthetic_10k'
    run = ROOT / 'runs/train/yolo11n_synthetic_960'
    checkpoint = run / 'weights/best.pt'
    selected = []
    truths = {}
    for path in sorted((dataset / 'labels/val').glob('*.txt')):
        rows = np.array([list(map(float, line.split())) for line in path.read_text().splitlines() if line.strip()]).reshape(-1, 5)
        if np.isin(rows[:, 0], [0, 1]).sum() == 1:
            selected.append(str(dataset / 'images/val' / (path.stem + '.jpg')))
            truths[path.stem] = rows
    thresholds = [0.25, 0.5, 0.75]
    counts = {t: np.zeros((3, 3), dtype=int) for t in thresholds}  # TP, FP, FN
    model = YOLO(str(checkpoint))
    source = run / 'single_player_validation_images.txt'
    source.write_text('\n'.join(str(Path(p).resolve()) for p in selected), encoding='utf-8')
    for result in model.predict(str(source.resolve()), stream=True, imgsz=960, batch=8, device=0,
                                conf=min(thresholds), iou=0.7, max_det=100, verbose=False):
        rows = truths[Path(result.path).stem]
        centers, sizes = rows[:, 1:3], rows[:, 3:5]
        gt = np.concatenate((centers - sizes / 2, centers + sizes / 2), axis=1)
        height, width = result.orig_shape
        gt *= np.array([width, height, width, height])
        pred = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)
        for threshold in thresholds:
            for cls in range(3):
                targets = gt[rows[:, 0] == cls]
                indices = np.where((classes == cls) & (scores >= threshold))[0]
                indices = indices[np.argsort(-scores[indices])]
                used = set()
                tp = 0
                for index in indices:
                    box = pred[index]
                    overlap = np.maximum(0, np.minimum(box[2:], targets[:, 2:]) - np.maximum(box[:2], targets[:, :2])).prod(axis=1)
                    union = np.prod(box[2:] - box[:2]) + np.prod(targets[:, 2:] - targets[:, :2], axis=1) - overlap
                    ious = overlap / np.maximum(union, 1e-12)
                    for matched in used:
                        ious[matched] = -1
                    if len(ious) and ious.max() >= 0.5:
                        used.add(int(ious.argmax()))
                        tp += 1
                counts[threshold][cls] += [tp, len(indices) - tp, len(targets) - tp]
    def metrics(values):
        tp, fp, fn = map(int, values)
        return dict(tp=tp, fp=fp, fn=fn, precision=tp/(tp+fp) if tp+fp else None,
                    recall=tp/(tp+fn) if tp+fn else None)
    report = dict(images=len(selected), split='val', selection='Exactly one visible enemy or teammate body label; head is evaluated separately',
                  checkpoint=str(checkpoint), checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                  imgsz=960, matching_iou=0.5, nms_iou=0.7, thresholds={}, image_stems=list(truths))
    for threshold, values in counts.items():
        report['thresholds'][str(threshold)] = {name: metrics(values[c]) for c, name in enumerate(['enemy', 'teammate', 'head'])}
        report['thresholds'][str(threshold)]['all_micro'] = metrics(values.sum(axis=0))
    output = run / 'single_player_validation.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'image_stems'}, indent=2))


if __name__ == '__main__':
    main()
