# Valorant detection experiments

Synthetic-data generation and YOLO detection for **enemy**, **teammate**, and
**head**. This repository contains code only. Images, character assets, engine
binaries, masks, checkpoints, logs, and generated results are excluded from Git.

The private dataset is [edgeai-lab/valorant-center400-10k](https://huggingface.co/datasets/edgeai-lab/valorant-center400-10k).
Authentication with permission to read that dataset is required.

## Train on an H100

Use a Linux environment with a CUDA-enabled PyTorch installation that supports
the H100. Install dependencies, authenticate, and launch:

```bash
git clone https://github.com/brian030128/valorant-detection.git
cd valorant-detection
pip install -r requirements.txt
hf auth login
python tools/train_h100.py --batch 64 --epochs 30 --workers 8
```

Alternatively, inject `HF_TOKEN` through your remote platform's secret manager.
Do not place credentials in source files or Git. `HF-TOKEN` is accepted as an
alias by the download script. No token is included in this repository or dataset.

The launcher verifies archive SHA-256 checksums, extracts the native 400×400
images, and pads them by eight pixels per side to 416×416 **without resampling**.
It fine-tunes the included YOLO11s warm-start weights using a lower learning rate.
The included weights are an intermediate checkpoint, not a model certified to
meet 99% precision or recall. Use `--revision COMMIT_HASH` for a pinned dataset
version. `--prepare-only` downloads/prepares without training; `--resume`
continues this remote run's `last.pt` using its saved training settings.

```bash
python tools/training_progress.py runs/train/yolo11s_center400_416
```

The best checkpoint is selected on validation. The evaluation script selects
per-class confidence thresholds on validation, freezes them, then measures
precision and recall on test at class-aware IoU ≥ 0.50. The target is **both
precision and recall ≥99% for each class**, not mAP50 alone. Outputs:

- `runs/train/yolo11s_center400_416/weights/best.pt`
- `runs/analysis/center400/assessment.txt` and `assessment.json`
- `runs/analysis/center400/frozen_thresholds.json`
- `runs/analysis/center400/val/index.html` and `test/index.html`

Assessment reports include counts, descriptive confidence intervals, validation
failure categories, and recommendations for additional training or data.
Gallery overlays use fixed confidence 0.50; the assessment uses the frozen
per-class thresholds. Synthetic performance does not establish real-game
performance. Test has only 80 teammate objects, so even a perfect score does not
substantiate a 99% lower confidence bound for that class. Scene-correlated frames
also limit statistical independence.

## Dataset

10,000 native 400×400 images: 8,000 train / 1,000 validation / 1,000 test.
Scene groups are disjoint across splits. There are 8,500 enemy images, 1,000
teammate images, and 500 empty negatives, with 29 characters and eight procedural
scene families. A positive crop contains one visible player. Masks generate
tight labels for visible portions; fully hidden heads are omitted. The crop is
the central perspective subfrustum of a 1920×1080 camera, with no pixel-scale
change. Purple highlight parameters are preserved in the metadata.

Sampling deliberately favors visible targets and almost always visible heads.
It is not representative of natural gameplay, heavily occluded targets, or
multiple players within the center crop. More random images are not automatically
the right next step; inspect validation failures and evaluate real recordings.

## Local rendering

The render lab uses Godot 4.7.2 and character-select assets downloaded from
Kingdom Archives. Engine and third-party assets are not distributed in Git.
Their underlying rights remain with their respective owners; this repository
does not grant rights to the game assets.

Place Godot executables under `tools/godot/`, obtain the character assets using
`tools/download_character_assets.py`, and prepare head-weighted meshes with
`tools/prepare_synthetic_assets.py`. See `environment/README.txt` for the render
lab. The project uses the Compatibility renderer.

```powershell
python tools/generate_center_dataset.py
python tools/dataset_progress.py datasets/valorant_center400_10k --log datasets/valorant_center400_10k/finalization.log
```

Generation and launch helpers are Windows-specific. Training, padding, download,
and evaluation scripts support Linux. The older full-screen comparison scripts
are retained as local experiment utilities.
