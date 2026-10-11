import hashlib
import json
import sys
import threading
import pytest

from tools import generate_real_maps as generator


@pytest.mark.parametrize('workers',[2,3])
@pytest.mark.parametrize('start,split',[(0,'train'),(5000,'test')])
def test_workers_overlap_without_sharing_frame_ids(tmp_path, monkeypatch, workers, start, split):
    (tmp_path/'tools').mkdir()
    (tmp_path/'tools/convert_blender_map.py').write_text('converter')
    (tmp_path/'environment').mkdir()
    (tmp_path/'environment/real_maps_dataset.gd').write_text('renderer')
    source=tmp_path/'assets/source/valorant_maps';source.mkdir(parents=True)
    records=[dict(name=name,file=name+'.blend',sha256=name,planned_training_images=2) for name in ['A','B','C'][:workers]]
    (source/'manifest.json').write_text(json.dumps({'maps':records}))
    for record in records:
        folder=tmp_path/'assets/generated/valorant_maps'/record['name'].lower();folder.mkdir(parents=True)
        (folder/'build_version.txt').write_text(hashlib.sha256(b'converter').hexdigest())
        (folder/'conversion.json').write_text(json.dumps({'source_sha256':record['sha256'],'viewpoints':101}))
    output=tmp_path/'output';barrier=threading.Barrier(workers)
    def fake_run(command, log, marker):
        if marker!='REAL_MAP_COMPLETE':return
        args={item.split('=',1)[0]:item.split('=',1)[1] for item in command if item.startswith('--') and '=' in item}
        barrier.wait(timeout=5)
        number=int(args['--map-number']);start=int(args['--start'])
        for i in range(start,start+int(args['--count'])):
            stem=str(1000000+number*10000+i)
            for folder,suffix in [('images','.jpg'),('masks','.png'),('metadata','.json')]:
                dest=output/folder/args['--split'];dest.mkdir(parents=True,exist_ok=True)
                data={'scene_family':args['--map'],'spatial_region':str(i),'map_viewpoint':i,'crosshair':{'style':'none'}}
                (dest/(stem+suffix)).write_text(json.dumps(data) if folder=='metadata' else 'fixture')
    monkeypatch.setattr(generator,'ROOT',tmp_path)
    monkeypatch.setattr(generator,'run',fake_run)
    monkeypatch.setattr(sys,'argv',['generate','--output',str(output),'--workers',str(workers),'--start',str(start),'--split',split])
    generator.main()
    state=json.loads((output/'generation_status.json').read_text())
    assert state['phase']=='complete' and state['images']==2*workers
    assert set(state['completed_maps'])=={r['name'].lower() for r in records} and not state['active_workers']
    assert {p.stem for p in (output/'metadata'/split).iterdir()}=={str(1000000+n*10000+i) for n in range(workers) for i in range(start,start+2)}
