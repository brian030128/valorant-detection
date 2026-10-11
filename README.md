# Valorant detection experiments

Synthetic native 400x400 crops with enemy, teammate and head labels. Code only:
images, character assets, masks, checkpoints and generated results are excluded
from Git. The private dataset is
[edgeai-lab/valorant-detection-400](https://huggingface.co/datasets/edgeai-lab/valorant-detection-400).

## Scene expansion (version 4)

**32,000 native images: 30,000 train / 1,000 validation / 1,000 test.**
Version 4 preserves all 20,000 version-3 images and adds 12,000 training images
across **120 scene designs: 20 structural themes ? six spatial layouts**.
Each design has two independently seeded layouts and 100 images (240 new seeded
layouts total). This is 120 combinations of geometry and layout, not 120
independently handcrafted map families.

Themes: scaffold canyons, lattice bridges, pipeworks, refinery tanks, steel
foundries, loading docks, cable tunnels, pallet depots, transit concourses,
cooling plants, antenna yards, brick quarters, concrete bunkers, solar arrays,
quarry terraces, timber sawmills, botanical courts, shop arcades, maintenance
bays and flood barriers. Layouts: parallel lanes, wide courts, staggered islands,
diagonal bays, stepped setbacks and cross galleries. Geometry, placement,
lighting, camera angles, characters and distances vary.

The additions contain 2,400 examples each of tiny heads (2?7 px shortest visible
box side), small heads (2?15 px), normal-scale players, partial cover (15?90% of
uncovered head pixels), and empty backgrounds. Positive examples contain one
player; 75% enemy and 25% teammate. Backgrounds are procedural, not model-mined.
The labeled [scene catalog](scene_catalog/index.html) covers every new design;
its samples are ground truth, not predictions.

No player stacking. Approved purple remains #B04DBE, strength 2.2, power 2.5,
upper bias 0.6. Labels bound visible pixels; hidden parts are omitted. Native
400x400 camera crops are padded to 416x416 for training without resizing.

Original validation and test images, masks, labels and metadata remain
byte-for-byte unchanged. All additions are training-only. Both 4,000-image map
benchmarks remain separate. Construction/scaffolding failures informed this
expansion, so the latest benchmark is now a regression set with known styles,
not a blind unseen-family test. Existing evaluation does not establish real
gameplay performance or robustness to wholly unseen styles.

Version 3 (20,000 images) remains in dataset history at
`f74434b3eae05722fe98bd12f59e3f61070461da`; version 2 (12,000) at
`72bd3da0041dcba7ae43399abb49f193ff89f668`. The parent history and generator
hashes are recorded in provenance.json. The full dataset includes the previous
20 scene families plus the 120 new theme/layout designs.

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
`8eac3628757f614b8a5e5bb94bd2b3b4c65be69a`, reset their optimizers, and use the same
seed, learning rate and augmentation settings. At batch 64, the baseline trains
on the original 8,000 images for 75 epochs (9,375 batches); the targeted arm uses
30,000 images for 20 epochs (9,380 batches). Early stopping is disabled. This
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
With the audited version-3 dataset under `datasets/valorant_detection_400_v3`, run:

```powershell
$sceneOutput = Join-Path $PWD "datasets/valorant_120scenes_12000"
.\tools\godot\Godot_v4.7.2-stable_win64.exe --path environment res://hundred_scenes_dataset.tscn -- --start=600000 --count=12000 "--output=$sceneOutput"
python tools/merge_hundred_scenes.py
python tools/publish_center_dataset.py
```

Prefer an absolute `--output` path when launching Godot outside this repository.
The merger checks all images, masks, labels, duplicates and scene splits, then
verifies held-out file hashes against version 3. It writes a new version-4 folder;
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


## Reproduce the version-3 unseen-scene test

`environment/unseen_maps_dataset.tscn` renders a separate 4,000-image test-only
benchmark: greenhouse, power substation, museum gallery and construction site.
These four families are absent from version-3 training. Version 4 incorporates
related structural styles, so subsequent use is regression testing. It replays the original
1,000 held-out cameras and character poses in each family, using 20 new layouts
per family. This isolates changes caused by scenery; the 4,000 frames are not
independent character/pose samples. Do not add this benchmark to training.

```powershell
$testOutput = Join-Path $PWD "datasets/valorant_unseen_maps_4000"
.\tools\godot\Godot_v4.7.2-stable_win64.exe --path environment res://unseen_maps_dataset.tscn -- --count=1000 "--output=$testOutput"
python tools/finalize_synthetic_dataset.py datasets/valorant_unseen_maps_4000 --expected 4000
python tools/evaluate_map_shift.py --model models/valorant-center400-yolo11s-8eac3628757f --dataset datasets/valorant_unseen_maps_4000 --training-dataset datasets/valorant_detection_400_v3 --output runs/analysis/unseen_maps_8eac3628757f
```

The model directory above contains the checkpoint and configuration downloaded
from `edgeai-lab/valorant-center400-yolo11s` at immutable revision
`8eac3628757f614b8a5e5bb94bd2b3b4c65be69a`. Evaluation uses its saved thresholds
(enemy 0.82, teammate 0.53, head 0.53), 416-pixel padded input, NMS IoU 0.70,
and class-aware matching at IoU 0.50. No new-map threshold tuning is performed.

The evaluator verifies replay metadata, checks that scene families are absent
from training, reproduces the original test as a control, and reports all-frame
results plus paired subsets where both body and head masks retain IoU >=0.95
against the original. Reports include head recall by size and diagnostic labeled
images in `index.html`. Best/worst example selection does not alter metrics.


## Paired texture and crosshair stress test

`environment/texture_test_dataset.tscn` renders four test-only procedural scenes:
atrium, ceramic passage, weathered service yard and painted arcade. Each replays
1,000 original held-out poses across 20 layout seeds. Materials use world-space
concrete, brick, tile, wood grain, rust, hazard stripes, graffiti and mosaic
patterns. These are procedural stress textures, not photographic assets.

Render twice to separate folders, with and without `--flat`; the generator keeps
geometry, camera, character and lighting identical. Audit both before evaluating:

```powershell
$textureOutput = Join-Path $PWD "datasets/valorant_texture_test_4000"
$flatOutput = Join-Path $PWD "datasets/valorant_texture_flat_4000"
.\tools\godot\Godot_v4.7.2-stable_win64.exe --path environment res://texture_test_dataset.tscn -- --count=1000 "--output=$textureOutput"
.\tools\godot\Godot_v4.7.2-stable_win64.exe --path environment res://texture_test_dataset.tscn -- --count=1000 --flat "--output=$flatOutput"
python tools/finalize_synthetic_dataset.py $textureOutput --expected 4000
python tools/finalize_synthetic_dataset.py $flatOutput --expected 4000
python tools/evaluate_texture_crosshairs.py --textured $textureOutput --flat $flatOutput --model models/valorant-center400-yolo11s-1f23a9a0575e --output runs/analysis/texture_crosshairs_1f23a9a0575e
```

The evaluator verifies all 4,000 paired masks and replay metadata are identical.
It uses the model's saved thresholds, native 400px images padded to 416, and
class-aware IoU 0.50 matching. It overlays five opaque synthetic center HUDs:
a 3px green dot, a 13px thin white cross, an open cyan cross, a larger purple
cross, and an outlined white cross, plus a no-HUD control. Pixels are native
screen pixels, without image resizing. Labels exclude opaque HUD pixels;
fully hidden heads are omitted. Reports also retain scores against pre-HUD
labels and head-overlap subsets with matched no-HUD controls, so label policy
changes are visible. Only diagnostic examples are selected for the gallery;
metrics include all frames. All these images remain test-only and excluded
from the published training dataset. Source poses and layouts are correlated.


Repeat the evaluator with `--hud-source flat` and a different `--output` folder
to isolate crosshair effects from texture failures. The complete factorial test
is 4,000 paired scene/pose samples ? two material conditions ? six HUD conditions
(48,000 inference inputs, derived from 8,000 renders). Use fresh output folders
when changing evaluator code; prediction caches deliberately reject different
implementation hashes.
