"""Replace training images with audited real-map renders, preserving the original held-out splits."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renders', type=Path, default=ROOT/'datasets/valorant_real_maps_30000')
    parser.add_argument('--base', type=Path, default=ROOT/'datasets/valorant_detection_400_v4')
    parser.add_argument('--output', type=Path, default=ROOT/'datasets/valorant_detection_400_v5')
    args = parser.parse_args(); renders=args.renders.resolve(); base=args.base.resolve(); output=args.output.resolve()
    assert output not in [renders, base]
    state=json.loads((renders/'generation_status.json').read_text())
    audit=json.loads((renders/'audit.json').read_text())
    assert state['phase']=='complete' and state['images']==audit['images']==30000
    metas=[json.loads(p.read_text()) for p in (renders/'metadata/train').glob('*.json')]
    assert len(metas)==30000 and all(len(m['actors'])<=1 for m in metas)
    assert len({a['character'] for m in metas for a in m['actors']})==29
    assert len({m['scene_family'] for m in metas})==11
    assert len({(m['scene_family'],m['spatial_region']) for m in metas})>=100
    assert len({m['crosshair']['style'] for m in metas})==6
    selected=[(renders,'train'),(base,'val'),(base,'test')]
    expected={p.stem for source,split in selected for p in (source/'metadata'/split).glob('*.json')}
    assert len(expected)==32000
    assert {p.stem for p in output.glob('metadata/*/*.json')}.issubset(expected)
    for source,split in selected:
        for directory in ['images','masks','metadata']:
            dest=output/directory/split;dest.mkdir(parents=True,exist_ok=True)
            for path in (source/directory/split).iterdir():shutil.copy2(path,dest/path.name)
        print('COPIED',split,flush=True)
    subprocess.run([sys.executable,'-u',str(ROOT/'tools/finalize_synthetic_dataset.py'),str(output),'--expected','32000','--workers','4'],cwd=ROOT,check=True)
    matched=0
    for split in ['val','test']:
        for directory in ['images','masks','metadata','labels']:
            for path in (base/directory/split).iterdir():
                assert sha(path)==sha(output/directory/split/path.name),str(path)
                matched+=1
    assert matched==8000
    provenance={'parent_dataset':base.name,'parent_hf_revision':'0f32d41612bb5bf13d5b5828b7985b98beb400f7',
                'training_replaced':True,'training_images':30000,'heldout_files_byte_identical':matched,
                'source_maps':json.loads((ROOT/'assets/source/valorant_maps/manifest.json').read_text()),
                'diversity':json.loads((renders/'diversity.json').read_text()),
                'generation':state,'crosshair_counts':dict(Counter(m['crosshair']['style'] for m in metas)),
                'rendering_limitations':'Original geometry, packed textures, vertex colors and normal maps; complex layered Blender materials are approximated in Godot. These are synthetic images, not game captures.',
                'evaluation_note':'The original 1k validation and 1k test images remain unchanged and are procedural environments. They do not measure generalization to unseen real maps or real gameplay.'}
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
    (output/'README.txt').write_text('32,000 native 400x400 images: 30,000 regenerated training images across 11 supplied Valorant maps; original 1,000 validation and 1,000 test images unchanged. One or zero actors; varied poses, angles, lighting, camera positions and six crosshair styles. Labels cover visible pixels after map and crosshair occlusion. See provenance.json for limitations.\n')
    catalog=output/'scene_catalog';catalog.mkdir(exist_ok=True)
    from finalize_synthetic_dataset import preview
    annotations=[json.loads(line) for line in (output/'annotations.jsonl').read_text().splitlines()]
    for name in sorted({m['scene_family'] for m in metas}):
        subset=[a for a in annotations if a['split']=='train' and a['scene_family']==name]
        preview(output,subset,catalog/f'{name}.jpg')
    names=sorted({m['scene_family'] for m in metas})
    (catalog/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Real-map training previews</title>'
        '<style>body{background:#202025;color:white;font:18px sans-serif;margin:2rem}img{max-width:100%}</style>'
        '<h1>Version 5: labeled real-map renders</h1><p>Ground-truth visible-pixel boxes, not model predictions.</p>'
        +''.join(f'<h2>{name.title()}</h2><img loading="lazy" src="{name}.jpg" alt="{name} labeled samples">' for name in names),encoding='utf-8')
    (output/'generation_status.json').write_text(json.dumps({'phase':'complete','images':32000,'training_images':30000}))
    print('REAL_MAP_PACKAGE_READY',str(output),flush=True)


if __name__=='__main__':
    main()
