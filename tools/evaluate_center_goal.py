"""Wait for crop fine-tuning, freeze validation thresholds, test the 99% goal, then resume the previous run."""
from collections import Counter
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from analyze_detection_failures import match, rates, NAMES

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/train/yolo11s_center400_416'
DATA=ROOT/'datasets/valorant_center400_padded416'
OUT=ROOT/'runs/analysis/center400'


def evaluate(records, thresholds):
    counts={c:[0,0,0] for c in range(3)}
    errors=[]
    for record in records:
        predictions=[p for p in record['predictions'] if p['confidence']>=thresholds[p['class_id']]]
        matched,correct,false=match(record['truth'],predictions,0)
        for i,target in enumerate(record['truth']):
            counts[target['class_id']][0 if i in matched else 2]+=1
            if i not in matched:
                errors.append(dict(stem=record['stem'],kind='miss',class_name=NAMES[target['class_id']],
                                   size=target['size_bin'],character=target['character'],view=target['view'],scene=record['scene']))
        for i in false:
            counts[predictions[i]['class_id']][1]+=1
            errors.append(dict(stem=record['stem'],kind='false_positive',class_name=NAMES[predictions[i]['class_id']]))
    return {NAMES[c]:rates(v) for c,v in counts.items()},errors


def wilson(success,total):
    if not total:return None
    p=success/total;z=1.959963984540054;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [center-half,center+half]


def freeze_thresholds():
    records=json.loads((OUT/'val/predictions.json').read_text())['images']
    sweep={}
    for number in range(1,100):
        threshold=number/100
        metrics,_=evaluate(records,{c:threshold for c in range(3)})
        sweep[str(threshold)]=metrics
    chosen={}
    for c,name in enumerate(NAMES):
        def score(key):
            m=sweep[key][name];p=m['precision'] or 0;r=m['recall'] or 0
            return min(p,r),2*p*r/(p+r) if p+r else 0,-float(key)
        chosen[c]=float(max(sweep,key=score))
    metrics,errors=evaluate(records,chosen)
    result=dict(split='val',rule='Per-class threshold maximizes min(precision, recall), ties broken by F1 then lower threshold; grid 0.01 to 0.99; IoU 0.50.',
                thresholds={NAMES[c]:v for c,v in chosen.items()},metrics=metrics,sweep=sweep,
                selected_before_test_at=time.time(),errors=errors)
    (OUT/'frozen_thresholds.json').write_text(json.dumps(result,indent=2))
    return chosen,result


