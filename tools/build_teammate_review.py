"""Show labeled enemies alongside unlabeled teammate hard negatives."""
import argparse
from collections import defaultdict
import json
import shutil
from pathlib import Path
from PIL import Image,ImageDraw
from finalize_anatomy_dataset import panel

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
    annotations={a['index']:a for line in (root/'annotations.jsonl').read_text().splitlines() for a in [json.loads(line)]}
    groups=defaultdict(dict)
    for path in root.glob('metadata/train/*.json'):
        m=json.loads(path.read_text())
        if not m['actors']:continue
        actor=m['actors'][0];kind='enemy' if actor['role']=='enemy' else actor['highlight_style']
        score=abs(m['pre_hud_body_pixels']-7000)
        previous=groups[actor['character']].get(kind)
        if previous is None or score<previous[0]:groups[actor['character']][kind]=(score,m)
    audit=json.loads((root/'audit.json').read_text())
    if audit['images']==32000:
        assert len(groups)==29 and all(set(g)=={'enemy','none','cyan'} for g in groups.values())
    out=root/'scene_catalog';out.mkdir(exist_ok=True)
    page='<!doctype html><meta charset="utf-8"><title>Enemy / teammate training review</title><style>body{background:#202025;color:white;font:18px sans-serif;margin:24px}img{max-width:100%}</style><h1>Two-class labels with teammate negatives</h1><p>Left: enemy with torso/head labels. Middle: teammate without highlight, empty labels. Right: cyan-highlighted teammate, empty labels. Same anatomy definitions as the approved v6 dataset. Pose and background differ across columns; these are examples, not paired experiments.</p>'
    for name,cases in sorted(groups.items()):
        canvas=Image.new('RGB',(1200,430),'#202025');d=ImageDraw.Draw(canvas)
        for i,kind in enumerate(['enemy','none','cyan']):
            d.text((i*400+8,8),f'{name}: '+('ENEMY: labeled' if kind=='enemy' else f'TEAMMATE ({kind}): EMPTY labels'),fill='white')
            if kind not in cases:continue
            m=cases[kind][1];a=annotations[m['index']]
            if kind!='enemy':assert not a['objects'] and (root/f"labels/train/{m['index']}.txt").read_text()==''
            canvas.paste(panel(root,a),(i*400,30))
        canvas.save(out/f'teams_{name}.jpg',quality=95)
        page+=f'<h2>{name.title()}</h2><img loading="lazy" src="teams_{name}.jpg">'
    (out/'index.html').write_text(page,encoding='utf-8');print(out/'index.html')
    baseline=Path(__file__).resolve().parents[1]/'runs/analysis/teammate_v7_baseline_9460cdaf8b55/results.json'
    if audit['images']==32000 and baseline.exists():
        shutil.copy2(baseline,root/'baseline_teammate_test.json')
        result=json.loads(baseline.read_text());negative=result['negative_groups']['teammate']
        with (root/'README.txt').open('a',encoding='utf-8') as stream:
            stream.write(f"\n## Pre-retraining baseline\n\nCheckpoint 9460cdaf8b55, at its frozen published confidence 0.23, falsely detects enemies in {negative['frames_with_false_detection']} of {negative['images']} teammate-only test frames ({negative['frame_false_positive_rate']:.2%}). These are synthetic test frames, not measured real-game rates. See baseline_teammate_test.json. Retrain and compare teammate frame false-positive rates as well as enemy precision/recall; data regeneration alone does not change the deployed model.\n")

if __name__=='__main__':main()
