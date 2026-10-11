# Valorant detection experiments

Synthetic native 400x400 crops with enemy, teammate and head labels. Code only:
images, character assets, masks, checkpoints and generated results are excluded
from Git. The private dataset is
[edgeai-lab/valorant-detection-400](https://huggingface.co/datasets/edgeai-lab/valorant-detection-400).

## Scene expansion (version 3)

**20,000 native images: 18,000 train / 1,000 validation / 1,000 test.**
Version 3 preserves all 12,000 version-2 images and adds 8,000 training images
across eight new scene families, 1,000 images and 20 layouts per family:

- Market streets with stalls, awnings, windows and colorful facades.
- Server rooms with equipment racks and indicator lights.
- Aircraft hangars with structural beams and simplified aircraft.
- Wooded paths with trees, canopy shadows and rocks.
- Canal walks with water, railings and buildings.
- Parking garages with pillars, parked vehicles and lane markings.
- Stone ruins with columns, broken walls and rubble.
- Ice tunnels with irregular walls and ice formations.

The additions contain 2,000 tiny-head samples (shortest visible-box side 2-7 px),
2,000 small-head samples (under 16 px), 2,000 partial-cover samples verified to
retain 15-90% of the uncovered head pixels, and 2,000 empty background scenes.
Enemy and teammate views vary. The new empty scenes are not model-mined.

Version 2 remains in dataset history at revision
`72bd3da0041dcba7ae43399abb49f193ff89f668`. It added 2,000 images to the original
10,000: 500 tiny heads, 500 small heads, 500 partial occlusions and 500 background
negatives ranked from 2,500 candidates. That candidate pool had zero head false
positives at confidence 0.52 (maximum confidence 0.289).

No player stacking. Approved purple remains #B04DBE, strength 2.2, power 2.5,
upper bias 0.6. Labels bound visible pixels; hidden parts are omitted. Native
400x400 camera crops are padded to 416x416 for training without resizing.

Original validation and test images, masks, labels and metadata remain
byte-for-byte unchanged. All new images are training-only. The complete training
set now contains 20 scene families. The earlier 4,000-image map benchmark stays
separate but is a known-family regression set after version 2. These existing
evaluation sets do not establish robustness to wholly unseen scene families or
real gameplay. A fresh independent evaluation is needed for that claim.

## Compare on an H100

Use CUDA-enabled PyTorch, authenticate to the private dataset, then run:

```bash
git clone https://github.com/brian030128/valorant-detection.git
cd valorant-detection
pip install -r requirements.txt
hf auth login
python tools/train_h100.py --experiment both --epochs 20 --batch 64 --workers 8
```

Both arms start independently from the identical trained checkpoint from
`edgeai-lab/valorant-center400-yolo11s` at revision
`116b979aa0913d1bfe4ef3714a52434721dbebf5`, reset their optimizers, and use the same
seed, learning rate and augmentation settings. At batch 64, the baseline trains
on the original 8,000 images for 45 epochs (5,625 batches); the targeted arm uses
18,000 images for 20 epochs (5,640 batches). Early stopping is disabled. This
approximately matches batch updates, not exact compute. Square-crop training uses
shuffled batches to mix the original and added examples. It is a single-seed
initial experiment, not proof that more data is the bottleneck.

The launcher verifies SHA-256 checksums and uses dataset-content-specific local
paths so revisions cannot silently overwrite one another. `--revision HASH` pins
a dataset commit. `--prepare-only` downloads, verifies and pads without training.
`HF_TOKEN` may be supplied through a secret manager instead of interactive login.
Use `--experiment baseline` or `--experiment targeted` to run an arm separately;
`--resume` resumes that arm's saved settings.

By default the comparison evaluates **validation only**, including class-specific
precision/recall and error galleries. Thresholds maximize the smaller of precision
and recall per class at IoU 0.50. Results go to
`runs/analysis/center400_<data-hash>_comparison.json`, with separate model runs and
galleries. Review head misses by native size and false positives, as well as body
class metrics. The target is precision AND recall >=99% for EACH class.

After selecting a checkpoint using validation, evaluate it explicitly:

```bash
python tools/evaluate_center_goal.py --run runs/train/center400_HASH_targeted --dataset datasets/center416_HASH --output runs/analysis/center400_HASH_targeted_final
```

Replace HASH with the identifier printed by the launcher. The evaluator freezes
thresholds on validation before testing. `--evaluate-test` also opts the launcher
into test evaluation, but should not be used to tune or choose between arms.
Descriptive Wilson intervals do not account for correlation among scene frames.
The original test has only 80 teammates. Synthetic scores do not establish real
Valorant performance or a statistically certified 99% success rate.

## Reproduce the local additions

Rendering requires Godot 4.7.2 and the existing head-weighted character assets.
With the audited version-2 dataset under `datasets/valorant_detection_400_v2`, run:

```powershell
$sceneOutput = Join-Path $PWD "datasets/valorant_scenes_8000"
.\tools\godot\Godot_v4.7.2-stable_win64.exe --path environment res://scene_expansion_dataset.tscn -- --start=200000 --count=8000 "--output=$sceneOutput"
python tools/merge_scene_expansion.py
python tools/publish_center_dataset.py
```

Prefer an absolute `--output` path when launching Godot outside this repository.
The merger checks all images, masks, labels, duplicates and scene splits, then
verifies held-out file hashes against version 2. It writes a new version-3 folder;
the parent dataset and map benchmark are preserved. `provenance.json` records
counts, seeds through per-image metadata, generator hash and parent history.

The original version-2 builders remain available as
`environment/targeted_dataset.tscn` and `tools/build_targeted_dataset.py`.

`tools/publish_center_dataset.py` packages this version and refuses to upload to
a public dataset. Archives contain images, labels, masks and metadata; the metadata
archive contains audit, annotations and provenance. The manifest records sizes
and checksums. Warm-start provenance is in `weights/warmstart_info.json`.

Character assets were obtained from Kingdom Archives. Underlying game assets and
trademarks belong to their respective owners; this repository and private dataset
do not grant additional rights to those assets. Generation helpers are Windows
specific; training, padding, download and evaluation support Linux.
