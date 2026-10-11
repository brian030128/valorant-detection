"""Read-only live training progress; Ctrl+C does not stop training."""
import argparse
from pathlib import Path
import sys
import time
from dataset_progress import bar, enable_ansi, read_json

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',nargs='?',type=Path,default=ROOT/'runs/train/yolo11n_synthetic_960')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--interval',type=float,default=2)
    args=parser.parse_args()
    if args.interval<=0:parser.error('--interval must be positive')
    ansi=enable_ansi();lines_before=0
    try:
        while True:
            state=read_json(args.run/'training_status.json')
            if not state:
                lines=['Waiting for training_status.json...',str(args.run)]
            else:
                epoch=state.get('epoch',0);total=state['epochs_planned'];batches=state.get('batches_per_epoch',0)
                elapsed=int(state.get('elapsed_seconds',time.time()-state['started_at']));phase=state['phase']
                lines=[f'{state.get("model", "YOLO11n")} | {phase.upper()} | {state["gpu"]}',
                       bar('Epochs finished',state['epochs_completed'],max(1,total),30),
                       bar(f'Epoch {epoch} batches',state.get('batch',0),max(1,batches),30),
                       f'Elapsed: {elapsed//3600}h {elapsed%3600//60}m {elapsed%60}s | Image size: {state["imgsz"]}',
                       ' | '.join(f'{k.split("/")[-1]}: {v:.4f}' for k,v in state.get('metrics',{}).items() if 'mAP' in k),
                       f'Status updated {max(0,int(time.time()-state["updated_at"]))}s ago | PID {state["pid"]}',
                       'Ctrl+C stops this monitor only.']
                if state.get('last_epoch_seconds'):
                    remaining=state['last_epoch_seconds']*(total-state['epochs_completed'])
                    lines.insert(-1,f'Estimated remaining (max epochs): {remaining/60:.1f} min; early stopping may finish sooner.')
                if state.get('error'):lines.append(state['error'])
            import shutil
            columns=shutil.get_terminal_size((100,24)).columns
            lines=[line[:max(1,columns-1)] for line in lines]
            if ansi and lines_before:sys.stdout.write(f'\x1b[{lines_before}F\x1b[J')
            print('\n'.join(lines),flush=True);lines_before=len(lines)
            if args.once or (state and state['phase'] in ('complete','failed','interrupted')):break
            time.sleep(args.interval)
    except KeyboardInterrupt:print('\nMonitor stopped; training is unaffected.')

if __name__=='__main__':main()
