"""Readable angle/occlusion examples from a finalized synthetic dataset."""
import argparse
import json
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

parser=argparse.ArgumentParser()
parser.add_argument('root',type=Path)
args=parser.parse_args();root=args.root.resolve()
annotations=[json.loads(line) for line in (root/'annotations.jsonl').read_text().splitlines()]
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
colors={'enemy':'#f477eb','teammate':'#43d9ff','head':'#ffed36'}
choices={}
for a in annotations:
    meta=json.loads((root/'metadata'/a['split']/f"{a['index']:06d}.json").read_text())
    actors={actor['instance_id']:actor for actor in meta['actors']}
    heads={o['instance_id'] for o in a['objects'] if o['class']=='head'}
    for obj in a['objects']:
        if obj['class']=='head':continue
        actor=actors[obj['instance_id']]
        camera=meta['camera_position'];pos=actor['position']
        angle=abs((actor['yaw']-math.atan2(camera[0]-pos[0],camera[2]-pos[2])+math.pi)%(math.pi*2)-math.pi)
        view=['Front','Front oblique','Side','Rear oblique','Rear'][min(4,int((angle+math.pi/8)/(math.pi/4)))]
        x0,y0,x1,y1=obj['bbox_xyxy']
        if 130<y1-y0<550 and 10<x0 and x1<1910 and y0>10 and y1<1065:
            if view not in choices and obj['instance_id'] in heads: choices[view]=(a,obj)
        if obj['instance_id'] not in heads and obj['visible_pixels']>200 and 10<x0 and x1<1910 and y0>20 and y1<1065:
            if 'Head hidden: no head label' not in choices:choices['Head hidden: no head label']=(a,obj)
    if len(choices)==6:break

canvas=Image.new('RGB',(1800,1280),'#131a23')
for k,title in enumerate(['Front','Front oblique','Side','Rear oblique','Rear','Head hidden: no head label']):
    if title not in choices:continue
    a,selected=choices[title]
    im=Image.open(root/'images'/a['split']/f"{a['index']:06d}.jpg").convert('RGB')
    d=ImageDraw.Draw(im)
    for obj in a['objects']:
        if obj['instance_id']!=selected['instance_id']:continue
        x0,y0,x1,y1=obj['bbox_xyxy'];color=colors[obj['class']]
        d.rectangle((x0,y0,x1-1,y1-1),outline=color,width=2)
        text_pos=(min(1790,x1+5),y0) if obj['class']=='head' else (x0,min(1050,y1+4))
        d.text(text_pos,obj['class'],font=font,fill=color,stroke_width=2,stroke_fill='black')
    x0,y0,x1,y1=selected['bbox_xyxy']
    side=min(1080,max(280,int(max(x1-x0,y1-y0)*1.7)))
    left=max(0,min(1920-side,(x0+x1-side)//2))
    top=max(0,min(1080-side,(y0+y1-side)//2))
    crop=im.crop((left,top,left+side,top+side)).resize((600,600))
    x=k%3*600;y=k//3*640
    canvas.paste(crop,(x,y+40))
    ImageDraw.Draw(canvas).text((x+12,y+10),f"{title} | {a['index']:06d}",font=font,fill='white')
canvas.save(root/'preview_angles_occlusion.jpg',quality=95)
(root/'inspection_examples.json').write_text(json.dumps({name:{'image_index':a['index'],'split':a['split'],'instance_id':obj['instance_id'],'character':obj['character']} for name,(a,obj) in choices.items()},indent=2))
print(root/'preview_angles_occlusion.jpg')
