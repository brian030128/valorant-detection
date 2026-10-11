"""Convert supplied Blender maps and render resumable, native 400px Godot samples."""
import argparse
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
    assert process.returncode == 0 and marker in log.read_text(encoding='utf-8', errors='replace'), str(log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path, default=Path('C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'))
    parser.add_argument('--output', type=Path, default=ROOT/'datasets/valorant_real_maps_30000')
    parser.add_argument('--pilot', type=int, default=0, help='Render this many per map instead of the full quotas')
    parser.add_argument('--maps', nargs='*')
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    logs = output/'logs'; logs.mkdir(exist_ok=True)
    manifest = json.loads((ROOT/'assets/source/valorant_maps/manifest.json').read_text())
    converter = ROOT/'tools/convert_blender_map.py'
    renderer = ROOT/'environment/real_maps_dataset.gd'
    version = digest(converter)
    records = [(i, r) for i, r in enumerate(manifest['maps']) if not args.maps or r['name'].lower() in args.maps]
    total = sum(args.pilot or r['planned_training_images'] for _, r in records)
    state = {'phase': 'converting', 'target': total, 'completed_maps': [], 'started_at': time.time(),
             'converter_sha256': version, 'renderer_sha256': digest(renderer)}
    def save():
        (output/'generation_status.json').write_text(json.dumps(state, indent=2))
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
            state.update(phase='rendering', current_map=name); save()
            count = args.pilot or record['planned_training_images']
            command = [str(ROOT/'tools/godot/Godot_v4.7.2-stable_win64_console.exe'), '--path', str(ROOT/'environment'),
                       '--rendering-method', 'gl_compatibility', '--disable-vsync', '--position', '-10000,-10000',
                       'real_maps_dataset.tscn', '--', f'--map={name}', f'--map-number={number}',
                       f'--count={count}', f'--output={output.as_posix()}']
            run(command, logs/f'render_{name}.log', 'REAL_MAP_COMPLETE')
            state['completed_maps'].append(name); save()
            print(f'MAP_COMPLETE {name} {len(state["completed_maps"])}/{len(records)}', flush=True)
        state.update(phase='auditing'); save()
        run([sys.executable, '-u', str(ROOT/'tools/finalize_synthetic_dataset.py'), str(output), '--expected', str(total), '--workers', '4'],
            logs/'audit.log', '"duplicate_images": 0')
        metadata = [json.loads(p.read_text()) for p in (output/'metadata/train').glob('*.json')]
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
