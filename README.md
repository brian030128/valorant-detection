# Valorant detection experiments

## Smooth head trajectories

The green **AIM 200x200** square shows the targeting region in both preview
panels. Detection still uses the native 400x400 crop. Only an `enemy_head`
whose bounding-box center lies in the smaller square is eligible; the nearest
head to the capture center wins. A two-pixel dead zone prevents tiny corrections.

```powershell
git submodule update --init --recursive
python tools/live_capture_detection.py --aim
python tools/live_capture_detection.py --aim --mouse --mouse-port COM6 --aim-scale 1
```

`--aim` alone previews generated movement without opening the serial port or
capturing the local cursor. With `--mouse`, it sends movement over streaming v3
firmware. Your movement forwards normally until an eligible head starts a
trajectory immediately from a single fresh detection, without a confirmation
delay. During that trajectory only movement is replaced; left/right button
presses, holds and releases continue forwarding. Manual movement resumes when
the trajectory completes. Detection changes do not interrupt or redirect an
active movement. Overridden manual motion
is discarded, never replayed afterward. `--mouse-scale` controls manual movement;
`--aim-scale` controls generated movement. With `--mouse-dry-run`, the local
cursor is still captured and recentered, but output is printed without serial
access. Generated paths never create button presses themselves.

Each trajectory randomly selects a **50–100 ms** movement duration
in one-millisecond increments. Use `--aim-min-ms` and `--aim-max-ms` to narrow
that range. The selected duration
and actual playback time are recorded in `runs/live_capture/status.json`, along
with the latest time/x/y trajectory. The orange line displays its shape.

Generated paths use the same `--mouse-hz` setting as manual cursor sampling:
250 Hz by default (one point every 4 ms). Paths have 13–25 movement intervals
plus their starting point, with a shorter final interval when needed to hit
the exact endpoint.
Previously, generated paths used 125 Hz. Fractional positions are retained
until cumulative HID-count rounding. Higher requested rates also increase path
density, but actual delivery is limited by serial/HID acknowledgements and
Windows scheduling; overdue points are coalesced, as with manual forwarding.

The default `--aim-generator smooth` uses a mathematical quintic easing function,
with no trajectory model loading or inference. It moves from the capture center
to the detected head center with zero continuous velocity and acceleration at
each endpoint. Each path gets a random sideways bend bounded by 3 pixels or
5% of the target distance, whichever is smaller. Forward progress is monotonic,
and the endpoint is exact before HID rounding. Timelines are cached at startup.
YOLO still performs head detection; only trajectory generation is model-free.

For comparison, `--aim-generator ai` restores the previous cached GRU-derived
curves; run `git -C mouse-generator lfs pull` first if its weights are missing.
That mode supports `--aim-checkpoint`. Both modes use the same movement duration,
sampling rate, target selection, mouse scaling, button forwarding and feedback
wait, so changing the generator isolates its contribution to latency.
The selected generator is recorded in `status.json`.

`--aim-scale` is HID counts per native capture pixel and must match receiving
game sensitivity. Exact pixel endpoints in the planned path do not guarantee
physical aim without that calibration. The 50–100 ms duration is the requested
movement duration; capture/inference latency and serial acknowledgement delays
are additional. Playback coalesces late samples without losing total movement.
Paths aim at the head position observed when they begin; moving targets require
subsequent fresh corrections. After the final HID report is acknowledged, the
next automatic correction waits `--aim-settle-ms` (default 20 ms) and requires a
frame received after that interval. Manual movement and button transitions
continue forwarding during the wait. No movements queue; frames received
during a trajectory or its settling interval cannot start the next one.
Detections older than 150 ms cannot start movement.
The 20 ms default favors quicker follow-up corrections and is not measured
capture latency. The first movement has no settling wait. Reducing this delay
can reintroduce corrections based on stale visual feedback.
Frame timestamps indicate receipt, not sensor exposure. Calibrate the interval
against movement-to-visible-response delay; this time gate cannot prove that
a frame reflects the previous movement if the actual delay is longer.
For example, append `--aim-settle-ms 150` to increase the wait, or use 0 to
disable the extra wait while still requiring a frame after acknowledgement.
`status.json` includes `feedback_timing`: configured wait, completion/frame
cutoff timestamps (monotonic), source-frame age at planning, and elapsed time
from the previous completion to the next start. These are software timings,
not a measurement of capture-card latency.
Once started, movement finishes even if the target disappears. Q/Escape,
closing the preview, or Ctrl+C still immediately stops the
session and closes the relay with STOP.

## Live mouse relay (Windows)

