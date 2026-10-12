"""Compare frozen checkpoints on fresh renders of maps used in training, without threshold tuning."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
import torch
from ultralytics import YOLO
import evaluate_map_shift as maps
from evaluate_center_goal import evaluate
from analyze_detection_failures import match
from preview_trained_center_model import annotated


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('--model',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    dataset=args.dataset.resolve();training=args.training.resolve()
    audit=json.loads((dataset/'audit.json').read_text());assert set(audit['splits'])=={'test'}
    train_files=list((training/'images/train').glob('*.jpg'));test_files=list((dataset/'images/test').glob('*.jpg'))
    assert not {f.stem for f in train_files}&{f.stem for f in test_files}
    with ThreadPoolExecutor(max_workers=8) as pool:
        train_hashes=set(pool.map(sha,train_files));test_hashes=set(pool.map(sha,test_files))
    assert not train_hashes&test_hashes
    metadata={p.stem:json.loads(p.read_text()) for p in (dataset/'metadata/test').glob('*.json')}
    report={'images':len(test_files),'training_images_checked':len(train_files),'duplicate_training_images':0,
            'protocol':'Fresh sample indices, camera/pose/lighting/crosshair realizations on the same 11 maps used in training. Sample IDs and image hashes are disjoint from training. Map assets and sampled camera regions/viewpoints are reused; this is not an unseen-map or real-game test.',
            'matching_iou':.5,'threshold_policy':'Each checkpoint uses its own published validation-selected thresholds. No test tuning.',
            'dataset_audit_sha256':sha(dataset/'audit.json'),'models':{}}
    torch.set_num_threads(4)
    for directory in args.model:
        directory=directory.resolve();maps.MODEL=directory;maps.OUT=args.output/directory.name;maps.OUT.mkdir(exist_ok=True)
        config=json.loads((directory/'thresholds.json').read_text())
        assert config['padding']==[8]*4 and config['input_size']==416 and config['nms_iou']==.7 and config['max_det']==100
        thresholds={i:config['confidence'][name] for i,name in enumerate(maps.NAMES)}
        model=YOLO(str(directory/'best.pt'));assert list(model.names.values())==maps.NAMES
        records=maps.records(dataset,model,thresholds)
        metrics,errors=evaluate(records,thresholds)
        entry={'thresholds':config['confidence'],'checkpoint_sha256':sha(directory/'best.pt'),'metrics':metrics,'errors':errors,
               'maps':{},'head_size_recall':{},'crosshair_groups':{},'empty_images':sum(not r['truth'] for r in records),
               'empty_frame_detections':sum(len(r['predictions']) for r in records if not r['truth'])}
        sizes=Counter();misses=Counter()
        for r in records:
            matched,_,_=match(r['truth'],r['predictions'],0)
            for i,t in enumerate(r['truth']):
                if t['class_id']==2:
                    sizes[t['size_bin']]+=1
                    if i not in matched:misses[t['size_bin']]+=1
        entry['head_size_recall']={size:{'heads':count,'missed':misses[size],'recall':(count-misses[size])/count} for size,count in sizes.items()}
        for scene in sorted({r['scene'] for r in records}):
            subset=[r for r in records if r['scene']==scene]
            entry['maps'][scene]={'images':len(subset),'metrics':evaluate(subset,thresholds)[0]}
        for style in sorted({m['crosshair']['style'] for m in metadata.values()}):
            subset=[r for r in records if metadata[r['stem']]['crosshair']['style']==style]
            entry['crosshair_groups'][style]={'images':len(subset),'metrics':evaluate(subset,thresholds)[0]}
        entry['crosshair_note']='Descriptive groups contain different images; do not interpret differences as a paired crosshair effect.'
        failures={e['stem'] for e in errors}
        selected=[]
        for scene in sorted(entry['maps']):
            subset=[r for r in records if r['scene']==scene and r['truth']]
            selected.append(next((r for r in subset if r['stem'] in failures),subset[0]))
        sheet=Image.new('RGB',(800,440*len(selected)),'#202025');draw=ImageDraw.Draw(sheet)
        for i,r in enumerate(selected):
            image=Image.open(r['image_path']).convert('RGB')
            sheet.paste(annotated(image,r['truth']),(0,440*i+24))
            sheet.paste(annotated(image,r['predictions'],True),(400,440*i+24))
            draw.text((8,440*i+6),f'{r["scene"]} / {r["stem"]} | labels',fill='white')
            draw.text((408,440*i+6),'predictions / published thresholds',fill='white')
        sheet.save(maps.OUT/'examples.jpg',quality=95)
        (maps.OUT/'results.json').write_text(json.dumps(entry,indent=2))
        report['models'][directory.name]=entry
        print(directory.name,json.dumps(metrics),flush=True)
    (args.output/'results.json').write_text(json.dumps(report,indent=2))
    page='<!doctype html><meta charset="utf-8"><title>Fresh real-map model tests</title><style>body{font:16px sans-serif;background:#202025;color:white;margin:2rem}td,th{padding:8px;border:1px solid #666}img{max-width:100%}</style><h1>Fresh real-map tests</h1><p>'+report['protocol']+'</p>'
    for name,entry in report['models'].items():
        page+='<h2>'+name+'</h2>'+maps.metrics_table([('All maps',entry['metrics'])]+[(n,m['metrics']) for n,m in entry['maps'].items()])
        page+='<p>One diagnostic example per map, prioritizing failures; these examples are not a random sample.</p><img src="'+name+'/examples.jpg">'
    (args.output/'index.html').write_text(page,encoding='utf-8')


if __name__=='__main__':main()
