"""Download private center-crop data, fine-tune YOLO11s, and test frozen validation thresholds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def verify(path,expected):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=expected:raise RuntimeError(f'Checksum mismatch: {path.name}')


def extract(archive,destination):
    destination=destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target=(destination/entry.filename).resolve()
            if not target.is_relative_to(destination):raise ValueError('Unsafe archive path')
        bundle.extractall(destination)


def main():
    import math
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='edgeai-lab/valorant-detection-400')
    parser.add_argument('--revision',default='main')
    parser.add_argument('--experiment',choices=['baseline','targeted','both'],default='both')
    parser.add_argument('--epochs',type=int,default=20,help='Targeted epochs; baseline epochs scale to approximately match batch updates.')
    parser.add_argument('--batch',type=int,default=64)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--evaluate-test',action='store_true',help='Opt in only after selecting an experiment on validation.')
    args=parser.parse_args()
    if min(args.epochs,args.batch)<1:raise ValueError('Epochs and batch must be positive.')
    from huggingface_hub import snapshot_download
    token=os.environ.get('HF_TOKEN') or os.environ.get('HF-TOKEN')
    download=Path(snapshot_download(args.repo,repo_type='dataset',revision=args.revision,token=token,
                                    allow_patterns=['archives/*','weights/*','manifest.json']))
    manifest=json.loads((download/'manifest.json').read_text())
    for relative,entry in manifest['files'].items():
        if relative.startswith(('archives/','weights/')):verify(download/relative,entry['sha256'])
    identity={k:v['sha256'] for k,v in manifest['files'].items() if k.startswith('archives/')}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:12]
    native=ROOT/f'datasets/center400_{key}'
    marker=native/'download_manifest.json'
    if not marker.exists():
        for archive in sorted((download/'archives').glob('*.zip')):extract(archive,native)
        marker.write_text(json.dumps(identity,indent=2))
    elif json.loads(marker.read_text())!=identity:raise RuntimeError('Dataset identity mismatch')
    padded=ROOT/f'datasets/center416_{key}'
    if not (padded/'audit.json').exists():
        subprocess.run([sys.executable,'-u','tools/prepare_center_training.py','--source',str(native),'--dest',str(padded)],cwd=ROOT,check=True)
    else:
        audit=json.loads((padded/'audit.json').read_text())
        assert audit['source_audit_sha256']==hashlib.sha256((native/'audit.json').read_bytes()).hexdigest()
    all_train=sorted((padded/'images/train').glob('*.png'))
    base_train=[p for p in all_train if int(p.stem)<100000]
    assert len(base_train)==8000
    baseline_list=padded/'baseline_train.txt'
    baseline_list.write_text(''.join(p.as_posix()+'\n' for p in base_train))
    if args.prepare_only:
        print(f'Data ready: {padded}');return
    import torch
    if not torch.cuda.is_available():raise RuntimeError('Install a CUDA-enabled PyTorch build first.')
    print('GPU:',torch.cuda.get_device_name(0),flush=True)
    experiments=['baseline','targeted'] if args.experiment=='both' else [args.experiment]
    comparison={}
    for experiment in experiments:
        epochs=round(args.epochs*math.ceil(len(all_train)/args.batch)/math.ceil(len(base_train)/args.batch)) if experiment=='baseline' else args.epochs
        run=ROOT/f'runs/train/center400_{key}_{experiment}'
        output=ROOT/f'runs/analysis/center400_{key}_{experiment}'
        command=[sys.executable,'-u','tools/train_synthetic_yolo.py','--model','yolo11s',
                 '--name',run.name,'--dataset',str(padded),'--init-weights',str(download/'weights/center400_warmstart.pt'),
                 '--imgsz','416','--batch',str(args.batch),'--epochs',str(epochs),
                 '--workers',str(args.workers),'--patience','0','--lr0','0.0003','--skip-test']
        if experiment=='baseline':command+=['--train-list',str(baseline_list)]
        if args.resume:command+=['--resume',str(run/'weights/last.pt')]
        subprocess.run(command,cwd=ROOT,check=True)
        evaluation=[sys.executable,'-u','tools/evaluate_center_goal.py','--run',str(run),'--dataset',str(padded),'--output',str(output)]
        if not args.evaluate_test:evaluation+=['--validation-only']
        subprocess.run(evaluation,cwd=ROOT,check=True)
        result=json.loads((output/'frozen_thresholds.json').read_text())
        comparison[experiment]=dict(epochs=epochs,training_images=len(base_train) if experiment=='baseline' else len(all_train),
            metrics=result['metrics'],thresholds=result['thresholds'],run=str(run),analysis=str(output))
    report=ROOT/f'runs/analysis/center400_{key}_comparison.json'
    report.write_text(json.dumps(dict(dataset_identity=identity,warmstart_sha256=manifest['files']['weights/center400_warmstart.pt']['sha256'],
        budget_note='Same initialization, seed and settings; integer epochs approximately match batch updates. Not an exact equal-compute or multi-seed study.',
        test_evaluated=args.evaluate_test,experiments=comparison),indent=2))
    print(f'Comparison: {report}',flush=True)


if __name__=='__main__':main()