`tools/relay_mouse.py` samples the local cursor, recenters it on the primary
display, and forwards relative movement using the `mouse-spoofing` submodule's
`replay.Relay` utility and CRC-framed UART protocol. Connect this PC to the
board's UART bridge and the receiving PC to its native USB HID port. Follow the
[firmware and wiring guide](mouse-spoofing/firmware/README.md).

```powershell
git submodule update --init --recursive
python -m pip install "pyserial>=3.5,<4"
python mouse-spoofing/replay.py --list-ports
python tools/relay_mouse.py --port COM6 --probe
python tools/relay_mouse.py --dry-run
python tools/relay_mouse.py --port COM6 --counts-per-pixel 1
```

To combine HDMI screen capture, detection labels, and mouse forwarding:

```powershell
python tools/live_capture_detection.py --mouse
python tools/live_capture_detection.py --mouse --mouse-port COM6 --mouse-scale 1 --mouse-hz 250
python tools/live_capture_detection.py --mouse --mouse-dry-run
```

`--mouse` defaults to COM6 and runs cursor capture independently of inference.
The preview remains responsive while waiting for the receiving USB connection;
its mouse status changes to `drag` when streaming starts. The local cursor is
captured only after USB is ready. Active serial/HID errors stop the session;
movement is never replayed automatically after a failure.
Without it, the preview runs normally without mouse capture or serial access.
Q or Escape globally while `--mouse` is active, closing the preview, or reaching `--frames`
stops both features and restores the local cursor. Relay failures stop the
preview and report the error. `--mouse-dry-run` requires `--mouse` and allows
combined testing without a connected board. The same firmware/USB readiness
requirements below apply to live forwarding.

Q, Escape or Ctrl+C stops capture and restores the original local cursor position.
With streaming v3 firmware, left/right button states are forwarded directly:
press and hold a button, move to drag, then release. Button transitions are
preserved in order while movement within each state is coalesced. There is no
batch start delay. Idle heartbeats maintain holds; STOP or the firmware's
250 ms communication watchdog releases buttons. Q/Escape closes and releases.
The M2K-profile firmware source and backup/restore instructions are in
[`mouse-spoofing/firmware/m2k_stream`](mouse-spoofing/firmware/m2k_stream/README.md).

On legacy v1/v2 firmware, left/right clicks use 30 ms press/release pairs (button masks
1 and 2). Observed down edges are queued while serial is busy; holding a button
does not repeat clicks. The batch firmware requires buttons released at the end
of every batch, so sustained holds/dragging are unavailable in legacy mode.
Wheel is not forwarded in either mode. Input
is polled: a press and release entirely between samples can be missed. Local
clicks are not suppressed. Exit discards queued clicks and sends STOP to release
remote buttons. Dry-run also captures/recenters the cursor, but only prints
movement and actual held-button masks. Probe sends STOP and queries firmware without
moving the mouse. Live capture supports the v1, v2 and v3 UART profiles and requires
`USB=1`. Probe also works with `USB=0`, which is expected when native USB is
disconnected. Unknown profiles fail before cursor capture starts. The wrapper
uses the pinned submodule's `Relay` framing and request utilities for both
versions; its original standalone `replay.py` still expects v1.

The connected CH343 bridge on COM6 originally reported protocol v2 and a
Zaunkoenig M2K identity. The streaming build preserves its recovered USB
descriptors and reported identity. The wrapper uses conservative 127-count reports for v2, retaining
remaining displacement for subsequent reports, and observes its advertised
10 ms minimum cadence. v1 uses up to 32767 counts per report. The v2 command
format was checked against local v2 source and verified on the connected board
with signed movement preloads followed by STOP (no playback). A zero-motion
LOAD/E/RUN/DONE transaction was also verified with `USB=1`. On 2026-10-12,
streaming v3 was built and flashed to app0 after saving a full 16 MiB backup.
The compiled device/configuration/report descriptors match the original
image byte-for-byte, and the post-flash identity reply is unchanged. The board
confirmed v3 and streaming capabilities, with `USB=0` while native USB was
disconnected. After native USB was connected, the board reported `USB=1` and
completed 30 zero-motion streaming reports. Median serial-to-HID-completion
round trip was 4.00 ms (maximum 4.14 ms), versus 27.01 ms for 10 zero-motion
batch reports in the same firmware. This excludes capture-card/display delay
and does not itself verify a visible drag gesture.

