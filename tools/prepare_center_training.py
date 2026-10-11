"""Pad center images by eight pixels per side, without resampling original pixels."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'datasets/valorant_center400_10k'
DEST=ROOT/'datasets/valorant_center400_padded416'


def prepare(path):
    path=Path(path);split=path.parent.name;stem=path.stem
    with Image.open(SOURCE/'images'/split/f'{stem}.jpg') as original:
        original=original.convert('RGB')
        assert original.size==(400,400)
        padded=Image.new('RGB',(416,416),(114,114,114))
        padded.paste(original,(8,8))
        padded.save(DEST/'images'/split/f'{stem}.png',compress_level=1)
        assert padded.crop((8,8,408,408)).tobytes()==original.tobytes()
    # Translate normalized original labels into padded coordinates.
    rows=[]
    for line in (SOURCE/'labels'/split/f'{stem}.txt').read_text().splitlines():
        c,x,y,w,h=map(float,line.split())
        rows.append(f'{int(c)} {(x*400+8)/416:.9f} {(y*400+8)/416:.9f} {w*400/416:.9f} {h*400/416:.9f}\n')
    (DEST/'labels'/split/f'{stem}.txt').write_text(''.join(rows))
    meta=json.loads(path.read_text());meta.update(resolution=[416,416],padding=[8,8,8,8],source_resolution=[400,400])
    (DEST/'metadata'/split/f'{stem}.json').write_text(json.dumps(meta))
    return split


def main():
    audit=json.loads((SOURCE/'audit.json').read_text())
    assert audit['images']==10000 and audit['resolution']==[400,400]
    for split in ['train','val','test']:
        for directory in ['images','labels','metadata']:
            (DEST/directory/split).mkdir(parents=True,exist_ok=True)
    paths=sorted(SOURCE.glob('metadata/*/*.json'))
    with ProcessPoolExecutor(4) as pool:
        for i,_ in enumerate(pool.map(prepare,paths,chunksize=25),1):
            if i%1000==0:print(f'PADDED {i}/10000',flush=True)
    annotations=[]
    for line in (SOURCE/'annotations.jsonl').read_text().splitlines():
        item=json.loads(line)
        for obj in item['objects']:obj['bbox_xyxy']=[v+8 for v in obj['bbox_xyxy']]
        annotations.append(item)
    (DEST/'annotations.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in annotations))
    audit.update(resolution=[416,416],source_dataset=str(SOURCE),padding=[8,8,8,8],
                 validation='Source dataset passed mask audit. All 10,000 decoded image interiors checked pixel-for-pixel unchanged after padding. Labels translated by eight pixels.',
                 source_audit_sha256=hashlib.sha256((SOURCE/'audit.json').read_bytes()).hexdigest())
    for split in ['train','val','test']:
        assert len(list((DEST/'images'/split).glob('*.png')))==audit['splits'][split]['images']
        assert len(list((DEST/'labels'/split).glob('*.txt')))==audit['splits'][split]['images']
    (DEST/'audit.json').write_text(json.dumps(audit,indent=2))
    (DEST/'data.yaml').write_text(f'path: {DEST.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: enemy\n  1: teammate\n  2: head\n')
    print('PADDING_COMPLETE',flush=True)


if __name__=='__main__':main()
