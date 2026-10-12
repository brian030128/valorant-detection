"""Test two-class checkpoints with frozen published thresholds and native padding."""
import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path
import time
from PIL import Image,ImageDraw,ImageOps
from analyze_detection_failures import match,rates

NAMES=['enemy_body','enemy_head']
COLORS=['#ef72ff','#ffe04b']

def summarize(records,thresholds):
    counts=[[0,0,0] for _ in NAMES];sizes=defaultdict(lambda:[0,0]);errors=[];empty_fp=0
    for r in records:
        preds=[p for p in r['predictions'] if p['confidence']>=thresholds[NAMES[p['class_id']]]]
        matched,_,false=match(r['truth'],preds,0)
        for i,t in enumerate(r['truth']):
            counts[t['class_id']][0 if i in matched else 2]+=1
            if t['class_id']==1:
                b=t['box'];side=min(b[2]-b[0],b[3]-b[1]);bucket='<8px' if side<8 else '8-16px' if side<16 else '16-32px' if side<32 else '>=32px'
                sizes[bucket][1]+=1;sizes[bucket][0]+=int(i in matched)
            if i not in matched:errors.append(dict(stem=r['stem'],kind='miss',class_name=NAMES[t['class_id']]))
        for i in false:
            counts[preds[i]['class_id']][1]+=1
            errors.append(dict(stem=r['stem'],kind='false_positive',class_name=NAMES[preds[i]['class_id']]))
        if not r['truth']:empty_fp+=len(preds)
    return dict(images=len(records),metrics={name:rates(c) for name,c in zip(NAMES,counts)},errors=errors,
                head_sizes={s:dict(detected=n,total=d,recall=n/d) for s,(n,d) in sizes.items()},
                empty_images=sum(not r['truth'] for r in records),empty_frame_detections=empty_fp)

def draw_boxes(im,objects,predictions=False):
    im=im.copy();d=ImageDraw.Draw(im)
    for o in objects:
        color=COLORS[o['class_id']];b=o['box'];d.rectangle(b,outline=color,width=2)
        title=NAMES[o['class_id']]+(f" {o['confidence']:.2f}" if predictions else '')
        d.text((max(0,b[0]),max(0,b[1]-12)),title,fill=color,stroke_width=1,stroke_fill='black')
    return im

