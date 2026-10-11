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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='edgeai-lab/valorant-center400-10k')
    parser.add_argument('--revision',default='main',help='Use an immutable commit hash to reproduce a download.')
    parser.add_argument('--epochs',type=int,default=30)
    parser.add_argument('--batch',type=int,default=64)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    from huggingface_hub import snapshot_download
    token=os.environ.get('HF_TOKEN') or os.environ.get('HF-TOKEN')
    # If no environment token is set, huggingface_hub uses `hf auth login` credentials.
    download=Path(snapshot_download(args.repo,repo_type='dataset',revision=args.revision,token=token,
                                    allow_patterns=['archives/*','weights/*','manifest.json'],
                                    local_dir=ROOT/'downloads/center400'))
    manifest=json.loads((download/'manifest.json').read_text())
    for relative,entry in manifest['files'].items():
        if relative.startswith(('archives/','weights/')):verify(download/relative,entry['sha256'])
    native=ROOT/'datasets/valorant_center400_10k'
    marker=native/'download_manifest.json'
    identity={k:v['sha256'] for k,v in manifest['files'].items() if k.startswith('archives/')}
    if not marker.exists():
        for archive in sorted((download/'archives').glob('*.zip')):extract(archive,native)
        marker.write_text(json.dumps(identity,indent=2))
    elif json.loads(marker.read_text())!=identity:
        raise RuntimeError('Existing dataset differs from this revision; use a fresh checkout for another dataset.')
    padded=ROOT/'datasets/valorant_center400_padded416'
    if not (padded/'audit.json').exists():
        subprocess.run([sys.executable,'-u','tools/prepare_center_training.py'],cwd=ROOT,check=True)
    else:
        audit=json.loads((padded/'audit.json').read_text())
        assert audit['source_audit_sha256']==hashlib.sha256((native/'audit.json').read_bytes()).hexdigest()
    if args.prepare_only:
        print(f'Data ready: {padded}');return
    import torch
    if not torch.cuda.is_available():raise RuntimeError('Install a CUDA-enabled PyTorch build in the H100 environment first.')
    print('GPU:',torch.cuda.get_device_name(0),flush=True)
    run=ROOT/'runs/train/yolo11s_center400_416'
    command=[sys.executable,'-u','tools/train_synthetic_yolo.py','--model','yolo11s',
             '--name',run.name,'--dataset',str(padded),'--init-weights',str(download/'weights/center400_warmstart.pt'),
             '--imgsz','416','--batch',str(args.batch),'--epochs',str(args.epochs),
             '--workers',str(args.workers),'--patience','10','--lr0','0.0003','--skip-test']
    if args.resume:command+=['--resume',str(run/'weights/last.pt')]
    subprocess.run(command,cwd=ROOT,check=True)
    subprocess.run([sys.executable,'-u','tools/evaluate_center_goal.py'],cwd=ROOT,check=True)
    print('Read runs/analysis/center400/assessment.txt for the held-out 99% assessment.',flush=True)


if __name__=='__main__':main()
