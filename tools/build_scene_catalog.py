"""Build a deterministic labeled catalog of every added scene design."""
import json
from pathlib import Path
from PIL import Image, ImageDraw


def build_catalog(root, metadata, annotations):
    root=Path(root)
    out=root/'scene_catalog';out.mkdir(exist_ok=True)
    indexed={a['index']:a for a in annotations}
    designs=sorted({m['scene_design_id'] for m in metadata})
    records=[];tiles=[]
    colors={'enemy':'#f080ff','teammate':'#65d5ff','head':'#ffe04b'}
    for design in designs:
        candidates=sorted((m for m in metadata if m['scene_design_id']==design and m['target_category']=='normal_scale'),key=lambda m:m['index'])
        m=candidates[design%2]
        a=indexed[m['index']]
        tile=Image.new('RGB',(400,448),'#171b20')
        im=Image.open(root/'images/train'/f"{m['index']:06d}.jpg").convert('RGB')
        draw=ImageDraw.Draw(im)
        for obj in a['objects']:
            box=obj['bbox_xyxy'];color=colors[obj['class']]
            draw.rectangle((box[0],box[1],box[2]-1,box[3]-1),outline=color,width=2)
            label_y=min(388,box[3]+2) if obj['class']=='head' else max(0,box[1]-12)
            draw.text((box[0],label_y),obj['class'],fill=color,stroke_width=1,stroke_fill='black')
        tile.paste(im,(0,0));draw=ImageDraw.Draw(tile)
        draw.text((5,405),f"{design+1:03d}: {m['structural_theme']}",fill='white')
        draw.text((5,423),f"{m['spatial_layout']} | frame {m['index']}",fill='white')
        tiles.append(tile)
        group=[x for x in metadata if x['scene_design_id']==design]
        records.append(dict(design_id=design,theme=m['structural_theme'],layout=m['spatial_layout'],images=len(group),scene_seeds=sorted({x['scene_seed'] for x in group}),sample_index=m['index']))
    pages=[]
    for start in range(0,len(tiles),12):
        canvas=Image.new('RGB',(1200,1792),'#171b20')
        for j,tile in enumerate(tiles[start:start+12]):canvas.paste(tile,((j%3)*400,(j//3)*448))
        name=f'page_{start//12+1:02d}.jpg';canvas.save(out/name,quality=94);pages.append(name)
    (out/'catalog.json').write_text(json.dumps(records,indent=2))
    body=''.join(f'<a href="{name}"><img loading="lazy" src="{name}" alt="Scene designs {i*12+1} through {(i+1)*12}"></a>' for i,name in enumerate(pages))
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>120 scene designs</title><style>body{background:#171b20;color:white;font:18px sans-serif;margin:24px}img{max-width:100%;display:block;margin:24px 0}</style><h1>120 scene designs</h1><p>20 structural themes × 6 spatial layouts; two independent seeds and 100 training images per design. Deterministic normal-scale samples with visible-pixel ground truth: purple enemy, cyan teammate, yellow head. These are labels, not model predictions.</p>'+body,encoding='utf-8')
    print('SCENE_CATALOG_READY',out,flush=True)
