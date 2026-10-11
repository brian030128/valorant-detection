"""Mine training-only background negatives and merge 2,000 targeted samples with the frozen original dataset."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'datasets/valorant_center400_10k'
TARGET=ROOT/'datasets/valorant_targeted_2000'
CANDIDATES=ROOT/'datasets/valorant_negative_candidates'
DEST=ROOT/'datasets/valorant_detection_400_v2'
MODEL=ROOT/'models/valorant-center400-yolo11s/best.pt'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from ultralytics import YOLO
    assert 'GENERATION_COMPLETE' in (TARGET/'render.log').read_text()
    assert 'GENERATION_COMPLETE' in (CANDIDATES/'render.log').read_text()
    paths=sorted(TARGET.glob('metadata/train/*.json'))
    assert len(paths)==2000
    positive=[];negative=[]
    for path in paths:
        meta=json.loads(path.read_text())
        (positive if meta['actors'] else negative).append(path)
    negative+=sorted(CANDIDATES.glob('metadata/train/*.json'))
    assert len(positive)==1500 and len(negative)==2500
    cache=ROOT/'exports/targeted_negative_scores.json'
    identity=dict(model_sha256=digest(MODEL),candidates={str(p):digest(p) for p in negative})
    if cache.exists() and json.loads(cache.read_text())['identity']==identity:
        scores=json.loads(cache.read_text())['scores']
    else:
        model=YOLO(str(MODEL));scores=[]
        for start in range(0,len(negative),8):
            batch=negative[start:start+8];images=[]
            for p in batch:
                root=p.parents[2]
                assert not json.loads(p.read_text())['actors']
                with Image.open(root/'masks/train'/f'{p.stem}.png') as mask:assert not np.array(mask.convert("RGB")).any()
                with Image.open(root/'images/train'/f'{p.stem}.jpg') as im:images.append(ImageOps.expand(im.convert('RGB'),border=8,fill=(114,114,114)))
            results=model.predict(images,imgsz=416,conf=.001,iou=.7,max_det=100,device=0,verbose=False)
            for path,result in zip(batch,results):
                heads=[float(b.conf) for b in result.boxes if int(b.cls)==2]
                scores.append(dict(path=str(path),max_head_confidence=max(heads,default=0),head_detections_at_052=sum(v>=.52 for v in heads)))
            if start%200==0:print(f'MINED {min(start+8,len(negative))}/{len(negative)}',flush=True)
        cache.write_text(json.dumps(dict(identity=identity,scores=scores),indent=2))
    ranked=sorted(scores,key=lambda r:(-r['max_head_confidence'],r['path']))
    chosen=ranked[:500]
    selected=positive+[Path(r['path']) for r in chosen]
    benchmark=ROOT/'datasets/valorant_mapshift_4000'
    benchmark_hashes={digest(p) for p in benchmark.glob('images/test/*.jpg')}
    assert len(benchmark_hashes)==4000
    assert not {digest(p.parents[2]/'images/train'/f'{p.stem}.jpg') for p in selected}&benchmark_hashes

    DEST.mkdir(parents=True,exist_ok=True)
    # New output only; never mutate the original or held-out map benchmark.
    expected_stems={p.stem for p in BASE.glob('metadata/*/*.json')}|{p.stem for p in selected}
    existing={p.stem for p in DEST.glob('metadata/*/*.json')}
    assert existing.issubset(expected_stems),'Existing output belongs to a different selection'
    for root,paths in [(BASE,sorted(BASE.glob('metadata/*/*.json'))),(None,selected)]:
        for path in paths:
            source=root or path.parents[2];split=path.parent.name
            for directory,extension in [('images','.jpg'),('masks','.png'),('metadata','.json')]:
                src=source/directory/split/(path.stem+extension)
                dst=DEST/directory/split/src.name;dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
            if root is None:
                dst=DEST/'metadata'/split/path.name;meta=json.loads(dst.read_text())
                meta['frame_seed']=20261013+(meta['index']*20+3)*104729+meta['acceptance_attempt']*15485863
                dst.write_text(json.dumps(meta))
    subprocess.run([sys.executable,'-u','tools/finalize_synthetic_dataset.py',str(DEST),'--expected','12000','--workers','4'],cwd=ROOT,check=True)
    # Exact byte identity of every held-out image, mask, label and metadata file.
    checked=0
    for split in ['val','test']:
        for directory in ['images','masks','labels','metadata']:
            for p in (BASE/directory/split).iterdir():
                assert digest(p)==digest(DEST/directory/split/p.name),p
                checked+=1
    metas=[json.loads((DEST/'metadata/train'/p.name).read_text()) for p in selected]
    tiny=[m for m in metas if m['target_category']=='tiny_head']
    small=[m for m in metas if m['target_category']=='small_head']
    covered=[m for m in metas if m['target_category']=='partial_cover']
    assert len(tiny)==len(small)==len(covered)==500
    assert all(2<=m['head_short_side']<8 for m in tiny)
    assert all(2<=m['head_short_side']<16 for m in small)
    assert all(.15<=m['visible_head_pixels']/m['uncovered_head_pixels']<=.9 for m in covered)
    provenance=dict(original_dataset_repo='edgeai-lab/valorant-detection-400',original_revision='6bfd4d0b5e13dc595dc6a23af4754260cf0ceead',
        original_audit_sha256=digest(BASE/'audit.json'),added_training_images=2000,original_training_index_max=9999,
        targeted_categories=dict(Counter(m['target_category'] for m in metas)),
        head_short_side_distribution=dict(Counter('under_8' if m['head_short_side']<8 else '8_to_15' if m['head_short_side']<16 else '16_plus' for m in metas if m['actors'])),
        heldout_files_byte_identical=checked,exact_image_overlap_with_map_benchmark=0,negative_mining=dict(model_sha256=digest(MODEL),pool_size=2500,selected_count=500,
        pool_images_with_head_fp_at_052=sum(r['max_head_confidence']>=.52 for r in ranked),selected_head_fp_at_052=sum(r['max_head_confidence']>=.52 for r in chosen),
        selection_rule='Highest maximum head confidence, deterministic path tie-break; below-threshold candidates retained to reach 500.',selected=[dict(index=int(Path(r['path']).stem),max_head_confidence=r['max_head_confidence'],head_detections_at_052=r['head_detections_at_052']) for r in chosen]),
        evaluation_note='Original validation/test and 4,000 map benchmark files unchanged. New training uses independent seeds, poses and layouts in the four map families. The old map benchmark is now a known-family regression set, not evidence of generalization to wholly unseen map families.')
    audit=json.loads((DEST/'audit.json').read_text())
    audit['sampling']={'policy':'Mixed original visibility-biased sampling and targeted examples; see per-image metadata and provenance.',
        'original_images':10000,'added_training_images':2000,'targeted_categories':provenance['targeted_categories']}
    (DEST/'audit.json').write_text(json.dumps(audit,indent=2))
    (DEST/'provenance.json').write_text(json.dumps(provenance,indent=2))
    (DEST/'README.txt').write_text('12,000 native 400x400 crops: 10,000 train, 1,000 validation, 1,000 test. Original 8,000 training images plus 2,000 targeted additions. Visible-pixel labels only. See provenance.json for categories, mining and unchanged held-out checks.\n')
    (DEST/'generation_status.json').write_text(json.dumps(dict(phase='complete',images=12000)))
    print('EXPANDED_DATASET_READY',DEST,flush=True)


if __name__=='__main__':main()
