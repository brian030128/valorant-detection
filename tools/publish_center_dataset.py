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
DATA=ROOT/'datasets/valorant_detection_400_v5'
PACKAGE=ROOT/'exports/hf_detection400_v5'


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
    anatomy=audit['class_names']==['enemy_body','enemy_head']
    state=json.loads((DATA/'generation_status.json').read_text())
    assert state['phase']=='complete' and audit['images']==state['images'] and audit['images']>0
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
        archive.writestr('data.yaml','path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {name}\n' for i,name in enumerate(audit['class_names'])))
    source=ROOT/'models/valorant-center400-yolo11s-1f23a9a0575e/best.pt'
    expected_weight_sha='1bf9746df9ed2b7cc4bdcd9898e56dccebadeab1baad99d2927f72519725cf0a'
    if anatomy:
        source=ROOT/'models/valorant-center400-yolo11s-9c592fe4d022/best.pt'
        expected_weight_sha='25a314556e497f1228713ae1d275cd52ab30940cd4dc876517ef58b14c312f8d'
    negatives=audit.get('label_policy')=='enemy-anatomy-teammate-negatives-v2'
    if negatives:
        source=ROOT/'models/valorant-center400-yolo11s-9460cdaf8b55/best.pt'
        expected_weight_sha='ba79522e47a2530ac9cfb8159aca8d79397d434a1fc6391e962856d64aeb65ee'
    assert sha256(source)==expected_weight_sha
    shutil.copy2(source,PACKAGE/'weights/center400_warmstart.pt')
    info=dict(source_repo='edgeai-lab/valorant-center400-yolo11s',
        source_revision='1f23a9a0575e650360427df0bf5bae03a5384729',source_sha256=sha256(source),
        purpose='Identical trained checkpoint for both controlled fine-tuning arms. Optimizer restarts in both arms.')
    (PACKAGE/'weights/warmstart_info.json').write_text(json.dumps(info,indent=2))
    if anatomy:
        info['source_revision']='9c592fe4d0222ee460ffb3cea82f376d99a46d0d'
        info['purpose']='Transfer compatible features from a three-class checkpoint; the two-class predictor is rebuilt. Do not resume the old three-class optimizer.'
        if negatives:
            info['source_revision']='9460cdaf8b55cf92695053c55d662127e0e8db7e'
            info['purpose']='Fine-tune the same two anatomy classes with teammate-only hard negatives; restart optimizer.'
        (PACKAGE/'weights/warmstart_info.json').write_text(json.dumps(info,indent=2))
    tool_names=['train_enemy_anatomy.py','dataset_io.py','prepare_center_training.py'] if anatomy else [
        'train_h100.py','train_synthetic_yolo.py','prepare_center_training.py',
        'evaluate_center_goal.py','analyze_detection_failures.py','training_progress.py','dataset_progress.py']
    for name in tool_names:
        shutil.copy2(ROOT/'tools'/name,PACKAGE/'tools'/name)
    shutil.copy2(ROOT/'requirements.txt',PACKAGE/'requirements.txt')
    if (DATA/'baseline_teammate_test.json').exists():
        shutil.copy2(DATA/'baseline_teammate_test.json',PACKAGE/'baseline_teammate_test.json')
    for name in ['preview_scenes.jpg','preview_heads.jpg']:shutil.copy2(DATA/name,PACKAGE/name)
    if (DATA/'preview_new_scenes.jpg').exists():shutil.copy2(DATA/'preview_new_scenes.jpg',PACKAGE/'preview_new_scenes.jpg')
    if (DATA/'scene_catalog').exists():
        shutil.copytree(DATA/'scene_catalog',PACKAGE/'scene_catalog',dirs_exist_ok=True)
    card=(ROOT/'README.md').read_text(encoding='utf-8')
    if anatomy:card=(DATA/'README.txt').read_text(encoding='utf-8')
    card='---\npretty_name: Valorant detection 400\ntask_categories: [object-detection]\ntags: [yolo, synthetic, valorant]\nsize_categories: [10K<n<100K]\n---\n\n'+card
    columns=['images',*audit['class_names'],'empty_images']
    card+='\n## Audited counts\n\n| Split | '+' | '.join(columns)+' |\n|---|'+'---:|'*len(columns)+'\n'
    for split,counts in audit['splits'].items():
        card+='| '+split+' | '+' | '.join(str(counts.get(k,0)) for k in columns)+' |\n'
    (PACKAGE/'README.md').write_text(card,encoding='utf-8')
    manifest=dict(dataset=DATA.name,images=audit['images'],resolution=[400,400],class_names=audit['class_names'],
                  created_at=time.time(),files={})
    for p in sorted(PACKAGE.rglob('*')):
        if p.is_file() and p.name!='manifest.json' and '.cache' not in p.parts:
            manifest['files'][p.relative_to(PACKAGE).as_posix()]=dict(bytes=p.stat().st_size,sha256=sha256(p))
    (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('PACKAGE_READY',flush=True)


def main():
    global DATA, PACKAGE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=DATA)
    parser.add_argument('--package',type=Path,default=PACKAGE)
    parser.add_argument('--repo',default='edgeai-lab/valorant-detection-400')
    parser.add_argument('--package-only',action='store_true')
    parser.add_argument('--upload-only',action='store_true')
    args=parser.parse_args()
    DATA=args.dataset.resolve();PACKAGE=args.package.resolve()
    if not args.upload_only:package()
    if args.package_only:return
    from huggingface_hub import HfApi
    api=HfApi(token=token())
    api.create_repo(args.repo,repo_type='dataset',private=True,exist_ok=True)
    previous=api.dataset_info(args.repo)
    assert previous.private,'Refusing to upload private data to a public repository.'
    manifest=json.loads((PACKAGE/'manifest.json').read_text())
    expected=set(manifest['files'])|{'manifest.json'}
    obsolete=sorted({s.rfilename for s in previous.siblings}-expected-{'.gitattributes'})
    result=api.upload_folder(repo_id=args.repo,repo_type='dataset',folder_path=PACKAGE,
                             ignore_patterns=['.cache/**'],delete_patterns=obsolete,
                             parent_commit=previous.sha,
                             commit_message='Replace current dataset with audited '+DATA.name)
    info=api.dataset_info(args.repo,files_metadata=True)
    assert info.private
    actual={s.rfilename:s for s in info.siblings}
    assert set(actual)-{'.gitattributes'}==expected,'Remote file set does not match replacement package'
    manifest=json.loads((PACKAGE/'manifest.json').read_text())
    for relative,entry in manifest['files'].items():
        assert relative in actual,relative
        sibling=actual[relative]
        assert sibling.size==entry['bytes'],relative
        if sibling.lfs:assert sibling.lfs.sha256==entry['sha256'],relative
    report=dict(repo=args.repo,private=info.private,commit=info.sha,previous_commit=previous.sha,removed_obsolete_files=len(obsolete),files=len(actual),url=f'https://huggingface.co/datasets/{args.repo}',
                verification='All listed sizes checked; all LFS SHA-256 hashes matched local package.')
    (ROOT/'exports/hf_upload_result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
