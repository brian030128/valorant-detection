"""Audit two-class, depth-tested enemy torso/head masks and write YOLO labels."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

NAMES=['enemy_body','enemy_head']
COLORS=['#ef72ff','#ffe04b']

def process(path):
    path=Path(path);root=path.parents[2];split=path.parent.name
    meta=json.loads(path.read_text());assert meta['label_policy'] in ['enemy-anatomy-v1','enemy-anatomy-teammate-negatives-v2']
    assert all(a['role'] in ['enemy','teammate'] for a in meta['actors'])
    if meta['label_policy']=='enemy-anatomy-v1':assert all(a['role']=='enemy' for a in meta['actors'])
    source=root/'images'/split/(path.stem+'.jpg')
    with Image.open(source) as im:assert im.size==(400,400);im.verify()
    with Image.open(root/'masks'/split/(path.stem+'.png')) as im:pixels=np.array(im.convert('RGB'))
    assert pixels.shape==(400,400,3)
    ids=np.rint(pixels[:,:,0].astype(float)/32).astype(int)
    assert set(np.unique(ids))<={0,*[a['instance_id'] for a in meta['actors']]}
    assert np.max(np.abs(pixels[:,:,0].astype(int)-ids*32))<=3
    assert set(np.unique(pixels[:,:,1:]))<={0,255}
    assert not np.any((pixels[:,:,1]>0)&(pixels[:,:,2]>0))
    assert not np.any((ids==0)&np.any(pixels[:,:,1:]>0,axis=2))
    objects=[];rows=[]
    for actor in meta['actors']:
        if actor['role']=='teammate':continue
        for cls,channel in ((0,2),(1,1)):
            ys,xs=np.where((ids==actor['instance_id'])&(pixels[:,:,channel]>127))
            if not len(xs):continue
            x0,x1=int(xs.min()),int(xs.max())+1;y0,y1=int(ys.min()),int(ys.max())+1
            objects.append(dict(class_id=cls,**{'class':NAMES[cls]},instance_id=actor['instance_id'],
                                character=actor['character'],bbox_xyxy=[x0,y0,x1,y1],visible_pixels=len(xs)))
            rows.append(f'{cls} {(x0+x1)/800:.8f} {(y0+y1)/800:.8f} {(x1-x0)/400:.8f} {(y1-y0)/400:.8f}\n')
    composition=meta.get('scene_composition')
    if composition:
        roles=sorted(a['role'] for a in meta['actors'])
        assert roles==(['enemy','teammate'] if composition=='mixed' else ['teammate'])
        assert all(np.count_nonzero(ids==a['instance_id'])>=80 for a in meta['actors'])
        if composition=='mixed':
            assert sum(o['visible_pixels'] for o in objects)>=8
            positions=[np.array(a['position']) for a in meta['actors']]
            assert np.linalg.norm(positions[0]-positions[1])>=2.799
        else:assert not objects
    dest=root/'labels'/split/(path.stem+'.txt');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(''.join(rows))
    return dict(index=meta['index'],split=split,scene_group=meta['scene_group'],scene_family=meta['scene_family'],objects=objects,
                actor_roles=[a['role'] for a in meta['actors']],label_policy=meta['label_policy']),hashlib.sha256(source.read_bytes()).hexdigest()

def panel(root,annotation):
    im=Image.open(root/'images'/annotation['split']/f"{annotation['index']}.jpg").convert('RGB')
    draw=ImageDraw.Draw(im)
    for obj in annotation['objects']:
        box=obj['bbox_xyxy'];color=COLORS[obj['class_id']]
        draw.rectangle(box,outline=color,width=2);draw.text((box[0],max(0,box[1]-12)),obj['class'],fill=color,stroke_width=1,stroke_fill='black')
    return im

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--expected',type=int);p.add_argument('--workers',type=int,default=8)
    args=p.parse_args();root=args.root.resolve();paths=sorted(root.glob('metadata/*/*.json'))
    if args.expected:assert len(paths)==args.expected,(len(paths),args.expected)
    with ProcessPoolExecutor(args.workers) as pool:results=list(pool.map(process,paths,chunksize=20))
    annotations=[r[0] for r in results];assert len(set(r[1] for r in results))==len(results)
    for split in {a['split'] for a in annotations}:
        expected={str(a['index']) for a in annotations if a['split']==split}
        for directory,suffix in [('images','.jpg'),('masks','.png'),('labels','.txt'),('metadata','.json')]:
            assert {p.stem for p in (root/directory/split).glob('*'+suffix)}==expected,(directory,split)
    counts=defaultdict(Counter);groups=defaultdict(set)
    for a in annotations:
        counts[a['split']]['images']+=1;counts[a['split']]['empty_images']+=int(not a['objects'])
        counts[a['split']]['teammate_images']+=int('teammate' in a['actor_roles'])
        counts[a['split']]['teammate_only_images']+=int(set(a['actor_roles'])=={'teammate'})
        counts[a['split']]['mixed_images']+=int(set(a['actor_roles'])=={'enemy','teammate'})
        counts[a['split']]['background_images']+=int(not a['actor_roles'])
        if a['actor_roles'] and set(a['actor_roles'])=={'teammate'}:assert not a['objects']
        counts[a['split']].update(o['class'] for o in a['objects']);groups[a['split']].add(a['scene_group'])
    for s,g in groups.items():
        for t,h in groups.items():
            if s!=t:assert not g&h,'Cross-split viewpoint overlap'
    (root/'annotations.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in annotations))
    (root/'data.yaml').write_text(f'path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: enemy_body\n  1: enemy_head\n')
    policies={a['label_policy'] for a in annotations};assert len(policies)==1
    audit=dict(images=len(paths),resolution=[400,400],class_names=NAMES,label_policy=next(iter(policies)),splits=dict(counts),duplicate_images=0,cross_split_scene_overlap=0,
               label_definition='Visible torso (pelvis/spine skin influence within central trunk envelope), and head excluding identified hair materials/bones. Arms, legs and excluded surfaces still occlude targets. Visual anatomical approximation, not game collision hitboxes.')
    (root/'audit.json').write_text(json.dumps(audit,indent=2))
    selected=[a for a in annotations if a['objects']][:24] or annotations[:24]
    canvas=Image.new('RGB',(1600,400*((len(selected)+3)//4)))
    for i,a in enumerate(selected):canvas.paste(panel(root,a),((i%4)*400,(i//4)*400))
    canvas.save(root/'preview_scenes.jpg');canvas.save(root/'preview_heads.jpg')
    print(json.dumps(audit,indent=2),flush=True)

if __name__=='__main__':main()
