"""Add exactly 2k teammate negatives and 8k mixed scenes to the published v7 dataset."""
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--publish-only',action='store_true')
    parser.add_argument('--workers',type=int,choices=range(1,7),default=4)
    args=parser.parse_args()
    base=ROOT/'datasets/valorant_detection_400_v7'
    output=ROOT/'datasets/valorant_detection_400_v8'
    output.mkdir(parents=True,exist_ok=True)
    assert json.loads((base/'audit.json').read_text())['images']==42000
    def state(phase,**extra):
        (output/'generation_status.json').write_text(json.dumps(dict(phase=phase,target=52000,updated_at=time.time(),**extra),indent=2))
    def run(script,*arguments):
        subprocess.run([sys.executable,'-u',str(ROOT/'tools'/script),*map(str,arguments)],cwd=ROOT,check=True)
    try:
        if args.publish_only:
            assert json.loads((output/'audit.json').read_text())['images']==52000
            assert json.loads((output/'provenance.json').read_text())['added_images']==10000
            state('publishing',images=52000)
            run('publish_center_dataset.py','--dataset',output,'--package',ROOT/'exports/hf_detection400_v8')
            state('published',images=52000)
            print('MIXED_DATASET_COMPLETE',flush=True)
            return
        state('assembling_existing')
        for kind in ['images','masks','metadata']:
            shutil.copytree(base/kind,output/kind,dirs_exist_ok=True)
        additions=[]
        for composition,count,start in [('teammate-only',2000,9000),('mixed',8000,8000)]:
            renders=ROOT/f'datasets/valorant_v8_{composition}'
            state('rendering',active_dataset=str(renders),composition=composition)
            run('generate_real_maps.py','--anatomy','--teammate-negatives','--expanded-views',
                '--composition',composition,'--split','train','--start',start,'--total-images',count,
                '--workers',args.workers,'--batch-size',2000,'--output',renders)
            audit=json.loads((renders/'audit.json').read_text())
            counts=audit['splits']['train']
            assert audit['images']==count
            if composition=='mixed':assert counts['mixed_images']==count and counts['empty_images']==0
            else:assert counts['teammate_only_images']==count and counts['empty_images']==count
            for kind in ['images','masks','metadata']:
                destination=output/kind/'train'
                incoming=renders/kind/'train'
                # IDs are outside the v7 ranges; resume may revisit identical additions.
                for path in incoming.iterdir():
                    existing=destination/path.name
                    if existing.exists():assert existing.read_bytes()==path.read_bytes()
                shutil.copytree(incoming,destination,dirs_exist_ok=True)
            additions.append(dict(composition=composition,images=count,start=start))
        state('auditing')
        run('finalize_anatomy_dataset.py',output,'--expected',52000)
        metadata=[json.loads(p.read_text()) for p in output.glob('metadata/*/*.json')]
        regions=defaultdict(set)
        for m in metadata:regions[m['split']].add((m['scene_family'],m['spatial_region']))
        for a,r in regions.items():
            for b,s in regions.items():
                if a!=b:assert not r&s
        for composition in ['mixed','teammate-only']:
            selected=[m for m in metadata if m.get('scene_composition')==composition]
            assert len({m['scene_family'] for m in selected})==11
            for role in (['enemy','teammate'] if composition=='mixed' else ['teammate']):
                assert len({a['character'] for m in selected for a in m['actors'] if a['role']==role})==29
        provenance=json.loads((base/'provenance.json').read_text())
        provenance.update(parent_hf_revision='5b84f5cd37403da329802afde3e6ef5b512befea',
            all_images_regenerated=False,preserved_images=42000,added_images=10000,additions=additions,
            region_counts={s:len(r) for s,r in regions.items()},cross_split_camera_region_overlap=0,
            render_workers=args.workers,extra_training_images=20000,
            map_counts=dict(Counter(m['scene_family'] for m in metadata)))
        (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
        card=(base/'README.txt').read_text(encoding='utf-8')
        training=card[card.index('## Training on H100'):].split('## Pre-retraining baseline')[0]
        description='''# Valorant detection 400 — enemy torso and head (v8)

52,000 native 400x400 images: 50,000 training, 1,000 validation, 1,000 test. Retains all 42,000 v7 images and adds exactly 2,000 teammate-only images with empty labels and 8,000 mixed enemy/teammate images. The new batch spans all eleven maps and all 29 characters on both teams.

Mixed images contain one enemy and one teammate at distinct, ray-checked ground positions at least 2.8 meters apart. Each has at least 80 visible silhouette pixels after map, actor and crosshair occlusion; the enemy has at least 8 visible anatomical target pixels. Partial overlaps are permitted. Only visible enemy torso/head pixels produce labels. Teammates are never labeled. Teammate-only frames contain one visible teammate and an empty label file.

Class IDs: 0 = enemy_body (visible chest, abdomen, pelvis); 1 = enemy_head (excluding identified hair). Arms, legs and excluded accessories occlude targets but receive no labels. Bounding rectangles can enclose excluded pixels. These skin/material-based masks approximate anatomy, not official game hitboxes.

The added 10,000 images use expanded training camera locations and six crosshair styles. Validation and test are unchanged from v7, contain single-character/background scenes, and do not measure mixed-scene performance. Camera regions are disjoint across splits; all splits share map assets and may share target regions. Synthetic shaders and map materials are approximations, not exact game rendering.

'''
        (output/'README.txt').write_text(description+training,encoding='utf-8')
        run('build_teammate_review.py',output)
        mixed=ROOT/'datasets/valorant_v8_mixed'
        shutil.copy2(mixed/'preview_scenes.jpg',output/'preview_new_scenes.jpg')
        state('complete',images=52000)
        if args.publish:
            state('publishing',images=52000)
            run('publish_center_dataset.py','--dataset',output,'--package',ROOT/'exports/hf_detection400_v8')
            state('published',images=52000)
        print('MIXED_DATASET_COMPLETE',flush=True)
    except BaseException as error:
        state('failed',error=str(error));raise


if __name__=='__main__':main()
