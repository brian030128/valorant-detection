"""Frozen-model, paired-map test with visibility-controlled comparisons and examples."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from PIL import Image,ImageOps,ImageDraw
import torch
from ultralytics import YOLO
from analyze_detection_failures import match,font,iou
from evaluate_center_goal import evaluate, wilson
from preview_trained_center_model import annotated

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/'datasets/valorant_center400_10k'
NEW=ROOT/'datasets/valorant_mapshift_4000'
MODEL=ROOT/'models/valorant-center400-yolo11s'
OUT=ROOT/'runs/analysis/map_shift'
NAMES=['enemy','teammate','head']


def records(dataset,model,thresholds):
    source=[json.loads(line) for line in (dataset/'annotations.jsonl').read_text().splitlines()]
    source=sorted((a for a in source if a['split']=='test'),key=lambda a:a['index'])
    cache=OUT/(dataset.name+'_predictions.json')
    identity=dict(model_sha256=hashlib.sha256((MODEL/'best.pt').read_bytes()).hexdigest(),
                  audit_sha256=hashlib.sha256((dataset/'audit.json').read_bytes()).hexdigest(),thresholds={str(k):v for k,v in thresholds.items()})
    if cache.exists():
        saved=json.loads(cache.read_text())
        assert saved['identity']==identity
        return saved['records']
    output=[]
    for start in range(0,len(source),8):
        batch=source[start:start+8]
        inputs=[]
        for a in batch:
            im=Image.open(dataset/'images/test'/f"{a['index']:06d}.jpg").convert('RGB')
            assert im.size==(400,400)
            inputs.append(ImageOps.expand(im,border=8,fill=(114,114,114)))
        results=model.predict(inputs,imgsz=416,device=0,conf=.001,iou=.7,max_det=100,verbose=False)
        for a,result in zip(batch,results):
            stem=f"{a['index']:06d}"
            meta=json.loads((dataset/'metadata/test'/f'{stem}.json').read_text())
            truth=[]
            for obj in a['objects']:
                box=obj['bbox_xyxy'];side=min(box[2]-box[0],box[3]-box[1])
                size='<8px' if side<8 else '8-16px' if side<16 else '16-32px' if side<32 else '>=32px'
                truth.append(dict(class_id=NAMES.index(obj['class']),box=box,size_bin=size,
                                  character=obj['character'],view='replayed',visible_pixels=obj['visible_pixels']))
            predictions=[]
            for raw in result.boxes:
                cls=int(raw.cls.item());confidence=float(raw.conf.item())
                if confidence>=thresholds[cls]:
                    predictions.append(dict(class_id=cls,confidence=confidence,box=(raw.xyxy[0]-8).clamp(0,400).tolist()))
            output.append(dict(stem=stem,source_index=meta.get('source_index',a['index']),scene=a['scene_family'],
                               scene_group=a['scene_group'],truth=truth,predictions=predictions,image_path=str(dataset/'images/test'/f'{stem}.jpg')))
        if start%200==0:print(f'PREDICTED {dataset.name} {min(start+8,len(source))}/{len(source)}',flush=True)
    cache.write_text(json.dumps(dict(identity=identity,records=output)))
    return output


def visibility(record):
    original=np.array(Image.open(ORIGINAL/'masks/test'/f"{record['source_index']:06d}.png").convert('RGB'))
    new=np.array(Image.open(NEW/'masks/test'/f"{record['stem']}.png").convert('RGB'))
    scores=[]
    for head in [False,True]:
        a=original[:,:,0]>15;b=new[:,:,0]>15
        if head:a=a & (original[:,:,1]>127);b=b & (new[:,:,1]>127)
        union=int((a|b).sum());intersection=int((a&b).sum())
        scores.append(intersection/union if union else 1.)
    return dict(body_mask_iou=scores[0],head_mask_iou=scores[1],same_visibility=min(scores)>=.95)


def metrics_table(items):
    rows=[]
    for label,metrics in items:
        for name,m in metrics.items():
            rows.append(f'<tr><td>{label}</td><td>{name}</td><td>{m["precision"]:.2%}</td><td>{m["recall"]:.2%}</td><td>{m["fp"]}</td><td>{m["fn"]}</td></tr>')
    return '<table><tr><th>Map</th><th>Class</th><th>Precision</th><th>Recall</th><th>False positives</th><th>Missed</th></tr>'+''.join(rows)+'</table>'


def main():
    global ORIGINAL, NEW, MODEL, OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,default=ORIGINAL)
    parser.add_argument('--dataset',type=Path,default=NEW)
    parser.add_argument('--model',type=Path,default=MODEL)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--training-dataset',type=Path,help='Assert that challenge scene families are absent from this training audit.')
    args=parser.parse_args();ORIGINAL=args.original.resolve();NEW=args.dataset.resolve();MODEL=args.model.resolve();OUT=args.output.resolve()
    if args.training_dataset:
        trained=set(json.loads((args.training_dataset/'audit.json').read_text())['scene_families']['train'])
        tested=set(json.loads((NEW/'audit.json').read_text())['scene_families']['test'])
        assert not trained&tested, f'Training families reused: {trained&tested}'
    for path in NEW.glob('metadata/test/*.json'):
        meta=json.loads(path.read_text())
        source=json.loads((ORIGINAL/'metadata/test'/f"{meta['source_index']:06d}.json").read_text())
        assert meta['split']==source['split']=='test'
        for key in ['camera_position','camera_rotation_degrees']:
            assert np.allclose(meta[key],source[key],rtol=0,atol=1e-10)
        assert len(meta['actors'])==len(source['actors'])
        for actor,old in zip(meta['actors'],source['actors']):
            for key in ['character','role','animation','instance_id']:assert actor[key]==old[key]
            for key in ['position','yaw','scale','animation_time']:
                assert np.allclose(actor[key],old[key],rtol=0,atol=1e-10)
    OUT.mkdir(parents=True,exist_ok=True)
    config=json.loads((MODEL/'thresholds.json').read_text())
    thresholds={c:config['confidence'][name] for c,name in enumerate(NAMES)}
    assert config['nms_iou']==.7 and config['max_det']==100 and config['input_size']==416 and config['padding']==[8,8,8,8]
    torch.set_num_threads(4)
    model=YOLO(str(MODEL/'best.pt'));assert list(model.names.values())==NAMES
    original=records(ORIGINAL,model,thresholds)
    new=records(NEW,model,thresholds)
    assert len(original)==1000 and len(new)==4000
    by_source={int(r['stem']):r for r in original}
    baseline,_=evaluate(original,thresholds)
    published=json.loads((MODEL/'evaluation.json').read_text())['test_metrics']
    reproduced=all(baseline[c][key]==published[c][key] for c in NAMES for key in ['tp','fp','fn'])
    report=dict(model='edgeai-lab/valorant-center400-yolo11s',checkpoint_sha256=hashlib.sha256((MODEL/'best.pt').read_bytes()).hexdigest(),
                thresholds=config['confidence'],matching_iou=.5,baseline=baseline,baseline_reproduces_published_counts=reproduced,
                protocol='Four new geometry/palette families, 20 layout seeds each. Original held-out camera, poses, characters, roles, scale, animations and lighting replayed. No training or threshold tuning. One actor per positive source frame. New cover can change visibility.',
                visibility_control='Per-map subset whose body AND head foreground masks have IoU >= 0.95 with original masks; includes original/new empty pairs. Compare against the same source subset.',maps={})
    provenance=MODEL/'download_provenance.json'
    if provenance.exists():report['model_provenance']=json.loads(provenance.read_text())
    report['dataset']=str(NEW)
    report['training_family_disjointness_checked']=bool(args.training_dataset)
    report['aggregate_metrics'],report['aggregate_errors']=evaluate(new,thresholds)
    for metric in report['aggregate_metrics'].values():
        metric['precision_95pct_wilson']=wilson(metric['tp'],metric['tp']+metric['fp'])
        metric['recall_95pct_wilson']=wilson(metric['tp'],metric['tp']+metric['fn'])
    report['uncertainty_note']='Frames share scene layouts and source poses across maps; intervals describe object counts and do not certify independent-sample 99% reliability.'
    tiles=[]
    for family in sorted({r['scene'] for r in new}):
        subset=[r for r in new if r['scene']==family]
        for r in subset:r.update(visibility(r))
        metrics,errors=evaluate(subset,thresholds)
        stable=[r for r in subset if r['same_visibility']]
        stable_original=[by_source[r['source_index']] for r in stable]
        stable_metrics,_=evaluate(stable,thresholds)
        stable_baseline,_=evaluate(stable_original,thresholds)
        report['maps'][family]=dict(images=len(subset),metrics=metrics,errors=errors,
                                   same_visibility_images=len(stable),same_visibility_metrics=stable_metrics,
                                   same_visibility_baseline=stable_baseline,
                                   recall_change_pp={name:100*(stable_metrics[name]['recall']-stable_baseline[name]['recall']) for name in NAMES},
                                   visibility_changed_images=len(subset)-len(stable),
                                   empty_images=sum(not r['truth'] for r in subset),
                                   failure_counts=dict(Counter(f"{e['class_name']} / {e['kind']} / {e.get('size','')}" for e in errors)))
        false_teammate_categories=Counter();high_confidence_false_teammates=0
        for r in subset:
            _,_,false=match(r['truth'],r['predictions'],0)
            for index in false:
                pred=r['predictions'][index]
                if pred['class_id']!=1:continue
                overlap,cls=max(((iou(pred['box'],target['box']),target['class_id']) for target in r['truth'] if target['class_id']!=2),default=(0,-1))
                kind='enemy_class_confusion' if overlap>=.5 and cls==0 else 'duplicate_teammate' if overlap>=.5 else 'poor_localization_or_partial_overlap' if overlap>0 else 'background_no_body_overlap'
                false_teammate_categories[kind]+=1
                high_confidence_false_teammates+=int(pred['confidence']>=.9)
        report['maps'][family]['false_teammate_categories']=dict(false_teammate_categories)
        report['maps'][family]['false_teammates_confidence_ge_090']=high_confidence_false_teammates
        size_counts={}
        for r in subset:
            matched,_,_=match(r['truth'],r['predictions'],0)
            for i,t in enumerate(r['truth']):
                if t['class_id']!=2:continue
                counts=size_counts.setdefault(t['size_bin'],dict(total=0,detected=0))
                counts['total']+=1;counts['detected']+=int(i in matched)
        report['maps'][family]['head_recall_by_size']={k:dict(**v,recall=v['detected']/v['total']) for k,v in size_counts.items()}
        report['maps'][family]['empty_frame_false_detections']=sum(len(r['predictions']) for r in subset if not r['truth'])
        def failure_score(r):
            matched,correct,false=match(r['truth'],r['predictions'],0)
            return len(r['truth'])-len(matched)+len(false)
        failures=[r for r in stable if failure_score(r)>0]
        chosen=max(failures or subset,key=lambda r:(failure_score(r)-failure_score(by_source[r['source_index']]),failure_score(r),len(r['truth'])))
        control=by_source[chosen['source_index']]
        tile=Image.new('RGB',(1232,476),'#111b29');draw=ImageDraw.Draw(tile)
        draw.text((8,6),f"{family} | source {chosen['source_index']:06d} | {'visibility matched' if chosen['same_visibility'] else 'visibility changed'}",font=font(22),fill='white')
        for i,(label,record,boxes,pred) in enumerate([
            ('Original map: predictions',control,control['predictions'],True),
            ('New map: ground truth',chosen,chosen['truth'],False),
            ('New map: predictions',chosen,chosen['predictions'],True)]):
            draw.text((i*416+5,38),label,font=font(17),fill='#d8e8ff')
            im=Image.open(record['image_path']).convert('RGB')
            tile.paste(annotated(im,boxes,pred),(i*416,70))
        tile.save(OUT/f'{family}_example.png');tiles.append(tile)
    sheet=Image.new('RGB',(1232,476*len(tiles)),'#111b29')
    for i,tile in enumerate(tiles):sheet.paste(tile,(0,476*i))
    sheet.save(OUT/'map_comparison.jpg',quality=95)
    (OUT/'results.json').write_text(json.dumps(report,indent=2))
    (OUT/'new_map_predictions_with_visibility.json').write_text(json.dumps(new))
    page='<!doctype html><meta charset="utf-8"><title>New-map robustness test</title><style>body{background:#111b29;color:#e4edf8;font:16px system-ui;max-width:1300px;margin:24px auto}table{border-collapse:collapse}td,th{padding:8px 18px;border-bottom:1px solid #456}a{color:#8cdaff}img{max-width:100%}</style><h1>New-map robustness test</h1>'
    page+='<p>'+report['protocol']+'</p><p>Frozen thresholds: '+', '.join(f'{name} {value:.2f}' for name,value in config['confidence'].items())+'. Correct class and IoU >= .50 required. Synthetic tests only; per-map samples share poses and scene groups.</p>'
    page+=metrics_table([('Original test',baseline),('All new maps',report['aggregate_metrics'])]+[(name,m['metrics']) for name,m in report['maps'].items()])
    page+='<h2>Visibility-controlled comparisons</h2><p>'+report['visibility_control']+'</p>'
    for name,m in report['maps'].items():
        page+=f'<h3>{name}: {m["same_visibility_images"]} comparable images</h3>'+metrics_table([('Same original frames',m['same_visibility_baseline']),('New map',m['same_visibility_metrics'])])
    page+='<h2>Selected failure examples</h2><p>Examples prioritize errors with unchanged visibility; these are diagnostic examples, not random samples. Pink: enemy, cyan: teammate, yellow: head.</p><img src="map_comparison.jpg">'
    (OUT/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['maps','aggregate_errors']},indent=2))
    for name,m in report['maps'].items():print(json.dumps(dict(map=name,**{k:v for k,v in m.items() if k not in ['errors','failure_counts']}),indent=2))


if __name__=='__main__':main()
