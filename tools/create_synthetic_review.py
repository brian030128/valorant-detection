"""Create full-resolution labeled examples and a purple before/after comparison."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/synthetic_review'
OUT=DATA/'review'
OUT.mkdir(exist_ok=True)
COLORS={'enemy':'#ff71eb','teammate':'#42ddff','head':'#ffeb39'}
FONT=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
SMALL=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
annotations={a['index']:a for a in map(json.loads,(DATA/'annotations.jsonl').read_text().splitlines())}

def annotate(index):
    a=annotations[index]
    source=Image.open(DATA/'images'/a['split']/f'{index:06d}.jpg').convert('RGB')
    im=Image.new('RGB',(1920,1140),'#161c24');im.paste(source,(0,60));d=ImageDraw.Draw(im)
    d.text((20,17),f"{index:06d} | {a['scene_family']} | visible-pixel boxes",fill='white',font=FONT)
    for j,(name,color) in enumerate(COLORS.items()):
        d.rectangle((1160+j*240,19,1178+j*240,37),fill=color)
        d.text((1190+j*240,15),name.upper(),fill=color,font=FONT)
    for obj in a['objects']:
        x0,y0,x1,y1=obj['bbox_xyxy'];y0+=60;y1+=60
        color=COLORS[obj['class']]
        d.rectangle((x0,y0,x1-1,y1-1),outline=color,width=2)
        text=f"{obj['class'].upper()} #{obj['instance_id']}"
        if obj['class']=='head': tx=min(1750,x1+5);ty=y0
        else:tx=x0;ty=max(60,y1+4) if y1<1104 else max(60,y0-26)
        bounds=d.textbbox((tx,ty),text,font=SMALL)
        d.rectangle((bounds[0]-3,bounds[1]-2,bounds[2]+3,bounds[3]+2),fill='#111820')
        d.text((tx,ty),text,font=SMALL,fill=color)
    im.save(OUT/f'labeled_{index:06d}.jpg',quality=96)
    return im

for index in [2,17,21,33,42,57,66,78]:annotate(index)

# Pixel-aligned crop of the same scene and animation, before and after highlighting.
old=Image.open(OUT/'stronger_purple_reference.jpg').convert('RGB')
new=Image.open(DATA/'images/train/000002.jpg').convert('RGB')
region=(900,380,1300,800)
comparison=Image.new('RGB',(1200,690),'#161c24')
comparison.paste(old.crop(region).resize((600,630)),(0,60))
comparison.paste(new.crop(region).resize((600,630)),(600,60))
d=ImageDraw.Draw(comparison)
d.text((20,20),'Stronger purple (reverted)',font=FONT,fill='white')
d.text((620,20),'Restored original purple',font=FONT,fill='white')
comparison.save(OUT/'purple_comparison.jpg',quality=96)

# A readable 2x2 sheet, with close crops as well as the original full images.
panels=[(2,(870,365,1320,815)),(21,(520,230,1150,860)),(42,(570,300,1230,960)),(66,(630,350,1230,950))]
sheet=Image.new('RGB',(1600,1680),'#161c24');d=ImageDraw.Draw(sheet)
for k,(index,box) in enumerate(panels):
    a=annotations[index];im=annotate(index)
    # Union body bounds determines the crop for the largest visible character.
    bodies=[o for o in a['objects'] if o['class']!='head']
    body=max(bodies,key=lambda o:o['visible_pixels'])
    x0,y0,x1,y1=body['bbox_xyxy'];side=min(1080,max(330,int(max(x1-x0,y1-y0)*1.45)))
    cx=(x0+x1)//2;cy=(y0+y1)//2+60
    left=max(0,min(1920-side,cx-side//2));top=max(60,min(1140-side,cy-side//2))
    crop=im.crop((left,top,left+side,top+side)).resize((800,800))
    x=(k%2)*800;y=(k//2)*840
    sheet.paste(crop,(x,y+40))
    d.text((x+15,y+10),f"{index:06d} | {a['scene_family']} | {body['character']}",font=FONT,fill='white')
sheet.save(OUT/'labeled_closeups.jpg',quality=95)
print(OUT)