def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();root=args.dataset.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    config=json.loads((args.model/'thresholds.json').read_text());audit=json.loads((root/'audit.json').read_text())
    assert audit['class_names']==NAMES and config['classes']=={str(i):n for i,n in enumerate(NAMES)}
    assert config['padding']==[8]*4 and config['input_size']==416 and config['nms_iou']==.7
    identity=dict(model_sha256=hashlib.sha256((args.model/'best.pt').read_bytes()).hexdigest(),audit_sha256=hashlib.sha256((root/'audit.json').read_bytes()).hexdigest(),config=config)
    cache=out/'predictions.json'
    if cache.exists():
        saved=json.loads(cache.read_text());assert saved['identity']==identity;records=saved['records']
    else:
        import torch
        from ultralytics import YOLO
        torch.set_num_threads(4);model=YOLO(args.model/'best.pt');assert list(model.names.values())==NAMES
        annotations=[json.loads(line) for line in (root/'annotations.jsonl').read_text().splitlines()]
        annotations=sorted((a for a in annotations if a['split']=='test'),key=lambda a:a['index']);records=[];started=time.time()
        for start in range(0,len(annotations),8):
            batch=annotations[start:start+8];inputs=[]
            for a in batch:
                im=Image.open(root/f"images/test/{a['index']}.jpg").convert('RGB');assert im.size==(400,400)
                inputs.append(ImageOps.expand(im,8,fill=(114,114,114)))
            results=model.predict(inputs,imgsz=416,device=0,conf=.001,iou=.7,max_det=config['max_det'],verbose=False)
            for a,result in zip(batch,results):
                meta=json.loads((root/f"metadata/test/{a['index']}.json").read_text())
                roles={actor['role'] for actor in meta['actors']}
                scene_type='teammate' if roles=={'teammate'} else 'background' if not roles else 'enemy'
                preds=[dict(class_id=int(c),confidence=float(score),box=[float(x)-8 for x in box]) for box,score,c in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist())]
                records.append(dict(stem=str(a['index']),scene=a['scene_family'],scene_type=scene_type,image_path=str(root/f"images/test/{a['index']}.jpg"),
                                    truth=[dict(class_id=NAMES.index(o['class']),box=o['bbox_xyxy'],character=o['character']) for o in a['objects']],predictions=preds))
            if start%200==0:print('PREDICTED',min(start+8,len(annotations)),len(annotations),flush=True)
        cache.write_text(json.dumps(dict(identity=identity,records=records,elapsed_seconds=time.time()-started)))
    thresholds=config['confidence'];report=summarize(records,thresholds);report.update(identity=identity,thresholds=thresholds,matching_iou=.5)
    report['fixed_confidence_05']=summarize(records,{n:.5 for n in NAMES})['metrics']
    report['negative_groups']={}
    for kind in ['teammate','background']:
        subset=[r for r in records if r.get('scene_type')==kind]
        if not subset:continue
        assert all(not r['truth'] for r in subset)
        false_frames=sum(any(p['confidence']>=thresholds[NAMES[p['class_id']]] for p in r['predictions']) for r in subset)
        report['negative_groups'][kind]=dict(images=len(subset),frames_with_false_detection=false_frames,
                                             frame_false_positive_rate=false_frames/len(subset))
    report['maps']={scene:summarize([r for r in records if r['scene']==scene],thresholds) for scene in sorted({r['scene'] for r in records})}
    report['point_estimate_99_met']=all(m['precision'] is not None and m['recall'] is not None and min(m['precision'],m['recall'])>=.99 for m in report['metrics'].values())
    (out/'results.json').write_text(json.dumps(report,indent=2))
    page='<!doctype html><meta charset="utf-8"><title>Enemy anatomy model test</title><style>body{background:#202025;color:white;font:18px sans-serif;margin:24px}img{max-width:100%}td,th{padding:8px;border:1px solid #777}</style><h1>Enemy torso/head model test</h1><p>Native 400px crops, padded to 416. Published confidence thresholds; class-aware IoU ≥ 0.50. No test tuning. Synthetic images on known map assets, not real-game accuracy.</p><table><tr><th>Class</th><th>Precision</th><th>Recall</th><th>TP / FP / FN</th></tr>'
    for n,m in report['metrics'].items():page+=f"<tr><td>{n}</td><td>{m['precision']:.2%}</td><td>{m['recall']:.2%}</td><td>{m['tp']} / {m['fp']} / {m['fn']}</td></tr>"
    page+='</table><h2>Diagnostic examples</h2><p>One failure-prioritized frame per map. Ground truth left, predictions right. Pink: torso; yellow: head. These examples are not random samples.</p>'
    failures={e['stem'] for e in report['errors']}
    for scene in report['maps']:
        subset=[r for r in records if r['scene']==scene and r['truth']];r=next((r for r in subset if r['stem'] in failures),subset[0])
        im=Image.open(r['image_path']).convert('RGB');canvas=Image.new('RGB',(800,425),'#202025')
        canvas.paste(draw_boxes(im,r['truth']),(0,25));canvas.paste(draw_boxes(im,[p for p in r['predictions'] if p['confidence']>=thresholds[NAMES[p['class_id']]]],True),(400,25))
        ImageDraw.Draw(canvas).text((8,6),f"{scene} / {r['stem']} | ground truth left; predictions right",fill='white')
        canvas.save(out/f'{scene}.jpg',quality=95);page+=f'<h3>{html.escape(scene)}</h3><img src="{scene}.jpg">'
    (out/'index.html').write_text(page,encoding='utf-8');print(json.dumps(report['metrics'],indent=2),flush=True)

if __name__=='__main__':main()
