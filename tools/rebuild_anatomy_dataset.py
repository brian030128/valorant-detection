"""Render all 32k images with two-class anatomy labels, audit, then publish privately."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');args=p.parse_args()
    output=ROOT/'datasets/valorant_detection_400_v6';output.mkdir(parents=True,exist_ok=True)
    status=output/'generation_status.json'
    def state(phase,**extra):
        status.write_text(json.dumps(dict(phase=phase,target=32000,updated_at=time.time(),**extra),indent=2))
    def run(script,*arguments):
        subprocess.run([sys.executable,'-u',str(ROOT/'tools'/script),*map(str,arguments)],cwd=ROOT,check=True)
    try:
        for split,count,start in [('val',1000,6000),('test',1000,7000),('train',30000,0)]:
            renders=ROOT/f'datasets/valorant_anatomy_{split}'
            state('rendering',split=split,active_dataset=str(renders))
            run('generate_real_maps.py','--anatomy','--split',split,'--start',start,'--total-images',count,
                '--workers',3,'--output',renders)
            for kind in ['images','masks','metadata']:
                shutil.copytree(renders/kind/split,output/kind/split,dirs_exist_ok=True)
        state('auditing')
        run('finalize_anatomy_dataset.py',output,'--expected',32000)
        metas=[json.loads(path.read_text()) for path in output.glob('metadata/*/*.json')]
        regions=defaultdict(set)
        for m in metas:regions[m['split']].add((m['scene_family'],m['spatial_region']))
        for a,r in regions.items():
            for b,s in regions.items():
                if a!=b:assert not r&s
        assert len({a['character'] for m in metas for a in m['actors']})==29
        assert all(a['role']=='enemy' for m in metas for a in m['actors'])
        assert len({m['crosshair']['style'] for m in metas})==6
        provenance=dict(parent_hf_revision='6563471bb7a35b6ec553f76597e61730118dca05',all_images_regenerated=True,
                        source_maps=json.loads((ROOT/'assets/source/valorant_maps/manifest.json').read_text()),
                        label_policy='enemy-anatomy-v1',map_counts=dict(Counter(m['scene_family'] for m in metas)),
                        region_counts={s:len(r) for s,r in regions.items()},cross_split_camera_region_overlap=0,
                        limitations='All splits share the same map assets. Camera regions are disjoint; target positions may overlap. Skin/material-based anatomy masks are approximations, not verified game hitboxes.')
        (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
        (output/'README.txt').write_text('''# Valorant detection 400 — enemy torso and head (v6)

32,000 newly rendered native 400x400 images: 30,000 train, 1,000 validation, 1,000 test. Eleven supplied map assets, 29 characters, six crosshair styles, varied poses, distances and camera regions. No teammates appear in the scenes; empty backgrounds are included.

Class IDs: 0 = enemy_body (visible chest, abdomen and pelvis); 1 = enemy_head (visible head excluding identified hair materials/bones). Arms, legs, hair and excluded accessories remain visible occluders but are not target masks. Fully hidden parts receive no label. A bounding rectangle can enclose excluded pixels; use the included masks to inspect exact target surfaces.

These labels approximate visible anatomy using skin weights, material names and geometric envelopes. They are not official game hitboxes. Shared-material geometry may not permit perfect hair/accessory separation. Review the 29-character gallery before training. Train/validation/test camera regions are disjoint, but all splits use the same map assets and can share target regions. This is not a real-game accuracy benchmark. Prior three-class metrics are not comparable.

## Training on H100

Install requirements.txt and CUDA-enabled PyTorch. Set HF_TOKEN in the environment. Download the tools folder from this dataset (or use the current code repository), then run:

    python tools/train_enemy_anatomy.py --revision <this-dataset-commit> --epochs 40 --batch 64

The script pads images to 416 without rescaling, transfers compatible pretrained features and rebuilds the two-class predictor. It evaluates validation by default. Use --test only after selecting the model; do not tune on test results. Do not resume the old three-class training run.
''',encoding='utf-8')
        shutil.copytree(ROOT/'datasets/anatomy_review_v1/character_review',output/'scene_catalog',dirs_exist_ok=True)
        state('complete',images=32000)
        if args.publish:
            run('publish_center_dataset.py','--dataset',output,'--package',ROOT/'exports/hf_detection400_v6')
            state('published',images=32000)
        print('ANATOMY_REBUILD_COMPLETE',flush=True)
    except BaseException as error:
        state('failed',error=str(error));raise

if __name__=='__main__':main()
