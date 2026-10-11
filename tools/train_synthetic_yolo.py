"""Train a three-class YOLO baseline, then evaluate best.pt on the held-out test split."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time
import traceback

os.environ.setdefault('OMP_NUM_THREADS', '4')
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--imgsz', type=int, default=960)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--patience', type=int, default=8)
    parser.add_argument('--name', default='yolo11n_synthetic_960')
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--model', choices=['yolo11n', 'yolo11s'], default='yolo11n')
    parser.add_argument('--test-only', action='store_true')
    parser.add_argument('--skip-test', action='store_true', help='Keep test split reserved during model comparisons.')
    parser.add_argument('--dataset', type=Path, default=ROOT/'datasets/valorant_synthetic_10k')
    parser.add_argument('--init-weights', type=Path)
    parser.add_argument('--train-list', type=Path, help='Optional training image subset; validation and test stay unchanged.')
    parser.add_argument('--lr0', type=float, default=.001)
    args = parser.parse_args()
    import torch
    import ultralytics
    from ultralytics import YOLO
    torch.set_num_threads(4)
    assert torch.cuda.is_available(), 'CUDA is required for this local training run.'
    dataset = args.dataset.resolve()
    audit = json.loads((dataset/'audit.json').read_text())
    assert audit['images'] > 0 and audit['class_names'] == ['enemy','teammate','head']
    assert audit['cross_split_scene_overlap'] == 0
    run = ROOT/'runs/train'/args.name
    if not args.resume and not args.test_only:
        assert not (run/'weights/last.pt').exists(), 'Run already has weights; use --resume or a different --name.'
    run.mkdir(parents=True, exist_ok=True)
    data_config=dataset/'data.yaml'
    if args.train_list:
        import yaml
        config=yaml.safe_load(data_config.read_text())
        config['path']=dataset.as_posix()
        config['train']=args.train_list.resolve().as_posix()
        data_config=run/'data.yaml'
        data_config.write_text(yaml.safe_dump(config))
    status = {'phase':'initializing','pid':os.getpid(),'run_dir':str(run),'started_at':time.time(),
              'epochs_planned':args.epochs,'epochs_completed':0,'epoch':0,'batch':0,'batches_per_epoch':0,
              'model':args.model,'imgsz':args.imgsz,'gpu':torch.cuda.get_device_name(0),'classes':audit['class_names']}
    if args.test_only:
        status.update(json.loads((run/'training_status.json').read_text()))
        status.update(pid=os.getpid(), phase='testing', epochs_completed=min(status['epochs_completed'],status['epochs_planned']))

    def write_status(**updates):
        status.update(updates);status['updated_at']=time.time()
        temporary=run/'training_status.tmp'
        temporary.write_text(json.dumps(status,indent=2),encoding='utf-8')
        for attempt in range(10):
            try:
                temporary.replace(run/'training_status.json');break
            except PermissionError:
                if attempt==9:raise
                time.sleep(.05)

    def epoch_start(trainer):
        write_status(phase='training',epoch=trainer.epoch+1,batch=0,
                     batches_per_epoch=len(trainer.train_loader),epochs_planned=trainer.epochs,
                     batch_size=trainer.batch_size)

    def batch_end(trainer):
        status['batch']+=1
        if status['batch']%20==0 or status['batch']==len(trainer.train_loader):
            write_status(phase='validating' if status['batch']==len(trainer.train_loader) else 'training')

    def epoch_end(trainer):
        write_status(phase='epoch_complete',epochs_completed=min(trainer.epoch+1,trainer.epochs),
                     metrics={str(k):float(v) for k,v in trainer.metrics.items()},
                     best_fitness=float(trainer.best_fitness),last_epoch_seconds=float(trainer.epoch_time or 0))

    write_status()
    try:
        pretrained=args.init_weights.resolve() if args.init_weights else ROOT/'models/pretrained'/f'{args.model}.pt'
        pretrained.parent.mkdir(parents=True,exist_ok=True)
        model=YOLO(str(run/'weights/best.pt') if args.test_only else str(args.resume.resolve()) if args.resume else str(pretrained))
        model.add_callback('on_train_epoch_start',epoch_start)
        model.add_callback('on_train_batch_end',batch_end)
        model.add_callback('on_fit_epoch_end',epoch_end)
        settings=dict(data=str(data_config),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,
                      workers=args.workers,device=0,project=str(run.parent),name=run.name,exist_ok=True,
                      patience=args.patience,seed=20261011,deterministic=True,amp=True,
                      optimizer='AdamW',lr0=args.lr0,lrf=.01,cos_lr=True,weight_decay=.0005,
                      warmup_epochs=3,warmup_bias_lr=0.0,rect=args.imgsz!=416,cache=False,
                      hsv_h=0.0,hsv_s=.10,hsv_v=.20,fliplr=.5,flipud=0.,
                      degrees=3.,translate=.08,scale=.25,shear=0.,perspective=0.,
                      mosaic=0.,mixup=0.,cutmix=0.,close_mosaic=0,
                      save=True,save_period=5,plots=True,val=True,verbose=False)
        manifest={'settings':settings,'dataset_audit_sha256':hashlib.sha256((dataset/'audit.json').read_bytes()).hexdigest(),
                  'versions':{'python':platform.python_version(),'torch':torch.__version__,'ultralytics':ultralytics.__version__},
                  'device':status['gpu'],'pretrained':str(pretrained),'model_docs':'https://docs.ultralytics.com/models/yolo11/',
                  'evaluation_policy':'Best checkpoint selected on val; test used once after training.',
                  'augmentation_policy':'No hue shift or mosaic/mixup; preserve team colors and separated players.'}
        if args.train_list:manifest['training_subset_sha256']=hashlib.sha256(args.train_list.read_bytes()).hexdigest()
        if pretrained.exists():manifest['pretrained_sha256']=hashlib.sha256(pretrained.read_bytes()).hexdigest()
        if not args.test_only:
            (run/'training_manifest.json').write_text(json.dumps(manifest,indent=2))
            model.train(resume=True) if args.resume else model.train(**settings)
        best=run/'weights/best.pt'
        assert best.is_file()
        if args.skip_test:
            write_status(phase='complete',best_checkpoint=str(best),test_skipped=True,
                         elapsed_seconds=time.time()-status['started_at'])
            return
        write_status(phase='testing',best_checkpoint=str(best))
        detector=YOLO(str(best))
        assert list(detector.names.values())==audit['class_names']
        metrics=detector.val(data=str(dataset/'data.yaml'),split='test',imgsz=args.imgsz,
                             batch=args.batch,device=0,workers=0,rect=True,
                             plots=True,save_json=True,conf=.001,iou=.7,max_det=100,
                             project=str(run),name='test',exist_ok=True,verbose=True)
        per_class=[]
        for index,class_id in enumerate(metrics.box.ap_class_index):
            p,r,map50,map5095=metrics.box.class_result(index)
            per_class.append({'class':detector.names[int(class_id)],'precision':float(p),'recall':float(r),
                              'mAP50':float(map50),'mAP50_95':float(map5095)})
        report={'best_checkpoint':str(best),'best_checkpoint_sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
                'split':'test','images':1000,'metrics':{k:float(v) for k,v in metrics.results_dict.items()},
                'per_class':per_class,'speed_ms_per_image':metrics.speed,
                'note':'Synthetic held-out scenes only; this does not establish real-game performance.'}
        (run/'test_evaluation.json').write_text(json.dumps(report,indent=2))
        write_status(phase='complete',test_metrics=report['metrics'],test_per_class=per_class,
                     elapsed_seconds=time.time()-status['started_at'])
        print(json.dumps(report,indent=2),flush=True)
    except BaseException as error:
        write_status(phase='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',
                     error=str(error),traceback=traceback.format_exc())
        raise


if __name__=='__main__':main()
