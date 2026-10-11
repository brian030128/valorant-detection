"""Cache validation predictions, compare fixed thresholds, and create a local failure gallery."""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['enemy', 'teammate', 'head']
DATA = ROOT / 'datasets/valorant_synthetic_10k'
SPLIT = 'val'
SIZE_SCALE = .5


def iou(a, b):
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return overlap / max(1e-12, (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap)


def match(truth, predictions, threshold):
    matched, correct, false = {}, set(), []
    for pidx in sorted(range(len(predictions)), key=lambda x: -predictions[x]['confidence']):
        pred = predictions[pidx]
        if pred['confidence'] < threshold:
            continue
        candidates = [(iou(pred['box'], target['box']), tidx) for tidx, target in enumerate(truth)
                      if target['class_id'] == pred['class_id'] and tidx not in matched]
        overlap, tidx = max(candidates, default=(0, -1))
        if overlap >= .5:
            matched[tidx] = pidx
            correct.add(pidx)
        else:
            false.append(pidx)
    return matched, correct, false


def rates(count):
    tp, fp, fn = map(int, count)
    return dict(tp=tp, fp=fp, fn=fn, precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None)


def size_bin(box):
    # Fixed 960 reference scale, independent of evaluated inference resolution.
    side = min(box[2]-box[0], box[3]-box[1]) * SIZE_SCALE
    return '<8px' if side < 8 else '8-16px' if side < 16 else '16-32px' if side < 32 else '>=32px'


def collect(checkpoint, imgsz, output):
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(4)
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    key = dict(checkpoint_sha256=sha, imgsz=imgsz, conf=.001, nms_iou=.7, max_det=100, split=SPLIT,
               dataset_audit_sha256=hashlib.sha256((DATA/'audit.json').read_bytes()).hexdigest())
    cache = output/'predictions.json'
    if cache.exists():
        previous = json.loads(cache.read_text())
        if previous['configuration'] == key:
            return previous
        raise RuntimeError('Output contains predictions from a different configuration; use another output directory.')
    images = sorted(p for p in (DATA/'images'/SPLIT).iterdir() if p.suffix.lower() in ['.jpg','.png'])
    annotations = {}
    for line in (DATA/'annotations.jsonl').read_text().splitlines():
        item = json.loads(line)
        if item['split'] == SPLIT:
            annotations[f"{item['index']:06d}"] = item
    records = []
    started = time.time()
    model = YOLO(str(checkpoint))
    assert list(model.names.values()) == NAMES
    source = output/'validation_images.txt'
    source.write_text('\n'.join(str(p.resolve()) for p in images), encoding='utf-8')
    results = model.predict(str(source.resolve()), stream=True, imgsz=imgsz, batch=8,
                            device=0, conf=.001, iou=.7, max_det=100, verbose=False)
    for result in results:
        stem = Path(result.path).stem
        annotation = annotations[stem]
        meta = json.loads((DATA/'metadata'/SPLIT/f'{stem}.json').read_text())
        height,width=result.orig_shape
        truth = []
        for row in (DATA/'labels'/SPLIT/f'{stem}.txt').read_text().splitlines():
            cls, cx, cy, w, h = map(float, row.split())
            box = [(cx-w/2)*width, (cy-h/2)*height, (cx+w/2)*width, (cy+h/2)*height]
            obj = max((x for x in annotation['objects'] if x['class'] == NAMES[int(cls)]),
                      key=lambda x: iou(box, x['bbox_xyxy']))
            actor = next(a for a in meta['actors'] if a['instance_id'] == obj['instance_id'])
            dx, dz = meta['camera_position'][0]-actor['position'][0], meta['camera_position'][2]-actor['position'][2]
            angle = abs(math.atan2(math.sin(actor['yaw']-math.atan2(dx,dz)), math.cos(actor['yaw']-math.atan2(dx,dz))))*180/math.pi
            view = 'front' if angle < 22.5 else 'front_oblique' if angle < 67.5 else 'side' if angle < 112.5 else 'rear_oblique' if angle < 157.5 else 'rear'
            truth.append(dict(class_id=int(cls), box=box, character=obj['character'], visible_pixels=obj['visible_pixels'],
                              instance_id=obj['instance_id'], view=view, size_bin=size_bin(box)))
        predictions = [dict(class_id=int(c), confidence=float(s), box=b.tolist())
                       for b, s, c in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.conf.cpu().numpy(), result.boxes.cls.cpu().numpy())]
        records.append(dict(stem=stem, scene=annotation['scene_family'], scene_group=annotation['scene_group'],
                            players=sum(x['class_id'] < 2 for x in truth), truth=truth, predictions=predictions,
                            speed_ms=result.speed, image_path=str(Path(result.path).resolve())))
        if len(records)%100 == 0:
            print(f'PREDICTED {len(records)}/{len(images)} at {imgsz}', flush=True)
    payload = dict(configuration=key, images=records, wall_seconds=time.time()-started)
    cache.write_text(json.dumps(payload), encoding='utf-8')
    return payload


