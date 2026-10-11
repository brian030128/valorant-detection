"""Train YOLO11s, then compare both checkpoints at 960/1280 on the same validation split."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'runs/analysis'
RUN=ROOT/'runs/train/yolo11s_synthetic_960'


def comparison():
    rows=[]
    for model in ['yolo11n','yolo11s']:
        for size in [960,1280]:
            path=OUTPUT/model/str(size)/'report.json'
            if path.exists():
                report=json.loads(path.read_text())
                rows.append(dict(model=model, inference_size=size, training_size=960,
                                 metrics=report['thresholds']['0.5'], mean_inference_ms=report['mean_inference_ms'],
                                 report=f'{model}/{size}/index.html', checkpoint_sha256=report['configuration']['checkpoint_sha256']))
    result=dict(matching_iou=.5, confidence=.5, split='val', images=1000, single_player_images=320,
                policy='Same dataset, seed, optimizer, augmentation, batch size 16, 30 epoch budget and patience 8. Both models start from their official COCO-pretrained weights. Training resolution stays 960; inference resolution is varied. Test is not used for model selection.',
                rows=rows, caveats=['Exploratory single-seed comparison on synthetic validation, not a guarantee of real-game accuracy.',
                                   'Inference timing is the batch-8 model-forward average, not end-to-end application latency.'])
    (OUTPUT/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    tables=[]
    for group in ['single_player','all']:
        table=f'<h2>{"Single visible player (320 images)" if group=="single_player" else "All validation images (1,000 images)"}</h2><table><tr><th>Model</th><th>Input</th><th>Class</th><th>Precision</th><th>Recall</th><th>Missed</th><th>False positives</th><th>Gallery</th></tr>'
        for row in rows:
            for name in ['enemy','teammate','head']:
                value=row['metrics'][group][name]
                table+=f'<tr><td>{row["model"]}</td><td>{row["inference_size"]}</td><td>{name}</td><td>{value["precision"]:.2%}</td><td>{value["recall"]:.2%}</td><td>{value["fn"]}</td><td>{value["fp"]}</td><td><a href="{row["report"]}">Review</a></td></tr>'
        tables.append(table+'</table>')
    page='<!doctype html><meta charset="utf-8"><title>YOLO validation comparison</title><style>body{font:16px system-ui;background:#111925;color:#e8eef8;padding:28px;max-width:1200px;margin:auto}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #445;text-align:left}a{color:#8dd5ff}p{line-height:1.6}</style><h1>YOLO validation comparison</h1>'
    page+='<p>Confidence ≥ 0.50; correct class and IoU ≥ 0.50. Both models train at 960 pixels; the input column changes inference resolution only. Refresh this page after the larger-model run finishes.</p>'
    page+=''.join(tables)+f'<p>{result["policy"]}</p><p>{" ".join(result["caveats"])}</p>'
    (OUTPUT/'comparison.html').write_text(page,encoding='utf-8')


def main():
    OUTPUT.mkdir(exist_ok=True)
    status=dict(pid=os.getpid(),started_at=time.time(),phase='starting',plan=['Train YOLO11s at 960','Evaluate YOLO11s at 960','Evaluate YOLO11s at 1280','Write comparison'])
    def update(**values):
        status.update(values,updated_at=time.time())
        temporary=OUTPUT/'comparison_status.tmp'
        temporary.write_text(json.dumps(status,indent=2),encoding='utf-8')
        temporary.replace(OUTPUT/'comparison_status.json')
    def run(command,log):
        with (OUTPUT/log).open('w',encoding='utf-8') as stream:
            subprocess.run([sys.executable,'-u',*command],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    try:
        comparison()
        update(phase='training',training_run=str(RUN))
        existing=RUN/'training_status.json'
        if not existing.exists() or json.loads(existing.read_text()).get('phase') != 'complete':
            command=['tools/train_synthetic_yolo.py','--model','yolo11s','--name',RUN.name,'--imgsz','960',
                     '--batch','16','--epochs','30','--workers','4','--skip-test']
            if (RUN/'weights/last.pt').exists():
                command+=['--resume',str(RUN/'weights/last.pt')]
            run(command,'yolo11s_training.log')
        for size in [960,1280]:
            update(phase='analyzing',imgsz=size)
            run(['tools/analyze_detection_failures.py','--checkpoint',str(RUN/'weights/best.pt'),
                 '--imgsz',str(size),'--output',str(OUTPUT/'yolo11s'/str(size))],f'yolo11s_analysis_{size}.log')
            comparison()
        update(phase='complete',elapsed_seconds=time.time()-status['started_at'])
    except BaseException as error:
        update(phase='failed',error=str(error))
        raise


if __name__=='__main__':main()