def assessment(thresholds,validation):
    payload=json.loads((OUT/'test/predictions.json').read_text())
    metrics,errors=evaluate(payload['images'],thresholds)
    fixed,_=evaluate(payload['images'],{c:.5 for c in range(3)})
    for name,m in metrics.items():
        m['precision_95pct_interval']=wilson(m['tp'],m['tp']+m['fp'])
        m['recall_95pct_interval']=wilson(m['tp'],m['tp']+m['fn'])
        m['point_estimate_meets_99']=m['precision'] is not None and m['recall'] is not None and m['precision']>=.99 and m['recall']>=.99
    goal=all(m['point_estimate_meets_99'] for m in metrics.values())
    supported=all(m['precision_95pct_interval'] and m['recall_95pct_interval'] and min(m['precision_95pct_interval'][0],m['recall_95pct_interval'][0])>=.99 for m in metrics.values())
    val_errors=Counter(f"{e['class_name']} / {e['kind']} / {e.get('size','')}" for e in validation['errors'])
    learning=list(csv.DictReader((RUN/'results.csv').read_text().splitlines()))
    learning=[{k.strip():float(v) for k,v in row.items()} for row in learning]
    change=learning[-1]['metrics/mAP50-95(B)']-learning[max(0,len(learning)-6)]['metrics/mAP50-95(B)']
    recommendations=[]
    if goal:
        recommendations.append('The frozen-threshold point estimates meet 99% for all three classes on this synthetic test set. More random synthetic data is not justified by this result alone.')
    else:
        recommendations.append('The 99% precision-and-recall target is not met for every class. This run alone cannot establish that data quantity is the bottleneck; do not assume more random renders will fix it.')
        for name in NAMES:
            if not metrics[name]['point_estimate_meets_99']:
                misses=Counter(e.get('size') for e in validation['errors'] if e['class_name']==name and e['kind']=='miss')
                recommendations.append(f'{name}: validation misses by native box size {dict(misses)}. Inspect the validation gallery and add training-only examples of the observed failure types, plus hard negatives for false detections. Keep evaluation scenes separate.')
        if change>.005:
            recommendations.append('Validation mAP50-95 was still improving over the last five epochs; first compare additional fine-tuning against targeted data expansion using validation only.')
    if not supported:
        recommendations.append('The available sample counts do not support claiming a 99% lower confidence bound for every class. A larger independent evaluation set, especially teammates, is needed to substantiate reliability.')
    recommendations.append('Test real gameplay separately. The synthetic generator deliberately favors visible targets, has one player per positive crop, and almost always shows the head. It does not cover natural gameplay frequency or multi-player center crops.')
    report=dict(goal='Precision >= 0.99 AND recall >= 0.99 for EACH of enemy, teammate and head; class-aware IoU >= 0.50.',
                images=len(payload['images']),split='test',thresholds=validation['thresholds'],
                threshold_policy=validation['rule'],threshold_file_sha256=hashlib.sha256((OUT/'frozen_thresholds.json').read_bytes()).hexdigest(),
                checkpoint=payload['configuration'],test_metrics=metrics,fixed_confidence_05=fixed,
                point_estimate_goal_met=goal,all_wilson_lower_bounds_ge_99=supported,
                confidence_interval_note='Approximate binomial Wilson intervals; objects/frames within a scene are correlated, so these are descriptive, not a scene-independent certification.',
                validation_failure_counts=dict(val_errors),test_errors=errors,
                training_epochs=len(learning),last_five_epoch_map5095_change=change,recommendations=recommendations)
    (OUT/'assessment.json').write_text(json.dumps(report,indent=2))
    lines=['CENTER-CROP TRAINING ASSESSMENT','',report['goal'],f'Test images: {report["images"]}',f'Goal met (point estimates): {goal}',
           '','Thresholds were selected on validation and frozen before test evaluation.','']
    for name,m in metrics.items():
        lines.append(f'{name}: threshold {validation["thresholds"][name]:.2f} | precision {m["precision"]:.4%} | recall {m["recall"]:.4%} | TP {m["tp"]}, FP {m["fp"]}, FN {m["fn"]}')
    lines+=['',*recommendations,'','Full metrics: assessment.json','Annotated validation failures: val/index.html','Annotated test failures at fixed confidence 0.50: test/index.html']
    (OUT/'assessment.txt').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines),flush=True)


def main():
    global RUN, DATA, OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,default=RUN)
    parser.add_argument('--dataset',type=Path,default=DATA)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--validation-only',action='store_true')
    args=parser.parse_args();RUN=args.run.resolve();DATA=args.dataset.resolve();OUT=args.output.resolve()
    OUT.mkdir(parents=True,exist_ok=True)
    state=dict(phase='waiting_for_training',started_at=time.time())
    def update(**values):
        state.update(values,updated_at=time.time())
        temp=OUT/'evaluation_status.tmp';temp.write_text(json.dumps(state,indent=2));temp.replace(OUT/'evaluation_status.json')
    def analyze(split):
        with (OUT/f'{split}_analysis.log').open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-u','tools/analyze_detection_failures.py','--checkpoint',str(RUN/'weights/best.pt'),
                            '--dataset',str(DATA),'--imgsz','416','--split',split,'--output',str(OUT/split)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    update()
    try:
        while True:
            status=json.loads((RUN/'training_status.json').read_text())
            if status['phase']=='complete':break
            if status['phase'] in ['failed','interrupted']:raise RuntimeError(status.get('error','Training failed'))
            time.sleep(10)
        update(phase='validation_threshold_selection')
        analyze('val')
        thresholds,validation=freeze_thresholds()
        if args.validation_only:
            update(phase='complete',thresholds=validation['thresholds'],metrics=validation['metrics'])
            print(json.dumps(validation['metrics'],indent=2));return
        update(phase='held_out_test',thresholds=validation['thresholds'])
        analyze('test')
        assessment(thresholds,validation)
        update(phase='complete',assessment=str(OUT/'assessment.txt'))
    except BaseException as error:
        update(phase='failed',error=str(error))
        raise
    finally:
        # The crop run temporarily took priority; preserve the user's earlier experiment.
        previous=ROOT/'runs/analysis/comparison_status.json'
        if previous.exists() and json.loads(previous.read_text()).get('phase')=='queued_for_resume':
            with (OUT/'fullscreen_resume.log').open('w',encoding='utf-8') as log:
                job=subprocess.Popen([sys.executable,'-u','tools/run_detection_comparison.py'],cwd=ROOT,
                                     stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            state['resumed_fullscreen_coordinator_pid']=job.pid
            update()


if __name__=='__main__':main()
