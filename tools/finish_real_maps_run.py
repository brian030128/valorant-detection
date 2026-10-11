"""Wait for a running real-map render, then audit/package and publish its private dataset."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renders',type=Path,default=ROOT/'datasets/valorant_real_maps_30000')
    parser.add_argument('--output',type=Path,default=ROOT/'datasets/valorant_detection_400_v5')
    parser.add_argument('--package',type=Path,default=ROOT/'exports/hf_detection400_v5')
    parser.add_argument('--publish',action='store_true',help='Upload the audited package to the existing private HF dataset')
    args=parser.parse_args()
    status=ROOT/'exports/real_maps_pipeline_status.json'
    def save(phase,**extra):
        status.write_text(json.dumps(dict(phase=phase,updated_at=time.time(),renders=str(args.renders),output=str(args.output),**extra),indent=2))
        print(phase,flush=True)
    try:
        save('waiting_for_render')
        deadline=time.monotonic()+4*3600
        while True:
            try:state=json.loads((args.renders/'generation_status.json').read_text())
            except (FileNotFoundError,json.JSONDecodeError):state={}
            if state.get('phase')=='failed':raise RuntimeError(state.get('error','Rendering failed'))
            if state.get('phase')=='complete':break
            if time.monotonic()>deadline:raise TimeoutError('Rendering did not finish within four hours; nothing published')
            time.sleep(5)
        assert state['images']==30000
        save('packaging_and_verifying_heldout_splits')
        subprocess.run([sys.executable,'-u',str(ROOT/'tools/package_real_maps_dataset.py'),
                        '--renders',str(args.renders),'--output',str(args.output)],cwd=ROOT,check=True)
        save('publishing' if args.publish else 'building_upload_package')
        command=[sys.executable,'-u',str(ROOT/'tools/publish_center_dataset.py'),
                 '--dataset',str(args.output),'--package',str(args.package)]
        if not args.publish:command.append('--package-only')
        subprocess.run(command,cwd=ROOT,check=True)
        result=json.loads((ROOT/'exports/hf_upload_result.json').read_text()) if args.publish else {}
        save('published' if args.publish else 'package_ready',result=result)
    except BaseException as error:
        save('failed',error=str(error))
        raise


if __name__=='__main__':
    main()
