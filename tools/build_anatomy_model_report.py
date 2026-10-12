"""Combine anatomy tests and make prediction comparisons for all 29 characters."""
import argparse
from collections import defaultdict
import json
from PIL import Image,ImageDraw
from pathlib import Path
from evaluate_anatomy_model import draw_boxes,NAMES

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
    page='<!doctype html><meta charset="utf-8"><title>New model test results</title><style>body{background:#202025;color:white;font:18px sans-serif;margin:24px}a{color:#cbb5ff}td,th{padding:10px;border:1px solid #777}img{max-width:100%}</style><h1>Enemy torso/head model: 9460cdaf8b55</h1><p>Published thresholds: 0.23 for both classes. Class-aware IoU ≥ 0.50. No test tuning. All tests use synthetic images; these results do not establish real-game accuracy.</p><table><tr><th>Test</th><th>Images</th><th>Torso P / R</th><th>Head P / R</th></tr>'
    reports={}
    for key,title in [('heldout','Published held-out split'),('fresh','Fresh renders on held-out camera regions'),('characters','Controlled 29-character review')]:
        r=json.loads((root/key/'results.json').read_text());reports[key]=r
        b,h=[r['metrics'][n] for n in NAMES]
        page+=f'<tr><td><a href="{key}/index.html">{title}</a></td><td>{r["images"]}</td><td>{b["precision"]:.2%} / {b["recall"]:.2%}</td><td>{h["precision"]:.2%} / {h["recall"]:.2%}</td></tr>'
    page+='</table><p>The fresh test reuses the existing held-out camera regions on the same 11 map assets, with new sample indices, poses, aim, lighting and crosshairs. The controlled character review is a diagnostic set, not a representative gameplay benchmark.</p><p><a href="characters/all_characters.html">View all 29 characters: labels versus predictions, three angles each</a></p><h2>Small-head errors</h2><p>On the original test, 79 of 105 missed heads are under 8 pixels on their shortest side. 85 of 102 false head predictions overlap a true head but have IoU below 0.50. Both localization and small-target recall need improvement.</p><img src="heldout/split.jpg"><img src="heldout/ascent.jpg">'
    (root/'index.html').write_text(page,encoding='utf-8')
    payload=json.loads((root/'characters/predictions.json').read_text());groups=defaultdict(list)
    for r in payload['records']:groups[r['truth'][0]['character']].append(r)
    assert len(groups)==29
    gallery=page[:page.index('<h1>')]+'<h1>All 29 characters: ground truth versus model predictions</h1><p>Each row is one angle. Ground truth on the left; predictions on the right. Pink: torso, yellow: head. Confidence ≥ 0.23.</p>'
    for name,records in sorted(groups.items()):
        canvas=Image.new('RGB',(800,425*len(records)),'#202025')
        for i,r in enumerate(records):
            im=Image.open(r['image_path']).convert('RGB')
            canvas.paste(draw_boxes(im,r['truth']),(0,i*425+25))
            canvas.paste(draw_boxes(im,[q for q in r['predictions'] if q['confidence']>=.23],True),(400,i*425+25))
            ImageDraw.Draw(canvas).text((8,i*425+6),f'{name} / angle {i+1} | ground truth left; predictions right',fill='white')
        canvas.save(root/'characters'/f'{name}.jpg',quality=95)
        gallery+=f'<h2>{name.title()}</h2><a href="{name}.jpg"><img loading="lazy" src="{name}.jpg"></a>'
    (root/'characters/all_characters.html').write_text(gallery,encoding='utf-8')
    (root/'summary.json').write_text(json.dumps({k:dict(images=v['images'],metrics=v['metrics'],head_sizes=v['head_sizes']) for k,v in reports.items()},indent=2))
    print(root/'index.html')

if __name__=='__main__':main()
