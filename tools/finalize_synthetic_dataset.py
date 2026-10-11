"""Convert depth-tested instance/head masks to YOLO labels; audit and preview."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

NAMES = ['enemy','teammate','head']
COLORS = ['#ef72ff','#50dfff','#ffff30']

def process(meta_path):
    meta_path=Path(meta_path)
    root=meta_path.parents[2]; split=meta_path.parent.name; name=meta_path.stem
    meta=json.loads(meta_path.read_text())
    if 'placement' in meta:
        for i,actor in enumerate(meta['actors']):
            for other in meta['actors'][i+1:]:
                distance=np.linalg.norm(np.array(actor['position'])-np.array(other['position']))
                assert distance >= meta['placement']['minimum_player_distance_m']-1e-5,(name,distance)
    image_path=root/'images'/split/f'{name}.jpg'
    with Image.open(image_path) as im:
        assert im.size==tuple(meta['resolution'])
        im.verify()
    with Image.open(root/'masks'/split/f'{name}.png') as im:
        rgb=np.array(im.convert('RGB'))
    h,w=rgb.shape[:2]
    assert (w,h)==tuple(meta['resolution'])
    ids=np.rint(rgb[:,:,0].astype(np.float32)/32).astype(np.uint8)
    assert np.max(np.abs(rgb[:,:,0].astype(int)-ids.astype(int)*32))<=3
    assert set(np.unique(rgb[:,:,1])).issubset({0,255})
    assert not rgb[:,:,2].any()
    assert set(np.unique(ids)).issubset({0,*[a['instance_id'] for a in meta['actors']]})
    if 'sampling' in meta:
        assert len(meta['actors'])<=1
        assert int((ids>0).sum())==meta['visible_body_pixels']
        assert int((rgb[:,:,1]>127).sum())==meta['visible_head_pixels']
        if meta['actors']:
            assert meta['visible_body_pixels']>=meta['sampling']['minimum_body_pixels']
            if meta['sampling']['head_required']:
                assert meta['visible_head_pixels']>=meta['sampling']['minimum_head_pixels_when_required']
        else:
            assert not (ids>0).any()
    if 'target_category' in meta:
        assert len(meta['actors'])<=1
        assert int((ids>0).sum())==meta['visible_body_pixels']
        assert int((rgb[:,:,1]>127).sum())==meta['visible_head_pixels']
        if meta['actors']:
            ys,xs=np.where(rgb[:,:,1]>127)
            assert len(xs)>=3 and (ids>0).sum()>=40
            side=min(int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1))
            assert side==meta['head_short_side']
            if meta['target_category']=='tiny_head':assert 2<=side<8
            if meta['target_category']=='small_head':assert 2<=side<16
            if meta['target_category']=='partial_cover':assert .15<=len(xs)/meta['uncovered_head_pixels']<=.9
        else:assert not ids.any()
    boxes=[]; details=[]; omitted=[]
    for actor in meta['actors']:
        body=ids==actor['instance_id']
        for cls,mask in [(NAMES.index(actor['role']),body),(2,body & (rgb[:,:,1]>127))]:
            ys,xs=np.where(mask)
            if not len(xs): continue
            x0,x1=int(xs.min()),int(xs.max())+1
            y0,y1=int(ys.min()),int(ys.max())+1
            # Keep every visible object, including tiny/truncated ones; no unlabeled positives.
            box=[cls,(x0+x1)/(2*w),(y0+y1)/(2*h),(x1-x0)/w,(y1-y0)/h]
            assert all(0<=v<=1 for v in box[1:]) and box[3]>0 and box[4]>0
            boxes.append(box)
            details.append({'class':NAMES[cls],'instance_id':actor['instance_id'],'character':actor['character'],
                            'bbox_xyxy':[x0,y0,x1,y1],'visible_pixels':len(xs)})
    if 'placement' in meta:
        bodies=[o for o in details if o['class']!='head']
        for i,body in enumerate(bodies):
            ax0,ay0,ax1,ay1=body['bbox_xyxy']
            for other in bodies[i+1:]:
                bx0,by0,bx1,by1=other['bbox_xyxy']
                assert min(ax1,bx1)<=max(ax0,bx0) or min(ay1,by1)<=max(ay0,by0), (name,'overlapping player boxes',body,other)
    label_path=root/'labels'/split/f'{name}.txt'
    label_path.parent.mkdir(parents=True,exist_ok=True)
    label_path.write_text(''.join(f'{int(b[0])} '+' '.join(f'{v:.8f}' for v in b[1:])+'\n' for b in boxes))
    annotation={'index':meta['index'],'split':split,'scene_group':meta['scene_group'],
                'scene_family':meta['scene_family'],'objects':details}
    return annotation,hashlib.sha256(image_path.read_bytes()).hexdigest()

def preview(root, annotations, output, count=24, crops=False):
    nonempty=[a for a in annotations if a['objects']]
    chosen=[]
    if crops:
        for character in sorted({o['character'] for a in annotations for o in a['objects']}):
            candidates=[(a,o) for a in nonempty for o in a['objects'] if o['character']==character and o['class']=='head']
            if candidates:
                a,o=max(candidates,key=lambda pair:pair[1]['visible_pixels'])
                chosen.append((a,o))
    else:
        families=sorted({a['scene_family'] for a in annotations})
        for family in families:
            candidates=[a for a in nonempty if a['scene_family']==family]
            picks=np.linspace(0,len(candidates)-1,min(3,len(candidates)),dtype=int)
            chosen.extend((candidates[i],None) for i in picks)
    sample_size=Image.open(root/'images'/annotations[0]['split']/f"{annotations[0]['index']:06d}.jpg").size
    square=sample_size[0]==sample_size[1]
    tw,th=(320,320) if crops else (400,424) if square else (640,384)
    cols=6 if crops else 3
    canvas=Image.new('RGB',(tw*cols,th*((len(chosen)+cols-1)//cols)), '#171b20')
    for i,(a,head) in enumerate(chosen):
        im=Image.open(root/'images'/a['split']/f"{a['index']:06d}.jpg").convert('RGB')
        draw=ImageDraw.Draw(im)
        for obj in a['objects']:
            if crops and obj['instance_id'] != head['instance_id']: continue
            cls=NAMES.index(obj['class']); box=obj['bbox_xyxy']
            draw.rectangle(box,outline=COLORS[cls],width=2)
            if not crops: draw.text((box[0],max(0,box[1]-13)),obj['class'],fill=COLORS[cls],stroke_width=1,stroke_fill='black')
        if crops:
            x0,y0,x1,y1=head['bbox_xyxy']; side=max(70,int(max(x1-x0,y1-y0)*2.2))
            cx=(x0+x1)//2;cy=(y0+y1)//2
            im=im.crop((cx-side//2,cy-side//2,cx+side//2,cy+side//2)).resize((tw,th-24))
            title=f"{head['character']} / {a['index']:06d}"
        else:
            im.thumbnail((tw,th-24))
            title=f"{a['scene_family']} | {a['split']} | {a['index']:06d}"
        x=(i%cols)*tw;y=(i//cols)*th
        canvas.paste(im,(x,y))
        ImageDraw.Draw(canvas).text((x+5,y+th-20),title,fill='white')
    canvas.save(output,quality=92)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    parser.add_argument('--expected',type=int)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();root=args.root.resolve()
    paths=sorted(root.glob('metadata/*/*.json'))
    if args.expected: assert len(paths)==args.expected,(len(paths),args.expected)
    with ProcessPoolExecutor(args.workers) as executor:
        results=[]
        for i,result in enumerate(executor.map(process,paths,chunksize=20),1):
            results.append(result)
            if i%1000==0:print(f'VALIDATED {i}/{len(paths)}',flush=True)
    annotations=[r[0] for r in results]
    hashes=[r[1] for r in results]
    assert len(hashes)==len(set(hashes)), 'Duplicate images found'
    split_groups=defaultdict(set); counts=defaultdict(Counter); char_counts=Counter(); family_counts=defaultdict(Counter)
    character_roles=defaultdict(lambda:defaultdict(Counter))
    for a in annotations:
        split=a['split'];split_groups[split].add(a['scene_group']);counts[split]['images']+=1
        if not a['objects']: counts[split]['empty_images']+=1
        family_counts[split][a['scene_family']]+=1
        for obj in a['objects']:
            counts[split][obj['class']]+=1
            if obj['class']!='head':
                char_counts[obj['character']]+=1
                character_roles[split][obj['character']][obj['class']]+=1
    for s,groups in split_groups.items():
        for t,other in split_groups.items():
            if s!=t:assert not groups&other
    for split,count in counts.items():
        assert len(list((root/'images'/split).glob('*.jpg')))==count['images']
        assert len(list((root/'labels'/split).glob('*.txt')))==count['images']
    (root/'data.yaml').write_text(f'path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: enemy\n  1: teammate\n  2: head\n')
    (root/'annotations.jsonl').write_text(''.join(json.dumps(a,separators=(',',':'))+'\n' for a in annotations))
    resolutions={tuple(json.loads(p.read_text())['resolution']) for p in paths}
    assert len(resolutions)==1
    report={'images':len(paths),'resolution':list(next(iter(resolutions))),'splits':dict(counts),'scene_families':dict(family_counts),
            'scene_groups':{s:sorted(g) for s,g in split_groups.items()},'characters':dict(sorted(char_counts.items())),
            'duplicate_images':0,'cross_split_scene_overlap':0,'validation':'Every JPEG, mask palette, instance ID, label bound, file count and image hash checked.',
            'class_names':NAMES,'bbox_convention':'Tight visible-pixel bounds, including clothing/hair/equipment; head of either team.',
            'head_definition':'Head/descendant skin weights >= 0.5, restricted by rest-pose and animated head-local envelopes to exclude long hair/scarves; visible surface, not a game hitbox.'}
    metadata=[json.loads(p.read_text()) for p in paths]
    spacing=[float(np.linalg.norm(np.array(a['position'])-np.array(b['position'])))
             for m in metadata for i,a in enumerate(m['actors']) for b in m['actors'][i+1:]]
    if all('placement' in m for m in metadata):
        report['placement_checks']={'minimum_required_distance_m':metadata[0]['placement']['minimum_player_distance_m'],
            'minimum_observed_distance_m':min(spacing) if spacing else None,'overlapping_visible_player_boxes':0,
            'screen_envelope_gap_pixels':metadata[0]['placement']['screen_envelope_gap_pixels']}
    report['character_roles_by_split']={s:{c:dict(n) for c,n in characters.items()} for s,characters in character_roles.items()}
    report['highlight_settings']=metadata[0].get('enemy_highlight')
    report['generator_versions']=sorted({m.get('generator_version','unknown') for m in metadata})
    if 'crop' in metadata[0]:
        report['crop']=metadata[0]['crop']
    if 'sampling' in metadata[0]:
        report['sampling']=metadata[0]['sampling'].copy()
        report['sampling'].pop('head_required',None)
        report['sampling']['accepted_after_retry']=sum(m['acceptance_attempt']>0 for m in metadata)
        report['sampling']['maximum_retries']=max(m['acceptance_attempt'] for m in metadata)
        report['sampling']['positive_images_without_visible_player']=0
    views=Counter(); occlusion=Counter()
    annotation_by_index={a['index']:a for a in annotations}
    for meta in metadata:
        objects=annotation_by_index[meta['index']]['objects']
        visible_bodies={o['instance_id'] for o in objects if o['class']!='head'}
        visible_heads={o['instance_id'] for o in objects if o['class']=='head'}
        occlusion['actors_without_visible_body_pixels']+=len(meta['actors'])-len(visible_bodies)
        occlusion['visible_bodies_without_visible_head_pixels']+=len(visible_bodies-visible_heads)
        for actor in meta['actors']:
            if actor['instance_id'] not in visible_bodies:continue
            dx=meta['camera_position'][0]-actor['position'][0]
            dz=meta['camera_position'][2]-actor['position'][2]
            angle=abs((actor['yaw']-math.atan2(dx,dz)+math.pi)%(2*math.pi)-math.pi)
            bucket=min(4,int((angle+math.pi/8)/(math.pi/4)))
            views[['front','front_oblique','side','rear_oblique','rear'][bucket]]+=1
    report['visible_character_view_angles']=dict(views)
    report['visibility_checks']={**dict(occlusion),'policy':'Label visible pixels only; no label for fully hidden or offscreen parts.'}
    (root/'audit.json').write_text(json.dumps(report,indent=2))
    preview(root,annotations,root/'preview_scenes.jpg')
    preview(root,annotations,root/'preview_heads.jpg',crops=True)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