def analyze(payload):
    thresholds = [.05, .1, .15, .2, .25, .3, .35, .4, .45, .5, .55, .6, .65, .7, .75, .8, .85, .9, .95]
    result = {}
    buckets = defaultdict(lambda: [0, 0])  # found, total GT
    failures = []
    for threshold in thresholds:
        groups = {name: np.zeros((3,3), dtype=int) for name in ['all', 'single_player', 'multiple_players', 'empty']}
        for record in payload['images']:
            truth, predictions = record['truth'], record['predictions']
            matched, correct, false = match(truth, predictions, threshold)
            subgroup = 'single_player' if record['players'] == 1 else 'multiple_players' if record['players'] > 1 else 'empty'
            for name in ['all', subgroup]:
                for idx, target in enumerate(truth):
                    groups[name][target['class_id'], 0 if idx in matched else 2] += 1
                for idx in false:
                    groups[name][predictions[idx]['class_id'], 1] += 1
            if threshold != .5:
                continue
            for idx, target in enumerate(truth):
                found = idx in matched
                for dimension, value in [('size',target['size_bin']), ('character',target['character']), ('view',target['view']), ('scene',record['scene'])]:
                    bucket = buckets[(NAMES[target['class_id']], dimension, value)]
                    bucket[0] += int(found)
                    bucket[1] += 1
                if found:
                    continue
                same = [p for p in predictions if p['class_id'] == target['class_id']]
                best = max(same, key=lambda p: iou(p['box'],target['box']), default=None)
                overlap = iou(best['box'], target['box']) if best else 0
                wrong = [p for p in predictions if p['class_id'] != target['class_id'] and p['confidence'] >= .5
                         and (p['class_id'] < 2) == (target['class_id'] < 2) and iou(p['box'], target['box']) >= .5]
                if overlap >= .5 and best['confidence'] < .5:
                    reason = 'below_confidence'
                elif wrong:
                    reason = 'wrong_team_class'
                elif any(p['confidence'] >= .5 and iou(p['box'],target['box']) >= .1 for p in same):
                    reason = 'poor_box_overlap'
                else:
                    reason = 'no_matching_detection'
                failures.append(dict(stem=record['stem'], kind='miss', class_name=NAMES[target['class_id']], reason=reason,
                                     box=target['box'], size=target['size_bin'], character=target['character'], view=target['view'],
                                     best_candidate_iou=overlap, best_candidate_confidence=best['confidence'] if best else None))
            for idx in false:
                pred = predictions[idx]
                same = [t for t in truth if t['class_id'] == pred['class_id']]
                overlap = max((iou(pred['box'],t['box']) for t in same), default=0)
                reason = 'duplicate_detection' if overlap >= .5 else 'poor_box_overlap' if overlap >= .1 else 'unmatched_prediction'
                failures.append(dict(stem=record['stem'], kind='false_positive', class_name=NAMES[pred['class_id']], reason=reason,
                                     box=pred['box'], size=size_bin(pred['box']), confidence=pred['confidence']))
        result[str(threshold)] = {group: {**{NAMES[c]:rates(values[c]) for c in range(3)}, 'micro':rates(values.sum(axis=0))}
                                  for group, values in groups.items()}
    return dict(configuration=payload['configuration'], image_counts=dict(Counter('single_player' if r['players']==1 else 'multiple_players' if r['players']>1 else 'empty' for r in payload['images'])),
                thresholds=result, recall_breakdown=[dict(class_name=c, dimension=d, value=v, found=n, total=t, recall=n/t) for (c,d,v),(n,t) in buckets.items()],
                failure_counts=dict(Counter(f"{f['class_name']} / {f['kind']} / {f['reason']}" for f in failures)),
                failures=failures, mean_inference_ms=float(np.mean([r['speed_ms']['inference'] for r in payload['images']])),
                notes=[f'{SPLIT} split; exploratory threshold sweeps do not constitute held-out guarantees.',
                       'Class-aware one-to-one matching at IoU >= 0.5. Miss and false-positive events can come from the same poorly localized box.',
                       f'Size is visible-box shortest side multiplied by {SIZE_SCALE}; native pixels for center crops.',
                       'Failure reasons are automated heuristics; occlusion fraction cannot be inferred from visible masks alone.'])


