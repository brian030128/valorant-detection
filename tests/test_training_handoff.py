"""Small checks for matching, archive extraction and confidence calculations."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from analyze_detection_failures import match
from evaluate_center_goal import evaluate,wilson
from train_h100 import extract,verify


class HandoffTests(unittest.TestCase):
    def test_matching_rejects_duplicates_wrong_classes_and_low_confidence(self):
        truth=[dict(class_id=0,box=[0,0,10,10])]
        predictions=[dict(class_id=c,box=box,confidence=confidence) for c,box,confidence in [
            (0,[0,0,10,10],.9),(0,[0,0,10,10],.8),(1,[0,0,10,10],.7),(0,[20,20,30,30],.2)]]
        matched,correct,false=match(truth,predictions,.5)
        self.assertEqual(matched,{0:0})
        self.assertEqual(correct,{0})
        self.assertEqual(false,[1,2])
        self.assertEqual(match([],predictions,.5)[2],[0,1,2])

    def test_per_class_frozen_thresholds_and_empty_false_positive(self):
        truth=dict(class_id=0,box=[0,0,10,10],size_bin='8-16px',character='test',view='front')
        records=[dict(stem='one',scene='test',truth=[truth],predictions=[dict(class_id=0,box=truth['box'],confidence=.6)]),
                 dict(stem='empty',scene='test',truth=[],predictions=[dict(class_id=1,box=[0,0,10,10],confidence=.8)])]
        metrics,errors=evaluate(records,{0:.5,1:.7,2:.5})
        self.assertEqual(metrics['enemy']['tp'],1)
        self.assertEqual(metrics['teammate']['fp'],1)
        self.assertEqual(len(errors),1)

    def test_small_perfect_sample_does_not_prove_99_percent(self):
        low,high=wilson(80,80)
        self.assertLess(low,.99)
        self.assertAlmostEqual(high,1)

    def test_safe_extraction_and_checksum(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'data.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('labels/train/a.txt','0 .5 .5 .1 .1')
            verify(archive,hashlib.sha256(archive.read_bytes()).hexdigest())
            extract(archive,root/'out')
            self.assertTrue((root/'out/labels/train/a.txt').exists())
            with self.assertRaises(RuntimeError):verify(archive,'0'*64)
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt','bad')
            with self.assertRaises(ValueError):extract(archive,root/'out')


if __name__=='__main__':unittest.main()
