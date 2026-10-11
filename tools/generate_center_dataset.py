"""Generate, label and audit 10k native-scale 400x400 center views; safe to resume."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/valorant_center400_10k'


def main():
    DATA.mkdir(parents=True,exist_ok=True)
    status=dict(pid=os.getpid(),started_at=time.time(),phase='rendering',expected=10000,
                resolution=[400,400],classes=['enemy','teammate','head'])
    def update(**values):
        status.update(values,updated_at=time.time())
        temp=DATA/'generation_status.tmp'
        temp.write_text(json.dumps(status,indent=2),encoding='utf-8')
        temp.replace(DATA/'generation_status.json')
    update()
    try:
        with (DATA/'render.log').open('w',encoding='utf-8') as log:
            command=[str(ROOT/'tools/godot/Godot_v4.7.2-stable_win64.exe'),'--path',str(ROOT/'environment'),
                     'res://center_dataset.tscn','--','--count=10000',f'--output={DATA}']
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        update(phase='labeling_and_auditing')
        with (DATA/'finalization.log').open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-u','tools/finalize_synthetic_dataset.py',str(DATA),
                            '--expected','10000','--workers','4'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        audit=json.loads((DATA/'audit.json').read_text())
        assert audit['images']==10000 and audit['resolution']==[400,400]
        totals={key:sum(s.get(key,0) for s in audit['splits'].values()) for key in ['enemy','teammate','empty_images']}
        assert totals==dict(enemy=8500,teammate=1000,empty_images=500),totals
        assert {s:v['images'] for s,v in audit['splits'].items()}==dict(train=8000,val=1000,test=1000)
        assert len(audit['characters'])==29
        for split in ['train','val','test']:
            assert len(audit['scene_families'][split])==8
            assert len(audit['character_roles_by_split'][split])==29
        provenance=dict(status='complete',created_at=time.time(),source='Kingdom Archives character assets; procedural Godot scenes',
                        scene_seed=20261013,original_dataset='valorant_synthetic_10k remains unchanged',
                        crop=audit['crop'],validation=audit['validation'],totals=totals,
                        pilot_projection_check='400x400 mask exactly matched full 1920x1080 mask crop [760:1160,340:740]; 0 differing pixels',
                        code_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['environment/center_dataset.gd','environment/dataset.gd','environment/instance_mask.gdshader','tools/finalize_synthetic_dataset.py']})
        (DATA/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        update(phase='complete',totals=totals,elapsed_seconds=time.time()-status['started_at'])
    except BaseException as error:
        update(phase='failed',error=str(error))
        raise


if __name__=='__main__':main()
