"""One native-resolution three-angle label/mask sheet per character."""
import argparse
import html
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from finalize_anatomy_dataset import panel

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
    annotations=[json.loads(line) for line in (root/'annotations.jsonl').read_text().splitlines()]
    by_id={a['index']:a for a in annotations};out=root/'character_review';out.mkdir(exist_ok=True)
    slugs=[]
    for char in range(29):
        rows=[by_id[char*3+i] for i in range(3)]
        meta=json.loads((root/f'metadata/test/{char*3}.json').read_text())
        slug=meta['actors'][0]['character'];slugs.append(slug)
        sheet=Image.new('RGB',(1200,840),'#202025');draw=ImageDraw.Draw(sheet)
        draw.text((12,10),f'{slug.upper()} | pink: enemy_body / yellow: enemy_head | labels above, exact visible masks below',fill='white')
        for i,a in enumerate(rows):
            im=panel(root,a);sheet.paste(im,(i*400,40))
            raw=Image.open(root/f"images/test/{a['index']}.jpg").convert('RGB')
            pixels=np.array(Image.open(root/f"masks/test/{a['index']}.png").convert('RGB'))
            overlay=np.array(raw).astype(float)*.30
            overlay[pixels[:,:,2]>127]=[239,114,255];overlay[pixels[:,:,1]>127]=[255,224,75]
            sheet.paste(Image.fromarray(overlay.astype('uint8')),(i*400,440))
        sheet.save(out/f'{slug}.jpg',quality=96)
    assert len(set(slugs))==29
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>29 character anatomy labels</title><style>body{background:#17171c;color:white;font:18px sans-serif;margin:24px}img{max-width:100%;display:block}a{color:#c9adff}</style><h1>All 29 characters: torso and head labels</h1><p>Three angles per character. Upper row: YOLO bounding boxes. Lower row: exact visible target pixels. Hair, limbs and accessories remain occluders. Bounding boxes can enclose background or excluded pixels; masks define the labeled surface. These are visual anatomy labels, not verified game hitboxes.</p>'+''.join(f'<h2>{html.escape(s.title())}</h2><a href="{s}.jpg"><img loading="lazy" src="{s}.jpg"></a>' for s in slugs),encoding='utf-8')
    print(out/'index.html')

if __name__=='__main__':main()
