"""Excluded limbs/hair still occlude targets; only visible torso/head get boxes."""
import json
from pathlib import Path
import sys
import tempfile
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from finalize_anatomy_dataset import process

def test_anatomy_labels_use_regions_not_whole_instance():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for kind in ['images','masks','metadata']:(root/kind/'test').mkdir(parents=True)
        pixels=np.zeros((400,400,3),dtype=np.uint8)
        pixels[10:390,20:380,0]=32 # Broad silhouette includes unlabeled limbs/hair.
        pixels[100:200,150:210,2]=255
        pixels[60:90,165:195,1]=255
        Image.new('RGB',(400,400)).save(root/'images/test/0.jpg')
        Image.fromarray(pixels).save(root/'masks/test/0.png')
        path=root/'metadata/test/0.json'
        path.write_text(json.dumps(dict(index=0,scene_group=0,scene_family='test',label_policy='enemy-anatomy-v1',actors=[dict(role='enemy',character='viper',instance_id=1)])))
        a,_=process(path)
        assert [(o['class'],o['bbox_xyxy']) for o in a['objects']]==[
            ('enemy_body',[150,100,210,200]),('enemy_head',[165,60,195,90])]
        pixels[:,:,1]=0 # Hair/occluder covers the entire head.
        Image.fromarray(pixels).save(root/'masks/test/0.png')
        a,_=process(path)
        assert [o['class'] for o in a['objects']]==['enemy_body']