Movement is sampled at up to 250 Hz by default; actual timing depends on Windows
scheduling. Capture temporarily requests 1 ms Windows timer resolution: a
measured 4 ms wait dropped from about 15.5 ms to 4.4 ms. The setting is restored
on exit. UART transmission runs separately. Legacy mode coalesces pending movement
into one-report batches, retaining any excess over the report limit. Firmware
adds a start delay per batch (10 ms in the pinned v1 source, 20 ms in the local
v2 source), plus serial round trips. Legacy commands are written together with
all acknowledgements still checked. Streaming v3 instead sends one immediate
report with acknowledgement and supports the full 16-bit axis range.
This is a basic desktop relay, not raw mouse
capture: local acceleration applies, fast motion can hit screen edges, and
movement between reading and recentering can be lost. Receiving-PC pointer
settings also affect displacement. Fractional scaling is retained across
batches; excessive backlog or serial errors stop the relay without retrying
possibly delivered movement. Exit discards unsent movement and sends STOP.

Synthetic native 400x400 crops. Version 6 uses enemy torso and enemy head labels;
older versions use enemy, teammate and head labels. Code only:
images, character assets, masks, checkpoints and generated results are excluded
from Git. The private dataset is
[edgeai-lab/valorant-detection-400](https://huggingface.co/datasets/edgeai-lab/valorant-detection-400).

## Enemy anatomy regeneration (version 6)

The v6 pipeline regenerates 30,000 train, 1,000 validation and 1,000 test images.
Classes are `0: enemy_body` (chest, abdomen and pelvis) and `1: enemy_head`.
No teammates are rendered. Hair, arms and legs remain visible occluders but are
excluded from target masks. Labels use visible anatomy estimated from skin
weights, material names and envelopes, not official game collision hitboxes.
Camera regions are partitioned by split; map assets and target regions can be shared.
Bounding boxes can enclose excluded pixels; inspect masks for the exact surfaces.

```powershell
python tools/prepare_synthetic_assets.py --anatomy
python tools/rebuild_anatomy_dataset.py --publish
```

The character review is rendered with `environment/anatomy_review.tscn -- --anatomy`
and assembled by `tools/build_anatomy_review.py`. It shows all 29 characters from
three angles, with boxes and exact visible masks. On H100, use the two-class
handoff: `python tools/train_enemy_anatomy.py --revision <dataset-commit>`.
Old three-class metrics and class IDs are incompatible with v6.

## Real-map regeneration (version 5, historical)

The version-5 pipeline replaces all 30,000 training images with native 400x400
renders from 11 user-supplied Blender maps: Abyss, Ascent, Bind, Breeze,
Fracture, Haven, Icebox, Lotus, Pearl, Split, and Sunset. The original 1,000
validation and 1,000 test images remain byte-for-byte unchanged. Prior datasets
are retained locally and in Hugging Face revision history.

Godot renders original map geometry and full-resolution packed textures, normal
maps, and material vertex colors with mipmapped anisotropic filtering and 4x
MSAA for images. ID masks disable MSAA to preserve exact labels. Complex layered
Blender materials are approximated; these are synthetic renders, not captures
from Valorant. Source textures are often 512x512. Camera positions, distances,
viewing directions, poses, lighting, and six crosshair styles vary. Each image
contains at most one player. Labels cover visible pixels after geometry and
opaque crosshair occlusion; fully hidden parts have no label.

To generate and audit supplied maps locally:

```powershell
python tools/generate_real_maps.py
python tools/package_real_maps_dataset.py
python tools/dataset_progress.py --help
```

Generation resumes completed images and logs each map in the output's `logs`
folder. `generation_status.json` records the current phase and map;
`diversity.json` records sampled regions and camera viewpoints per map.
Two independent Godot workers render different maps by default, using 500-image
batches and persistent image/mask render targets. Use `--workers 3` for three
concurrent maps, or `--workers 1` to reduce memory usage. Failed batches resume completed frames; retries stop after three
consecutive failures with no progress, or ten attempts for a batch.
Downloaded assets and generated datasets are excluded from Git.

To fine-tune on version 5 after downloading it from the private dataset:

```bash
python tools/train_h100.py --experiment targeted --epochs 20 --batch 64 --workers 8
```

The packaged warm start is the trained checkpoint at
`1f23a9a0575e650360427df0bf5bae03a5384729`. Version 5 does not contain the original
8,000 training images, so baseline comparisons require a pinned older revision.
The preserved procedural validation/test sets do not measure performance on
unseen real maps or real gameplay. See `provenance.json` and the labeled map
previews in `scene_catalog` for the exact dataset contents and limitations.

## Previous scene expansion (version 4)

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
python tools/train_h100.py --revision 0f32d41612bb5bf13d5b5828b7985b98beb400f7 --experiment both --epochs 20 --batch 64 --workers 8
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
