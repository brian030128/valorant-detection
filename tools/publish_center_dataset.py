"""Package audited native crops and warm-start weights; upload only to a private HF dataset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/valorant_center400_10k'
PACKAGE=ROOT/'exports/hf_center400'


def token():
    value=os.environ.get('HF_TOKEN') or os.environ.get('HF-TOKEN')
    if not value and os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            for name in ['HF_TOKEN','HF-TOKEN']:
                try:value=winreg.QueryValueEx(key,name)[0];break
                except FileNotFoundError:pass
    return value


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def package():
    audit=json.loads((DATA/'audit.json').read_text())
    state=json.loads((DATA/'generation_status.json').read_text())
    assert state['phase']=='complete' and audit['images']==10000
    (PACKAGE/'archives').mkdir(parents=True,exist_ok=True)
    (PACKAGE/'weights').mkdir(exist_ok=True)
    (PACKAGE/'tools').mkdir(exist_ok=True)
    for split in ['train','val','test']:
        path=PACKAGE/'archives'/f'{split}.zip'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for directory in ['images','labels','masks','metadata']:
                for source in sorted((DATA/directory/split).iterdir()):
                    archive.write(source,source.relative_to(DATA).as_posix())
        print(f'PACKAGED {split}: {path.stat().st_size/1e6:.1f} MB',flush=True)
    with zipfile.ZipFile(PACKAGE/'archives/dataset_metadata.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['audit.json','provenance.json','annotations.jsonl','README.txt']:
            archive.write(DATA/name,name)
        archive.writestr('data.yaml','path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: enemy\n  1: teammate\n  2: head\n')
    import torch
    from ultralytics.utils.torch_utils import strip_optimizer
    source=ROOT/'runs/train/yolo11s_center400_416/weights/best.pt'
    checkpoint=torch.load(source,map_location='cpu',weights_only=False)
    info=dict(source_epoch=int(checkpoint['epoch'])+1,source_sha256=sha256(source),
              validation_metrics=checkpoint.get('train_metrics'),purpose='Warm start for continued fine-tuning; not a completed 99% evaluation.',
              source='YOLO11s full-screen synthetic training followed by center-crop fine-tuning.')
    strip_optimizer(str(source),str(PACKAGE/'weights/center400_warmstart.pt'))
    (PACKAGE/'weights/warmstart_info.json').write_text(json.dumps(info,indent=2))
    for name in ['train_h100.py','train_synthetic_yolo.py','prepare_center_training.py',
                 'evaluate_center_goal.py','analyze_detection_failures.py','training_progress.py','dataset_progress.py']:
        shutil.copy2(ROOT/'tools'/name,PACKAGE/'tools'/name)
    shutil.copy2(ROOT/'requirements.txt',PACKAGE/'requirements.txt')
    for name in ['preview_scenes.jpg','preview_heads.jpg']:shutil.copy2(DATA/name,PACKAGE/name)
    card='''---
pretty_name: Valorant native center-crop detection
task_categories:
- object-detection
tags:
- yolo
- synthetic
- valorant
size_categories:
- 10K<n<100K
---

# Valorant 400x400 center-crop dataset (private)

10,000 native-resolution images with YOLO labels and depth-tested instance/head
masks. Classes: `0 enemy`, `1 teammate`, `2 head` (either team).

| Split | Images | Enemy boxes | Teammate boxes | Head boxes | Empty images |
|---|---:|---:|---:|---:|---:|
| train | 8000 | 6800 | 800 | 7592 | 400 |
| val | 1000 | 820 | 120 | 940 | 60 |
| test | 1000 | 880 | 80 | 960 | 40 |

All 29 characters and eight procedural scene families appear in each split.
Scene groups are disjoint across splits. One player per positive crop; no stacked
players. Each intended positive has at least 200 visible body pixels. Most also
require at least 16 visible head pixels. The sampling favors visibility and is
not representative of natural gameplay. Completely hidden parts are not labeled;
partially visible body/head labels bound their visible pixels only.

The 400x400 viewport is the central subfrustum of a 1920x1080 camera with vertical
FOV 70.53 degrees, equivalent to rectangle `(760,340)-(1160,740)`. No resampling is
used. A pilot mask matched the corresponding full-frame crop pixel-for-pixel.

## Train remotely

Code-only repository: https://github.com/brian030128/valorant-detection

```bash
git clone https://github.com/brian030128/valorant-detection.git
cd valorant-detection
pip install -r requirements.txt
hf auth login
python tools/train_h100.py --batch 64 --epochs 30 --workers 8
```

Use a CUDA-enabled PyTorch installation suitable for your H100. `HF_TOKEN` may
instead be injected through your platform's secret manager. The launcher verifies
archive checksums, extracts the dataset, pads each image by eight pixels on each
side to 416x416 without resampling, and fine-tunes the bundled intermediate
YOLO11s weights. `--prepare-only` stops after data preparation. `--revision` accepts
an immutable dataset commit hash.

The warm-start weights are an intermediate local checkpoint. They are not a
completed 99% test result; see `weights/warmstart_info.json` for validation metrics.
The final evaluation freezes per-class confidence thresholds using validation,
then tests whether both precision and recall reach 99% for every class at IoU .50.
Results and data recommendations are saved to `runs/analysis/center400/assessment.txt`.
Small class sample counts and correlated frames limit statistical certainty.
Real-game performance and multi-player crops require independent evaluation.

## Files

- `archives/train.zip`, `val.zip`, `test.zip`: images, labels, masks, metadata.
- `archives/dataset_metadata.zip`: complete audit, annotations, provenance, config.
- `manifest.json`: byte sizes and SHA-256 checksums.
- `weights/center400_warmstart.pt`: optimizer-stripped transfer-learning weights.
- `preview_scenes.jpg`, `preview_heads.jpg`: labeled previews.
- `tools/`, `requirements.txt`: a copy of the portable training utilities.

Character assets were obtained from Kingdom Archives and rendered in Godot.
Underlying game assets and trademarks belong to their respective owners. No
additional license to those assets is granted by this private dataset. The purple
highlight is an approximation using #B04DBE and the approved rendering parameters.
'''
    (PACKAGE/'README.md').write_text(card,encoding='utf-8')
    manifest=dict(dataset='valorant_center400_10k',images=10000,resolution=[400,400],class_names=audit['class_names'],
                  created_at=time.time(),files={})
    for p in sorted(PACKAGE.rglob('*')):
        if p.is_file() and p.name!='manifest.json' and '.cache' not in p.parts:
            manifest['files'][p.relative_to(PACKAGE).as_posix()]=dict(bytes=p.stat().st_size,sha256=sha256(p))
    (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('PACKAGE_READY',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='edgeai-lab/valorant-center400-10k')
    parser.add_argument('--package-only',action='store_true')
    parser.add_argument('--upload-only',action='store_true')
    args=parser.parse_args()
    if not args.upload_only:package()
    if args.package_only:return
    from huggingface_hub import HfApi
    api=HfApi(token=token())
    api.create_repo(args.repo,repo_type='dataset',private=True,exist_ok=True)
    assert api.dataset_info(args.repo).private,'Refusing to upload private data to a public repository.'
    result=api.upload_folder(repo_id=args.repo,repo_type='dataset',folder_path=PACKAGE,
                             ignore_patterns=['.cache/**'],commit_message='Add audited 10k center-crop dataset and H100 training handoff')
    info=api.dataset_info(args.repo,files_metadata=True)
    assert info.private
    actual={s.rfilename:s for s in info.siblings}
    manifest=json.loads((PACKAGE/'manifest.json').read_text())
    for relative,entry in manifest['files'].items():
        assert relative in actual,relative
        sibling=actual[relative]
        assert sibling.size==entry['bytes'],relative
        if sibling.lfs:assert sibling.lfs.sha256==entry['sha256'],relative
    report=dict(repo=args.repo,private=info.private,commit=info.sha,files=len(actual),url=f'https://huggingface.co/datasets/{args.repo}',
                verification='All listed sizes checked; all LFS SHA-256 hashes matched local package.')
    (ROOT/'exports/hf_upload_result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
