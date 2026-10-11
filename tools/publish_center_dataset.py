"""Package audited native crops and warm-start weights; upload only to a private HF dataset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/valorant_detection_400_v2'
PACKAGE=ROOT/'exports/hf_detection400_v2'


def token():
    value=os.environ.get('HF_TOKEN') or os.environ.get('HF-TOKEN')
    if not value and os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            for name in ['HF_TOKEN','HF-TOKEN']:
                try:value=winreg.QueryValueEx(key,name)[0];break
                except FileNotFoundError:pass
    return value


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def package():
    audit=json.loads((DATA/'audit.json').read_text())
    state=json.loads((DATA/'generation_status.json').read_text())
    assert state['phase']=='complete' and audit['images']==12000
    (PACKAGE/'archives').mkdir(parents=True,exist_ok=True)
    (PACKAGE/'weights').mkdir(exist_ok=True)
    (PACKAGE/'tools').mkdir(exist_ok=True)
    for split in ['train','val','test']:
        path=PACKAGE/'archives'/f'{split}.zip'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for directory in ['images','labels','masks','metadata']:
                for source in sorted((DATA/directory/split).iterdir()):
                    archive.write(source,source.relative_to(DATA).as_posix())
        print(f'PACKAGED {split}: {path.stat().st_size/1e6:.1f} MB',flush=True)
    with zipfile.ZipFile(PACKAGE/'archives/dataset_metadata.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['audit.json','provenance.json','annotations.jsonl','README.txt']:
            archive.write(DATA/name,name)
        archive.writestr('data.yaml','path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: enemy\n  1: teammate\n  2: head\n')
    source=ROOT/'models/valorant-center400-yolo11s/best.pt'
    assert sha256(source)=='8dcda1b95132818411015fc6ca09d5def7569b592e33e6745c96ee48bdf0ee8f'
    shutil.copy2(source,PACKAGE/'weights/center400_warmstart.pt')
    info=dict(source_repo='edgeai-lab/valorant-center400-yolo11s',
        source_revision='116b979aa0913d1bfe4ef3714a52434721dbebf5',source_sha256=sha256(source),
        purpose='Identical trained checkpoint for both controlled fine-tuning arms. Optimizer restarts in both arms.')
    (PACKAGE/'weights/warmstart_info.json').write_text(json.dumps(info,indent=2))
    for name in ['train_h100.py','train_synthetic_yolo.py','prepare_center_training.py',
                 'evaluate_center_goal.py','analyze_detection_failures.py','training_progress.py','dataset_progress.py']:
        shutil.copy2(ROOT/'tools'/name,PACKAGE/'tools'/name)
    shutil.copy2(ROOT/'requirements.txt',PACKAGE/'requirements.txt')
    for name in ['preview_scenes.jpg','preview_heads.jpg']:shutil.copy2(DATA/name,PACKAGE/name)
    card=(ROOT/'README.md').read_text(encoding='utf-8')
    card='---\npretty_name: Valorant detection 400\ntask_categories: [object-detection]\ntags: [yolo, synthetic, valorant]\nsize_categories: [10K<n<100K]\n---\n\n'+card
    card+='\n## Audited counts\n\n| Split | Images | Enemy | Teammate | Head | Empty |\n|---|---:|---:|---:|---:|---:|\n'
    for split,counts in audit['splits'].items():
        card+='| '+split+' | '+' | '.join(str(counts.get(k,0)) for k in ['images','enemy','teammate','head','empty_images'])+' |\n'
    (PACKAGE/'README.md').write_text(card,encoding='utf-8')
    manifest=dict(dataset='valorant_detection_400_v2',images=audit['images'],resolution=[400,400],class_names=audit['class_names'],
                  created_at=time.time(),files={})
    for p in sorted(PACKAGE.rglob('*')):
        if p.is_file() and p.name!='manifest.json' and '.cache' not in p.parts:
            manifest['files'][p.relative_to(PACKAGE).as_posix()]=dict(bytes=p.stat().st_size,sha256=sha256(p))
    (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('PACKAGE_READY',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='edgeai-lab/valorant-detection-400')
    parser.add_argument('--package-only',action='store_true')
    parser.add_argument('--upload-only',action='store_true')
    args=parser.parse_args()
    if not args.upload_only:package()
    if args.package_only:return
    from huggingface_hub import HfApi
    api=HfApi(token=token())
    api.create_repo(args.repo,repo_type='dataset',private=True,exist_ok=True)
    assert api.dataset_info(args.repo).private,'Refusing to upload private data to a public repository.'
    result=api.upload_folder(repo_id=args.repo,repo_type='dataset',folder_path=PACKAGE,
                             ignore_patterns=['.cache/**'],commit_message='Add 2,000 targeted training images and controlled H100 comparison')
    info=api.dataset_info(args.repo,files_metadata=True)
    assert info.private
    actual={s.rfilename:s for s in info.siblings}
    manifest=json.loads((PACKAGE/'manifest.json').read_text())
    for relative,entry in manifest['files'].items():
        assert relative in actual,relative
        sibling=actual[relative]
        assert sibling.size==entry['bytes'],relative
        if sibling.lfs:assert sibling.lfs.sha256==entry['sha256'],relative
    report=dict(repo=args.repo,private=info.private,commit=info.sha,files=len(actual),url=f'https://huggingface.co/datasets/{args.repo}',
                verification='All listed sizes checked; all LFS SHA-256 hashes matched local package.')
    (ROOT/'exports/hf_upload_result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