def font(size):
    for name in ['C:/Windows/Fonts/arial.ttf','DejaVuSans.ttf']:
        try:return ImageFont.truetype(name,size)
        except OSError:pass
    return ImageFont.load_default(size=size)


def gallery(payload, report, output):
    records = {r['stem']:r for r in payload['images']}
    grouped = defaultdict(list)
    for failure in report['failures']:
        grouped[(failure['class_name'], failure['kind'], failure['reason'],failure['size'])].append(failure)
    for items in grouped.values():
        items.sort(key=lambda item: hashlib.sha256(item['stem'].encode()).hexdigest())
    examples = []
    # Balanced sampling so abundant tiny heads do not hide other failure modes.
    while grouped and len(examples) < 180:
        for key in list(grouped):
            examples.append(grouped[key].pop(0))
            if not grouped[key]: del grouped[key]
            if len(examples) == 180: break
    cards, tiles = [], []
    (output/'gallery').mkdir(exist_ok=True)
    for index, failure in enumerate(examples):
        record = records[failure['stem']]
        original_path=Path(record.get('image_path',str(DATA/'images'/SPLIT/f"{failure['stem']}.jpg")))
        original = Image.open(original_path).convert('RGB')
        x1,y1,x2,y2 = failure['box']
        cx,cy = (x1+x2)/2,(y1+y2)/2
        width,height = max(240,(x2-x1)*1.8), max(200,(y2-y1)*1.5)
        width=max(width,height*1.5); height=width/1.5
        left,top=max(0,cx-width/2),max(0,cy-height/2)
        right,bottom=min(original.width,left+width),min(original.height,top+height)
        bounds=tuple(map(int,(left,top,right,bottom)))
        crop=original.crop(bounds)
        scale=min(600/crop.width,400/crop.height)
        crop=crop.resize((round(crop.width*scale),round(crop.height*scale)))
        tile=Image.new('RGB',(600,470),'#131c28');tile.paste(crop,(0,70));draw=ImageDraw.Draw(tile)
        draw.text((10,6),f"{failure['stem']} | {failure['class_name']} | {failure['kind']}",font=font(19),fill='white')
        draw.text((10,30),f"{failure['reason']} | size {failure['size']}",font=font(17),fill='#e1bf72')
        draw.text((10,51),'GREEN = label    RED = prediction >= 0.50',font=font(15),fill='white')
        def drawbox(box,label,color,below=False):
            a,b,c,d=box
            if c < bounds[0] or a > bounds[2] or d < bounds[1] or b > bounds[3]:return
            a,c=(max(bounds[0],a)-bounds[0])*scale,(min(bounds[2],c)-bounds[0])*scale
            b,d=(max(bounds[1],b)-bounds[1])*scale+70,(min(bounds[3],d)-bounds[1])*scale+70
            draw.rectangle((a,b,c,d),outline=color,width=2)
            draw.text((a,min(450,d+1) if below else max(70,b-17)),label,font=font(14),fill=color,stroke_width=1,stroke_fill='black')
        for target in record['truth']:
            if (target['class_id']==2) == (failure['class_name']=='head'):
                drawbox(target['box'],'GT '+NAMES[target['class_id']],'#54ff86',below=True)
        for pred in record['predictions']:
            if pred['confidence']>=.5 and (pred['class_id']==2) == (failure['class_name']=='head'):
                drawbox(pred['box'],f"{NAMES[pred['class_id']]} {pred['confidence']:.2f}",'#ff6878')
        filename=f'gallery/{index:03d}_{failure["stem"]}.jpg'
        tile.save(output/filename,quality=92)
        if index<12:tiles.append(tile)
        full=Path(os.path.relpath(original_path,output)).as_posix()
        cards.append(f'<article data-class="{failure["class_name"]}" data-kind="{failure["kind"]}" data-reason="{failure["reason"]}"><a href="{full}"><img loading="lazy" src="{filename}"></a><p>{html.escape(failure.get("character", ""))} {html.escape(failure.get("view", ""))} | <a href="{full}">Full image</a></p></article>')
    sheet=Image.new('RGB',(1800,470*math.ceil(len(tiles)/3)),'#131c28')
    for i,tile in enumerate(tiles):sheet.paste(tile,((i%3)*600,(i//3)*470))
    if tiles:sheet.save(output/'contact_sheet.jpg',quality=94)
    rows=''.join(f'<tr><td>{name}</td><td>{m["precision"]:.1%}</td><td>{m["recall"]:.1%}</td><td>{m["fn"]}</td><td>{m["fp"]}</td></tr>' for name,m in report['thresholds']['0.5']['all'].items())
    document='''<!doctype html><meta charset="utf-8"><title>Detection failure review</title><style>body{background:#101722;color:#e7edf6;font:16px system-ui;margin:24px}a{color:#82cfff}table{border-collapse:collapse}td,th{padding:8px 20px;border-bottom:1px solid #435}select{padding:10px;margin:12px 10px 20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:16px}article{background:#1c2737}img{width:100%}p{padding:0 10px}</style><h1>Detection failure review</h1>'''
    document+=f'<p>YOLO {SPLIT} split at {report["configuration"]["imgsz"]} pixels. Confidence ≥ 0.50, class-aware IoU ≥ 0.50. Green boxes are labels; red boxes are predictions. Head-error crops show head boxes; body-error crops show enemy and teammate boxes. Click a crop for its full image.</p><p>{len(report["failures"])} error events; {len(examples)} balanced examples below. A poorly localized prediction can create both a miss and a false positive. Size groups use visible-box shortest side multiplied by {SIZE_SCALE} (native pixels for center crops). These are synthetic results, not real-game accuracy.</p>'
    document+='<table><tr><th>Class</th><th>Precision</th><th>Recall</th><th>Misses</th><th>False positives</th></tr>'+rows+'</table>'
    for attr,options in [('class',NAMES),('kind',['miss','false_positive']),('reason',sorted({f['reason'] for f in examples}))]:
        document+=f'<select id="{attr}" onchange="filter()"><option value="">All {attr}</option>'+''.join(f'<option>{x}</option>' for x in options)+'</select>'
    document+='<div class="grid">'+''.join(cards)+'</div><script>function filter(){document.querySelectorAll("article").forEach(x=>{x.hidden=["class","kind","reason"].some(k=>document.getElementById(k).value&&x.dataset[k]!==document.getElementById(k).value)})}</script>'
    (output/'index.html').write_text(document,encoding='utf-8')


def main():
    global DATA,SPLIT,SIZE_SCALE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,default=ROOT/'runs/train/yolo11n_synthetic_960/weights/best.pt')
    parser.add_argument('--imgsz',type=int,default=960)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dataset',type=Path,default=DATA)
    parser.add_argument('--split',choices=['val','test'],default='val')
    args=parser.parse_args()
    DATA=args.dataset.resolve();SPLIT=args.split
    SIZE_SCALE=1.0 if json.loads((DATA/'audit.json').read_text())['resolution'][0]<=416 else .5
    args.output.mkdir(parents=True,exist_ok=True)
    payload=collect(args.checkpoint,args.imgsz,args.output)
    report=analyze(payload)
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    gallery(payload,report,args.output)
    print(json.dumps(dict(output=str(args.output), images=report['image_counts'], metrics=report['thresholds']['0.5'], failures=report['failure_counts']),indent=2),flush=True)


if __name__=='__main__':main()
