"""Merge an audited parent dataset with training-only scene renders, keeping held-out files identical."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=ROOT/'datasets/valorant_detection_400_v2')
    parser.add_argument('--additions',type=Path,default=ROOT/'datasets/valorant_scenes_8000')
    parser.add_argument('--output',type=Path,default=ROOT/'datasets/valorant_detection_400_v3')
    parser.add_argument('--expected-added',type=int,default=8000)
    args=parser.parse_args();base=args.base.resolve();added=args.additions.resolve();dest=args.output.resolve()
    assert dest not in [base,added]
    assert 'GENERATION_COMPLETE' in (added/'render.log').read_text()
    original=sorted(base.glob('metadata/*/*.json'));new=sorted(added.glob('metadata/*/*.json'))
    assert len(new)==args.expected_added
    assert all(p.parent.name=='train' for p in new)
    assert not {p.stem for p in original}&{p.stem for p in new}
    audit=json.loads((base/'audit.json').read_text());assert len(original)==audit['images']
    expected=len(original)+len(new)
    expected_names={p.stem for p in original+new}
    assert {p.stem for p in dest.glob('metadata/*/*.json')}.issubset(expected_names)
    for paths,source in [(original,base),(new,added)]:
        for i,path in enumerate(paths,1):
            split=path.parent.name
            for directory,extension in [('images','.jpg'),('masks','.png'),('metadata','.json')]:
                src=source/directory/split/(path.stem+extension);target=dest/directory/split/src.name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
            if source==added:
                target=dest/'metadata'/split/path.name;meta=json.loads(target.read_text())
                meta['scene_generator']='scene_expansion_dataset.gd/v1'
                target.write_text(json.dumps(meta))
            if i%2000==0:print(f'COPIED {source.name}: {i}/{len(paths)}',flush=True)
    subprocess.run([sys.executable,'-u','tools/finalize_synthetic_dataset.py',str(dest),'--expected',str(expected),'--workers','4'],cwd=ROOT,check=True)
    matched=0
    for split in ['val','test']:
        for directory in ['images','masks','labels','metadata']:
            for p in (base/directory/split).iterdir():
                assert sha(p)==sha(dest/directory/split/p.name),p
                matched+=1
    print('HELD_OUT_FILES_IDENTICAL',matched,flush=True)
    from finalize_synthetic_dataset import preview
    new_indices={int(p.stem) for p in new}
    annotations=[json.loads(line) for line in (dest/'annotations.jsonl').read_text().splitlines()]
    preview(dest,[a for a in annotations if a['index'] in new_indices],dest/'preview_new_scenes.jpg')
    metas=[json.loads(p.read_text()) for p in new]
    families=Counter(m['scene_family'] for m in metas)
    assert len(families)==8 and set(families.values())=={1000}
    assert len({m['scene_group'] for m in metas})==160
    prior=json.loads((base/'provenance.json').read_text())
    provenance=dict(parent_dataset=base.name,parent_hf_revision='72bd3da0041dcba7ae43399abb49f193ff89f668',
        parent_audit_sha256=sha(base/'audit.json'),parent_provenance=prior,
        added_images=len(new),added_split='train',scene_family_counts=dict(families),
        added_scene_layouts=160,target_categories=dict(Counter(m['target_category'] for m in metas)),
        generator_sha256=sha(ROOT/'environment/scene_expansion_dataset.gd'),
        heldout_files_byte_identical=matched,
        evaluation_note='Validation/test are unchanged. Added families appear only in training; do not claim unseen-family robustness from the original validation/test. Existing map-shift benchmark is a known-family regression set.')
    (dest/'provenance.json').write_text(json.dumps(provenance,indent=2))
    merged_audit=json.loads((dest/'audit.json').read_text())
    merged_audit['sampling']={'policy':'Original crops plus targeted v2 and scene-diverse v3 training additions; per-image metadata records sampling.', 'parent_images':len(original),'added_images':len(new)}
    (dest/'audit.json').write_text(json.dumps(merged_audit,indent=2))
    (dest/'README.txt').write_text(f'{expected} native 400x400 images; {expected-2000} train, 1000 validation, 1000 test. Added {len(new)} training images in eight new scene families. Visible-pixel labels only. See provenance.json.\n')
    (dest/'generation_status.json').write_text(json.dumps(dict(phase='complete',images=expected)))
    print('SCENE_EXPANSION_READY',dest,flush=True)

if __name__=='__main__':main()
