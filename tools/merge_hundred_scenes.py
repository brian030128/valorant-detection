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
    parser.add_argument('--base',type=Path,default=ROOT/'datasets/valorant_detection_400_v3')
    parser.add_argument('--additions',type=Path,default=ROOT/'datasets/valorant_120scenes_12000')
    parser.add_argument('--output',type=Path,default=ROOT/'datasets/valorant_detection_400_v4')
    parser.add_argument('--expected-added',type=int,default=12000)
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
                meta['scene_generator']='hundred_scenes_dataset.gd/v1'
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
    assert len(families)==120 and set(families.values())=={100}
    themes=Counter(m['structural_theme'] for m in metas)
    layouts=Counter(m['spatial_layout'] for m in metas)
    categories=Counter(m['target_category'] for m in metas)
    assert len(themes)==20 and set(themes.values())=={600}
    assert len(layouts)==6 and set(layouts.values())=={2000}
    assert len(categories)==5 and set(categories.values())=={2400}
    assert all(len({m['scene_group'] for m in metas if m['scene_family']==family})==2 for family in families)
    assert len({m['scene_group'] for m in metas})==240
    assert set(Counter(m['scene_group'] for m in metas).values())=={50}
    roles=Counter(a['role'] for m in metas for a in m['actors'])
    assert roles=={'enemy':7200,'teammate':2400},roles
    assert len({a['character'] for m in metas for a in m['actors']})==29
    assert all(len(m['actors'])<=1 for m in metas)
    assert {m['purple_srgb'].lower() for m in metas}=={'#b04dbe'}
    prior=json.loads((base/'provenance.json').read_text())
    provenance=dict(parent_dataset=base.name,parent_hf_revision='f74434b3eae05722fe98bd12f59e3f61070461da',
        parent_audit_sha256=sha(base/'audit.json'),parent_provenance=prior,
        added_images=len(new),added_split='train',scene_family_counts=dict(families),
        added_scene_layouts=240, structural_theme_counts=dict(themes), spatial_layout_counts=dict(layouts),target_categories=dict(Counter(m['target_category'] for m in metas)),
        generator_sha256=sha(ROOT/'environment/hundred_scenes_dataset.gd'),
        heldout_files_byte_identical=matched,
        evaluation_note='Validation/test are unchanged. Added families appear only in training; do not claim unseen-family robustness from the original validation/test. Both map benchmarks remain excluded. Construction/scaffolding benchmark failures informed this expansion, so it is a known-style regression set, not a blind unseen-family test.')
    (dest/'provenance.json').write_text(json.dumps(provenance,indent=2))
    merged_audit=json.loads((dest/'audit.json').read_text())
    merged_audit['sampling']={'policy':'Original crops plus v2/v3 and 120-design v4 training additions; per-image metadata records sampling.', 'parent_images':len(original),'added_images':len(new)}
    (dest/'audit.json').write_text(json.dumps(merged_audit,indent=2))
    (dest/'README.txt').write_text(f'{expected} native 400x400 images; {expected-2000} train, 1000 validation, 1000 test. Added {len(new)} training images across 120 scene designs (20 structural themes x 6 spatial layouts; two seeds each). Visible-pixel labels only. See provenance.json.\n')
    from build_scene_catalog import build_catalog
    build_catalog(dest, metas, annotations)
    (dest/'generation_status.json').write_text(json.dumps(dict(phase='complete',images=expected)))
    print('SCENE_EXPANSION_READY',dest,flush=True)

if __name__=='__main__':main()
