# Valorant detection experiments

Synthetic native 400x400 crops with enemy, teammate and head labels. Code only:
images, character assets, masks, checkpoints and generated results are excluded
from Git. The private dataset is
[edgeai-lab/valorant-detection-400](https://huggingface.co/datasets/edgeai-lab/valorant-detection-400).

## Targeted expansion

Version 2 contains **12,000 images: 10,000 train / 1,000 validation / 1,000 test**.
It keeps all original 10,000 images and adds these training-only examples:

- 500 distant heads with a visible box shorter side of 2-7 pixels.
- 500 additional small heads with a shorter side below 16 pixels.
- 500 partial occlusions, verified to retain 15-90% of the head pixels visible
  before placing the foreground cover.
- 500 empty scenes selected from 2,500 candidates by the current model's maximum
  head confidence. Candidates below the detection threshold can also be selected;
  the provenance reports how many actually caused false positives.

The 2,500 background candidates produced zero head detections at the frozen
0.52 threshold (maximum confidence 0.289). These negatives add background
coverage; whether they reduce false heads remains an experimental question.

New positives include enemies and teammates with varied viewpoints. No player
stacking. Approved purple remains #B04DBE, strength 2.2, power 2.5, upper bias 0.6.
Labels bound visible pixels; hidden parts are omitted. Resolution is preserved:
400x400 is a central camera subfrustum, then padded to 416x416 without resizing.

Original validation and test images, masks, labels and metadata are byte-for-byte
unchanged. New images use independent seeds, poses and layouts in cargo yard,
stone plaza, transit tunnel and neon industrial scenes. The earlier 4,000-image
map benchmark remains separate, but these are now known training map families;
it becomes a regression set, not an unseen-family generalization test. A fresh
map-family holdout and real gameplay evaluation are still needed.

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
on the original 8,000 images for 25 epochs (3,125 batches); the targeted arm uses
10,000 images for 20 epochs (3,140 batches). Early stopping is disabled. This
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
Run `environment/targeted_dataset.tscn` with `--start=100000 --count=2000` into
`datasets/valorant_targeted_2000`, then with `--start=102000 --count=8000
--negative-only` into `datasets/valorant_negative_candidates`. The second command
renders only every fourth index, producing 2,000 additional background candidates.
Then run `python tools/build_targeted_dataset.py` to mine and audit the merged
version. It verifies that held-out files are unchanged. The original dataset and
map benchmark are never modified. See `provenance.json` inside the metadata archive
for exact selections and checks.

`tools/publish_center_dataset.py` packages this version and refuses to upload to
a public dataset. Archives contain images, labels, masks and metadata; the metadata
archive contains audit, annotations and provenance. The manifest records sizes
and checksums. Warm-start provenance is in `weights/warmstart_info.json`.

Character assets were obtained from Kingdom Archives. Underlying game assets and
trademarks belong to their respective owners; this repository and private dataset
do not grant additional rights to those assets. Generation helpers are Windows
specific; training, padding, download and evaluation support Linux.
