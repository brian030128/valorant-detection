"""Enemy-only head labels retain visible body labels for both teams."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from finalize_synthetic_dataset import process


class EnemyHeadLabelsTests(unittest.TestCase):
    def test_mixed_teams_and_occluded_enemy_head(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for kind in ('images', 'masks', 'metadata'):
                (root / kind / 'test').mkdir(parents=True)
            pixels = np.zeros((20, 30, 3), dtype=np.uint8)
            actors = []
            for instance, role in ((1, 'enemy'), (2, 'teammate'), (3, 'enemy')):
                x = (instance - 1) * 10
                pixels[2:18, x:x+6, 0] = instance * 32
                if instance != 3:
                    pixels[2:5, x:x+6, 1] = 255
                actors.append(dict(instance_id=instance, role=role, character='test'))
            Image.new('RGB', (30, 20)).save(root / 'images/test/0.jpg')
            Image.fromarray(pixels).save(root / 'masks/test/0.png')
            meta = root / 'metadata/test/0.json'
            meta.write_text(json.dumps(dict(index=0, scene_group=0, scene_family='test',
                                           resolution=[30, 20], actors=actors)))
            annotation, _ = process(meta)
            self.assertEqual([(o['instance_id'], o['class']) for o in annotation['objects']],
                             [(1, 'enemy'), (1, 'head'), (2, 'teammate'), (3, 'enemy')])
            self.assertEqual(annotation['objects'][1]['bbox_xyxy'], [0, 2, 6, 5])
            self.assertEqual([line.split()[0] for line in
                              (root / 'labels/test/0.txt').read_text().splitlines()],
                             ['0', '2', '1', '0'])


if __name__ == '__main__':
    unittest.main()
