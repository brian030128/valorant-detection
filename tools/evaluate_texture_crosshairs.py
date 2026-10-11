"""Paired texture and HUD stress test; native pixels, frozen model thresholds, visible-only labels."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageOps
import torch
from ultralytics import YOLO
import evaluate_map_shift as maps
from evaluate_center_goal import evaluate
from analyze_detection_failures import match,font
from preview_trained_center_model import annotated

NAMES=['enemy','teammate','head']
STYLES=['none','green_dot','white_cross','cyan_open','purple_large','outlined_white']


def overlay(style):
    im=Image.new('RGBA',(400,400));d=ImageDraw.Draw(im)
    if style=='green_dot':d.rectangle((199,199,201,201),fill='#00ff00')
    elif style=='white_cross':
        d.rectangle((194,200,206,200),fill='white');d.rectangle((200,194,200,206),fill='white')
    elif style in ['cyan_open','purple_large','outlined_white']:
        gap,length,width,color=(3,6,2,'#00ffff') if style=='cyan_open' else (2,12,3,'#b04dbe') if style=='purple_large' else (3,6,2,'white')
        lo=200-width//2;hi=lo+width-1
        boxes=[(200-gap-length,lo,199-gap,hi),(201+gap,lo,200+gap+length,hi),(lo,200-gap-length,hi,199-gap),(lo,201+gap,hi,200+gap+length)]
        if style=='outlined_white':
            for x0,y0,x1,y1 in boxes:d.rectangle((x0-1,y0-1,x1+1,y1+1),fill='black')
        for b in boxes:d.rectangle(b,fill=color)
    return im


def adjusted_truth(base,annotation,pixels,occluder):
    truth=[];head_overlap=False;body_overlap=False;hidden_heads=0
    for target,obj in zip(base['truth'],annotation['objects']):
        selected=np.abs(pixels[:,:,0].astype(int)-obj['instance_id']*32)<=3
        if target['class_id']==2:selected &= pixels[:,:,1]>127
        overlap=bool(np.any(selected & occluder))
        if target['class_id']==2:head_overlap |= overlap
        else:body_overlap |= overlap
        selected &= ~occluder
        yy,xx=np.where(selected)
        if not len(xx):
            hidden_heads+=int(target['class_id']==2)
            continue
        box=[int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1]
        side=min(box[2]-box[0],box[3]-box[1]);size='<8px' if side<8 else '8-16px' if side<16 else '16-32px' if side<32 else '>=32px'
        truth.append(dict(target,box=box,size_bin=size,visible_pixels=len(xx)))
    return truth,head_overlap,body_overlap,hidden_heads


def summary(records,thresholds):
    metrics,_=evaluate(records,thresholds)
    return dict(images=len(records),metrics=metrics,empty_images=sum(not r['truth'] for r in records),empty_frame_detections=sum(len(r['predictions']) for r in records if not r['truth']))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--textured',type=Path,required=True);p.add_argument('--flat',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hud-source',choices=['textured','flat'],default='textured')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    config=json.loads((a.model/'thresholds.json').read_text());thresholds={i:config['confidence'][n] for i,n in enumerate(NAMES)}
    assert config['input_size']==416 and config['padding']==[8]*4 and config['nms_iou']==.7 and config['max_det']==100
    annotations={str(x['index']):x for x in map(json.loads,(a.textured/'annotations.jsonl').read_text().splitlines())}
    assert len(annotations)==4000
    for stem in annotations:
        left=a.flat/'masks/test'/f'{stem}.png';right=a.textured/'masks/test'/f'{stem}.png'
        assert hashlib.sha256(left.read_bytes()).digest()==hashlib.sha256(right.read_bytes()).digest(),stem
        assert (a.flat/'images/test'/f'{stem}.jpg').read_bytes()!=(a.textured/'images/test'/f'{stem}.jpg').read_bytes(),f'No material change: {stem}'
        m=json.loads((a.flat/'metadata/test'/f'{stem}.json').read_text());n=json.loads((a.textured/'metadata/test'/f'{stem}.json').read_text())
        m.pop('texture_condition');n.pop('texture_condition');assert m==n,stem
    print('4000_TEXTURE_PAIRS_IDENTICAL_GEOMETRY_MASKS_AND_POSES',flush=True)
    maps.MODEL=a.model.resolve();maps.OUT=a.output.resolve()
    torch.set_num_threads(4);model=YOLO(str(a.model/'best.pt'));assert list(model.names.values())==NAMES
    flat=maps.records(a.flat.resolve(),model,thresholds);base=maps.records(a.textured.resolve(),model,thresholds)
    assert all(x['truth']==y['truth'] for x,y in zip(flat,base))
    report=dict(model_revision=json.loads((a.model/'download_provenance.json').read_text())['revision'],checkpoint_sha256=hashlib.sha256((a.model/'best.pt').read_bytes()).hexdigest(),thresholds=config['confidence'],protocol='4000 paired flat/textured images, four new procedural geometry families, 20 layout seeds each. Original held-out poses replayed. Five opaque synthetic center crosshairs plus no-HUD control. No training or threshold tuning. HUD pixels removed from visible-only masks; fully covered objects omitted.',limitations='Procedural material patterns, not photographic textures or captured game HUD. Replayed poses/layouts are correlated; this is not a real-game accuracy certification.',flat=summary(flat,thresholds),textured=summary(base,thresholds),maps={},crosshairs={})
    for family in sorted({r['scene'] for r in base}):
        report['maps'][family]={condition:summary([r for r in records if r['scene']==family],thresholds) for condition,records in [('flat',flat),('textured',base)]}
    texture_base=base
    report['hud_source']=a.hud_source
    if a.hud_source=='flat':base=flat
    all_records={'none':base};identity=dict(hud_source=a.hud_source,model_sha=report['checkpoint_sha256'],dataset_sha=hashlib.sha256((a.textured/'audit.json').read_bytes()).hexdigest(),thresholds=config['confidence'],implementation_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    for style in STYLES:
        hud=overlay(style);hud.save(a.output/f'crosshair_{style}.png');occluder=np.asarray(hud)[:,:,3]==255
        if style=='none':
            report['crosshairs'][style]=summary(base,thresholds);continue
        cache=a.output/f'predictions_{style}.json'
        if cache.exists():
            saved=json.loads(cache.read_text());assert saved['identity']==identity;records=saved['records']
        else:
            records=[]
            for start in range(0,len(base),8):
                batch=base[start:start+8];inputs=[];batch_records=[]
                for r in batch:
                    im=Image.open(r['image_path']).convert('RGBA');im.alpha_composite(hud)
                    inputs.append(ImageOps.expand(im.convert('RGB'),border=8,fill=(114,114,114)))
                    pixels=np.asarray(Image.open(a.textured/'masks/test'/f"{r['stem']}.png").convert('RGB'))
                    truth,head,body,hidden=adjusted_truth(r,annotations[r['stem']],pixels,occluder)
                    batch_records.append(dict(r,truth=truth,head_overlap=head,body_overlap=body,fully_hidden_heads=hidden,predictions=[]))
                results=model.predict(inputs,imgsz=416,device=0,conf=.001,iou=.7,max_det=100,verbose=False)
                for r,result in zip(batch_records,results):
                    for raw in result.boxes:
                        cls=int(raw.cls.item());confidence=float(raw.conf.item())
                        if confidence>=thresholds[cls]:r['predictions'].append(dict(class_id=cls,confidence=confidence,box=(raw.xyxy[0]-8).clamp(0,400).tolist()))
                    records.append(r)
                if start%400==0:print('HUD_PROGRESS',style,min(start+8,len(base)),len(base),flush=True)
            cache.write_text(json.dumps(dict(identity=identity,records=records)))
        all_records[style]=records
        head=[r for r in records if r['head_overlap']];stems={r['stem'] for r in head}
        report['crosshairs'][style]=dict(**summary(records,thresholds),head_overlap=summary(head,thresholds),same_frames_without_crosshair=summary([r for r in base if r['stem'] in stems],thresholds),fully_hidden_heads=sum(r['fully_hidden_heads'] for r in records),body_overlap_images=sum(r['body_overlap'] for r in records),opaque_pixels=int(occluder.sum()))
        # Also retain fixed pre-HUD labels for a transparent comparison of scoring policies.
        fixed=[dict(r,truth=control['truth']) for r,control in zip(records,base)]
        report['crosshairs'][style]['fixed_pre_hud_labels']=summary(fixed,thresholds)
    (a.output/'results.json').write_text(json.dumps(report,indent=2))
    def error_count(r):
        m,_,f=match(r['truth'],r['predictions'],0);return len(r['truth'])-len(m)+len(f)
    # Diagnostic failure selection, plus a deterministic centered-head example when available.
    candidates=[r for r in all_records['purple_large'] if r['head_overlap']]
    selected=sorted(candidates,key=lambda r:(error_count(r)-error_count(base[next(i for i,b in enumerate(base) if b['stem']==r['stem'])]),r['stem']),reverse=True)[:2]
    if not selected:selected=base[:2]
    rows=[]
    lookup={style:{r['stem']:r for r in records} for style,records in all_records.items()}
    for chosen in selected:
        canvas=Image.new('RGB',(1200,880),'#111b29');d=ImageDraw.Draw(canvas)
        for j,style in enumerate(STYLES):
            r=lookup[style][chosen['stem']];im=Image.open(r['image_path']).convert('RGBA');im.alpha_composite(overlay(style))
            tile=annotated(im.convert('RGB'),r['predictions'],True);x=(j%3)*400;y=(j//3)*440
            d.text((x+5,y+5),f"{style} | {r['stem']}",font=font(16),fill='white');canvas.paste(tile,(x,y+35))
        canvas.save(a.output/f"hud_example_{chosen['stem']}.jpg",quality=95);rows.append(f"hud_example_{chosen['stem']}.jpg")
    base=texture_base
    sheet=Image.new('RGB',(1200,1760),'#111b29');d=ImageDraw.Draw(sheet)
    for i,family in enumerate(sorted(report['maps'])):
        ids=[j for j,r in enumerate(base) if r['scene']==family]
        j=max(ids,key=lambda j:error_count(base[j])-error_count(flat[j]))
        for k,(title,r,truth) in enumerate([('Flat: predictions',flat[j],False),('Texture: ground truth',base[j],True),('Texture: predictions',base[j],False)]):
            d.text((k*400+5,i*440+5),f'{family}: {title}',font=font(13),fill='white')
            im=Image.open(r['image_path']).convert('RGB');sheet.paste(annotated(im,r['truth'] if truth else r['predictions'],not truth),(k*400,i*440+35))
    sheet.save(a.output/'texture_comparison.jpg',quality=95)
    def table(items):
        rows=[]
        for name,v in items:
            for cls,m in v['metrics'].items():
                precision='N/A' if m['precision'] is None else f"{m['precision']:.2%}"
                recall='N/A' if m['recall'] is None else f"{m['recall']:.2%}"
                rows.append(f"<tr><td>{name}</td><td>{cls}</td><td>{precision}</td><td>{recall}</td><td>{m['fp']}</td><td>{m['fn']}</td></tr>")
        return '<table><tr><th>Condition</th><th>Class</th><th>Precision</th><th>Recall</th><th>FP</th><th>FN</th></tr>'+''.join(rows)+'</table>'
    page='<!doctype html><meta charset="utf-8"><title>Texture and crosshair test</title><style>body{background:#111b29;color:white;font:16px system-ui;margin:24px}td,th{padding:8px;border-bottom:1px solid gray}img{max-width:100%}</style><h1>Texture and crosshair test</h1><p>'+report['protocol']+'</p><p>'+report['limitations']+'</p>'
    page+='<h2>Texture comparison</h2>'+table([('Flat',report['flat']),('Textured',report['textured'])])
    for family,conditions in report['maps'].items():page+='<h3>'+family+'</h3>'+table(conditions.items())
    page+='<h2>Crosshair results on '+a.hud_source+' scenes</h2>'+table(report['crosshairs'].items())
    for style in STYLES[1:]:
        r=report['crosshairs'][style];page+=f"<h3>{style}: {r['head_overlap']['images']} head-overlap images; {r['fully_hidden_heads']} fully hidden heads</h3>"+table([('Same frames, no HUD',r['same_frames_without_crosshair']),('HUD, visible-only labels',r['head_overlap'])])
    page+='<h2>Diagnostic texture examples</h2><p>Selected for increased errors, not random samples.</p><img src="texture_comparison.jpg"><h2>Crosshair predictions</h2><p>Selected head-overlap cases with increased errors. Full counts above include all frames.</p>'+''.join(f'<img src="{name}">' for name in rows)
    (a.output/'index.html').write_text(page,encoding='utf-8');print('TEXTURE_HUD_EVALUATION_COMPLETE',flush=True)

if __name__=='__main__':main()
