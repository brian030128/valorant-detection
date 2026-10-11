"""Show downloaded model predictions alongside labels on fixed held-out examples."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
import torch
from ultralytics import YOLO
from analyze_detection_failures import font, match

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/valorant_center400_10k'
MODEL=ROOT/'models/valorant-center400-yolo11s'
OUT=ROOT/'runs/previews/hf_center400_yolo11s'
NAMES=['enemy','teammate','head']
COLORS=['#ff80e8','#55dcff','#fff34f']


def annotated(image,boxes,predictions=False):
    image=image.copy();draw=ImageDraw.Draw(image)
    for box in boxes:
        cls=box['class_id'];x0,y0,x1,y1=box['box']
        draw.rectangle((x0,y0,x1,y1),outline=COLORS[cls],width=2)
        label=NAMES[cls]+(f" {box['confidence']:.2f}" if predictions else '')
        y=max(0,y0-15) if cls==2 else min(385,y1+2)
        x=min(max(0,x0),max(0,400-draw.textlength(label,font=font(12))-4))
        draw.text((x,y),label,font=font(12),fill=COLORS[cls],stroke_width=1,stroke_fill='black')
    return image


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((MODEL/'manifest.json').read_text())
    for name in ['best.pt','thresholds.json']:
        assert hashlib.sha256((MODEL/name).read_bytes()).hexdigest()==manifest[name]['sha256']
    config=json.loads((MODEL/'thresholds.json').read_text())
    records=[json.loads(line) for line in (DATA/'annotations.jsonl').read_text().splitlines()]
    records=[r for r in records if r['split']=='test']
    records.sort(key=lambda r:hashlib.sha256(f"preview-{r['index']}".encode()).hexdigest())
    families=sorted({r['scene_family'] for r in records})[:6]
    selected=[next(r for r in records if r['scene_family']==family and any(o['class']=='enemy' for o in r['objects'])) for family in families]
    selected.append(next(r for r in records if any(o['class']=='teammate' for o in r['objects'])))
    selected.append(next(r for r in records if not r['objects']))
    model=YOLO(str(MODEL/'best.pt'));torch.set_num_threads(4)
    assert list(model.names.values())==NAMES
    summary=[];tiles=[]
    for record in selected:
        stem=f"{record['index']:06d}"
        image=Image.open(DATA/'images/test'/f'{stem}.jpg').convert('RGB')
        assert image.size==(400,400)
        padded=ImageOps.expand(image,border=8,fill=(114,114,114))
        result=model.predict(padded,imgsz=416,device=0,conf=.001,iou=config['nms_iou'],max_det=config['max_det'],verbose=False)[0]
        predictions=[]
        for raw in result.boxes:
            cls=int(raw.cls.item());confidence=float(raw.conf.item())
            if confidence>=config['confidence'][NAMES[cls]]:
                predictions.append(dict(class_id=cls,confidence=confidence,box=(raw.xyxy[0]-8).clamp(0,400).tolist()))
        truth=[dict(class_id=NAMES.index(o['class']),box=o['bbox_xyxy']) for o in record['objects']]
        matched,correct,false=match(truth,predictions,0)
        misses=len(truth)-len(matched)
        left=annotated(image,truth);right=annotated(image,predictions,True)
        right.save(OUT/f'{stem}_predictions.png')
        tile=Image.new('RGB',(816,462),'#111b29');draw=ImageDraw.Draw(tile)
        draw.text((8,5),f"{stem} | {record['scene_family']}",font=font(18),fill='white')
        draw.text((8,29),'GROUND TRUTH',font=font(14),fill='#cbd7e9')
        draw.text((416,29),'MODEL PREDICTIONS',font=font(14),fill='#cbd7e9')
        tile.paste(left,(0,50));tile.paste(right,(416,50))
        tile.save(OUT/f'{stem}_comparison.png')
        tiles.append(tile)
        summary.append(dict(image=stem,scene=record['scene_family'],truth=truth,predictions=predictions,
                            matched=len(matched),missed=misses,false_positives=len(false)))
    sheet=Image.new('RGB',(1632,462*4+74),'#111b29');draw=ImageDraw.Draw(sheet)
    draw.text((16,8),'Trained YOLO11s | held-out 400 x 400 crops',font=font(26),fill='white')
    draw.text((16,43),'Pink: enemy   Cyan: teammate   Yellow: head | Confidence: enemy 0.82 / teammate 0.22 / head 0.52',font=font(18),fill='#cbd7e9')
    for index,tile in enumerate(tiles):sheet.paste(tile,((index%2)*816,74+(index//2)*462))
    sheet.save(OUT/'comparison_sheet.jpg',quality=95)
    report=dict(model='edgeai-lab/valorant-center400-yolo11s',revision='116b979aa0913d1bfe4ef3714a52434721dbebf5',
                checkpoint_sha256=manifest['best.pt']['sha256'],thresholds=config['confidence'],
                selection='Deterministic scene-stratified selection before inference: six enemy examples, one teammate, one empty crop.',
                samples=summary)
    (OUT/'predictions.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'output':str(OUT),'samples':len(summary),'matched':sum(x['matched'] for x in summary),
                      'missed':sum(x['missed'] for x in summary),'false_positives':sum(x['false_positives'] for x in summary)},indent=2))


if __name__=='__main__':main()
