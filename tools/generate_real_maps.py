"""Convert supplied Blender maps and render resumable, native 400px Godot samples."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, marker):
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    output=log.read_text(encoding='utf-8',errors='replace')
    if process.returncode != 0 or marker not in output or 'SCRIPT ERROR:' in output:
        raise RuntimeError(f'Process failed (exit {process.returncode}); see {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anatomy',action='store_true')
    parser.add_argument('--teammate-negatives',action='store_true')
    parser.add_argument('--total-images',type=int,help='Distribute exactly this many images across selected maps.')
    parser.add_argument('--blender', type=Path, default=Path('C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'))
    parser.add_argument('--output', type=Path, default=ROOT/'datasets/valorant_real_maps_30000')
    parser.add_argument('--start', type=int, default=0, help='First local sample index; use a new range for evaluation renders')
    parser.add_argument('--split', choices=['train','val','test'], default='train')
    parser.add_argument('--pilot', type=int, default=0, help='Render this many per map instead of the full quotas')
    parser.add_argument('--maps', nargs='*')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--workers', type=int, choices=[1,2,3], default=2)
    parser.add_argument('--rerender-map', nargs='*', default=[])
    args = parser.parse_args()
    if args.teammate_negatives and not args.anatomy:parser.error('--teammate-negatives requires --anatomy')
    assert args.batch_size > 0 and args.start >= 0
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    logs = output/'logs'; logs.mkdir(exist_ok=True)
    manifest = json.loads((ROOT/'assets/source/valorant_maps/manifest.json').read_text())
    converter = ROOT/'tools/convert_blender_map.py'
    renderer = ROOT/'environment/real_maps_dataset.gd'
    version = digest(converter)
    records = [(i, r) for i, r in enumerate(manifest['maps']) if not args.maps or r['name'].lower() in args.maps]
    if args.total_images:
        records=[(i,dict(r,planned_training_images=args.total_images//len(records)+int(j<args.total_images%len(records)))) for j,(i,r) in enumerate(records)]
    total = sum(args.pilot or r['planned_training_images'] for _, r in records)
    old_state=json.loads((output/'generation_status.json').read_text()) if (output/'generation_status.json').exists() else {}
    renderer_history=old_state.get('renderer_history',[])
    if old_state.get('renderer_sha256') and old_state['renderer_sha256'] not in renderer_history:
        renderer_history.append(old_state['renderer_sha256'])
    state = {'phase': 'converting', 'target': total, 'completed_maps': [], 'started_at': time.time(),
             'sample_start':args.start, 'split':args.split, 'renderer_history':renderer_history, 'worker_limit':args.workers, 'active_workers':{},
             'converter_sha256': version, 'renderer_sha256': digest(renderer)}
    state_lock=threading.RLock()
    def save():
        with state_lock:
            temporary=output/'generation_status.tmp'
            temporary.write_text(json.dumps(state, indent=2))
            for retry in range(5):
                try:
                    temporary.replace(output/'generation_status.json')
                    break
                except PermissionError:
                    if retry==4:raise
                    time.sleep(.05)
    save()
    try:
        for number, record in records:
            name = record['name'].lower(); state.update(phase='converting', current_map=name); save()
            folder = ROOT/'assets/generated/valorant_maps'/name; folder.mkdir(parents=True, exist_ok=True)
            cache = folder/'build_version.txt'
            if not cache.exists() or cache.read_text() != version:
                command = [str(args.blender), '--background', '--factory-startup', '--disable-autoexec', '--threads', '4',
                           '--python', str(converter), '--', str(ROOT/'assets/source/valorant_maps'/record['file']), str(folder)]
                run(command, logs/f'convert_{name}.log', 'MAP_CONVERSION_COMPLETE')
                cache.write_text(version)
            report = json.loads((folder/'conversion.json').read_text())
            assert report['source_sha256'] == record['sha256']
            assert report['viewpoints'] > 100
        state.update(phase='rendering');save()
        def render_record(item):
            number,record=item
            name=record['name'].lower()
            count = args.pilot or record['planned_training_images']
            command = [str(ROOT/'tools/godot/Godot_v4.7.2-stable_win64_console.exe'), '--path', str(ROOT/'environment'),
                       '--rendering-method', 'gl_compatibility', '--disable-vsync', '--position', '-10000,-10000',
                       'real_maps_dataset.tscn', '--', f'--map={name}', f'--map-number={number}',
                       f'--output={output.as_posix()}',f'--split={args.split}']
            if args.anatomy:command.append('--anatomy')
            if args.teammate_negatives:command.append('--teammate-negatives')
            for start in range(args.start, args.start+count, args.batch_size):
                size = min(args.batch_size, args.start+count-start)
                stems = [str(1000000+number*10000+i) for i in range(start,start+size)]
                if name not in args.rerender_map and all(
                    (output/folder/args.split/(stem+suffix)).exists()
                    for stem in stems for folder,suffix in [('metadata','.json'),('images','.jpg'),('masks','.png')]):
                    continue
                stalled=0
                prior_completed=sum((output/'metadata'/args.split/(stem+'.json')).exists() for stem in stems)
                for attempt in range(10):
                    log = logs/f'render_{name}_{start:04d}_n{size}_attempt{attempt+1}.log'
                    with state_lock:
                        progress=dict(current_map=name,batch_start=start,batch_size=size,attempt=attempt+1,current_log=str(log))
                        state['active_workers'][name]=progress
                        state.update(progress);save()
                    batch = command+[f'--start={start}',f'--count={size}']
                    if name in args.rerender_map:batch.append('--overwrite')
                    try:
                        run(batch, log, 'REAL_MAP_COMPLETE')
                        break
                    except RuntimeError:
                        completed=sum((output/'metadata'/args.split/(stem+'.json')).exists() for stem in stems)
                        stalled=stalled+1 if completed<=prior_completed else 0
                        prior_completed=completed
                        if stalled>=3 or attempt==9:raise
                        print(f'RETRY {name} batch {start} after process failure',flush=True)
                print(f'BATCH_COMPLETE {name} {start+size-args.start}/{count}',flush=True)
            with state_lock:
                state['active_workers'].pop(name,None)
                state['completed_maps'].append(name);save()
                print(f'MAP_COMPLETE {name} {len(state["completed_maps"])}/{len(records)}',flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(render_record,item) for item in records]
            for future in as_completed(futures):future.result()
        state.update(phase='auditing',current_log=str(logs/'audit.log')); save()
        finalizer='finalize_anatomy_dataset.py' if args.anatomy else 'finalize_synthetic_dataset.py'
        run([sys.executable, '-u', str(ROOT/'tools'/finalizer), str(output), '--expected', str(total), '--workers', '4'],
            logs/'audit.log', '"duplicate_images": 0')
        metadata = [json.loads(p.read_text()) for p in (output/'metadata'/args.split).glob('*.json')]
        diversity = {}
        for _, record in records:
            name = record['name'].lower(); subset = [m for m in metadata if m['scene_family'] == name]
            diversity[name] = {'images': len(subset), 'regions': len({m['spatial_region'] for m in subset}),
                               'viewpoints': len({m['map_viewpoint'] for m in subset}),
                               'crosshair_styles': sorted({m['crosshair']['style'] for m in subset})}
        (output/'diversity.json').write_text(json.dumps(diversity, indent=2))
        state.update(phase='complete', images=total, completed_at=time.time()); save()
        print('REAL_MAP_DATASET_COMPLETE', total, flush=True)
    except BaseException as error:
        state.update(phase='failed', error=str(error)); save()
        raise


if __name__ == '__main__':
    main()
