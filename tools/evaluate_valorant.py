"""Evaluate the Hugging Face Valorant checkpoint on the local validation archive."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import platform
import urllib.request
import zipfile

import torch
import ultralytics
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
REPO = "keremberke/yolov8n-valorant-detection"
REVISION = "29e9db15fff51846fb077837650f546efb06463f"


def prepare_data():
    archive = ROOT / "datasets/raw/valid.zip"
    destination = ROOT / "datasets/valorant_yolo"
    images = destination / "images/val"
    labels = destination / "labels/val"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        data = json.loads(source.read("_annotations.coco.json"))
        categories = sorted(data["categories"], key=lambda c: c["id"])
        mapping = {c["id"]: i for i, c in enumerate(categories)}
        grouped = defaultdict(list)
        for annotation in data["annotations"]:
            assert not annotation.get("iscrowd", 0), "Crowd annotations need special handling"
            grouped[annotation["image_id"]].append(annotation)
        assert len({i["file_name"] for i in data["images"]}) == len(data["images"])
        for item in data["images"]:
            name = item["file_name"]
            assert Path(name).name == name
            (images / name).write_bytes(source.read(name))
            width, height = item["width"], item["height"]
            rows = []
            for annotation in grouped[item["id"]]:
                x, y, w, h = annotation["bbox"]
                assert w > 0 and h > 0 and x >= 0 and y >= 0
                assert x + w <= width + 1e-6 and y + h <= height + 1e-6
                rows.append(f"{mapping[annotation['category_id']]} {(x+w/2)/width:.10f} {(y+h/2)/height:.10f} {w/width:.10f} {h/height:.10f}")
            (labels / Path(name).with_suffix(".txt")).write_text("\n".join(rows) + ("\n" if rows else ""))
    names = [c["name"] for c in categories]
    config = destination / "validation.yaml"
    # Ultralytics requires a train entry even for a validation-only dataset.
    config.write_text(f"path: {json.dumps(destination.as_posix())}\ntrain: images/val\nval: images/val\nnames: {json.dumps(names)}\n")
    return config, names, {
        "archive": str(archive),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "images": len(data["images"]),
        "annotations": len(data["annotations"]),
        "class_counts": {c["name"]: sum(a["category_id"] == c["id"] for a in data["annotations"]) for c in categories},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    config, names, dataset = prepare_data()
    weights = ROOT / "models/yolov8n-valorant-detection" / REVISION / "best.pt"
    weights.parent.mkdir(parents=True, exist_ok=True)
    if not weights.exists():
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/best.pt"
        temporary = weights.with_suffix(".download")
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(weights)
    model = YOLO(str(weights))
    assert [model.names[i] for i in range(len(model.names))] == names, (model.names, names)
    print("Checkpoint training image size:", model.overrides.get("imgsz"))
    metrics = model.val(
        data=str(config), split="val", imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=0, conf=0.001, iou=0.7, max_det=300,
        half=False, plots=True, save_json=True,
        project=str(ROOT / "runs/valorant"), name=f"validation_{args.imgsz}",
    )
    per_class = []
    for index, class_id in enumerate(metrics.box.ap_class_index):
        precision, recall, map50, map5095 = metrics.box.class_result(index)
        per_class.append(dict(name=names[int(class_id)], precision=float(precision),
                              recall=float(recall), map50=float(map50), map50_95=float(map5095)))
    report = {
        "model": REPO, "revision": REVISION,
        "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "dataset": dataset, "settings": vars(args) | {"conf": 0.001, "iou": 0.7, "max_det": 300, "half": False},
        "versions": {"python": platform.python_version(), "torch": torch.__version__, "ultralytics": ultralytics.__version__},
        "device_name": torch.cuda.get_device_name(int(args.device)) if args.device.isdigit() else args.device,
        "metrics": {key: float(value) for key, value in metrics.results_dict.items()},
        "per_class": per_class, "speed_ms_per_image": metrics.speed,
        "output_directory": str(metrics.save_dir),
        "precision_recall_note": "Ultralytics reports precision and recall at the confidence threshold maximizing mean F1, not at the 0.001 collection threshold.",
    }
    output = Path(metrics.save_dir) / "evaluation.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("Saved report:", output)


if __name__ == "__main__":
    main()
