"""Download verified two-class data and fine-tune YOLO on a CUDA GPU."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from train_h100 import extract,verify

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',default='edgeai-lab/valorant-detection-400')
    p.add_argument('--revision',default='main');p.add_argument('--epochs',type=int,default=40)
    p.add_argument('--batch',type=int,default=64);p.add_argument('--workers',type=int,default=8)
    p.add_argument('--name',default='enemy_anatomy');p.add_argument('--test',action='store_true',help='Evaluate test only after model selection.')
    args=p.parse_args()
    from huggingface_hub import snapshot_download
    import hashlib
    package=Path(snapshot_download(args.repo,repo_type='dataset',revision=args.revision,token=os.environ.get('HF_TOKEN'),allow_patterns=['archives/*','weights/*','manifest.json']))
    manifest=json.loads((package/'manifest.json').read_text());assert manifest['class_names']==['enemy_body','enemy_head']
    for name,entry in manifest['files'].items():
        if name.startswith(('archives/','weights/')):verify(package/name,entry['sha256'])
    identity=hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest()[:12]
    native=Path('datasets')/f'anatomy400_{identity}';padded=Path('datasets')/f'anatomy416_{identity}'
    if not (native/'extraction_complete.json').exists():
        for archive in sorted((package/'archives').glob('*.zip')):extract(archive,native)
        (native/'extraction_complete.json').write_text(json.dumps({'manifest_identity':identity}))
    if not (padded/'audit.json').exists():
        subprocess.run([sys.executable,'tools/prepare_center_training.py','--source',str(native),'--dest',str(padded)],check=True)
    from ultralytics import YOLO
    # Ultralytics rebuilds the class predictor for nc=2; compatible backbone/neck weights transfer.
    model=YOLO(str(package/'weights/center400_warmstart.pt'))
    model.train(data=str(padded.resolve()/'data.yaml'),imgsz=416,epochs=args.epochs,batch=args.batch,
                workers=args.workers,device=0,name=args.name,seed=42,patience=10,lr0=.0003,
                fliplr=.5,flipud=0,mosaic=0,mixup=0,scale=0,degrees=0,translate=0)
    best=YOLO(str(model.trainer.best))
    result=best.val(data=str(padded.resolve()/'data.yaml'),split='test' if args.test else 'val',imgsz=416,device=0)
    print(json.dumps(dict(class_names=best.names,metrics=result.results_dict),indent=2))

if __name__=='__main__':main()
