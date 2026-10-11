"""Check visibility semantics for opaque HUD pixels, including tiny fully covered heads."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evaluate_texture_crosshairs import adjusted_truth,overlay

class HudVisibilityTests(unittest.TestCase):
    def scene(self):
        pixels=np.zeros((400,400,3),dtype=np.uint8)
        pixels[199:210,199:203,0]=32
        pixels[199:201,199:201,1]=255
        base={'truth':[{'class_id':0,'box':[199,199,203,210]},{'class_id':2,'box':[199,199,201,201]}]}
        annotation={'objects':[{'instance_id':1},{'instance_id':1}]}
        return base,annotation,pixels

    def test_dot_hides_head_but_retains_visible_body(self):
        b,a,p=self.scene();occluder=np.asarray(overlay('green_dot'))[:,:,3]==255
        truth,head,body,hidden=adjusted_truth(b,a,p,occluder)
        self.assertEqual([t['class_id'] for t in truth],[0])
        self.assertEqual(truth[0]['box'],[199,199,203,210])
        self.assertEqual((head,body,hidden),(True,True,1))

    def test_partial_head_box_is_clipped_to_visible_pixels(self):
        b,a,p=self.scene();occluder=np.zeros((400,400),dtype=bool);occluder[:,199]=True
        truth,_,_,hidden=adjusted_truth(b,a,p,occluder)
        self.assertEqual(truth[1]['box'],[200,199,201,201])
        self.assertEqual(hidden,0)

    def test_no_hud_keeps_truth_and_empty_stays_empty(self):
        b,a,p=self.scene();occluder=np.asarray(overlay('none'))[:,:,3]==255
        truth,head,body,hidden=adjusted_truth(b,a,p,occluder)
        self.assertEqual([t['box'] for t in truth],[t['box'] for t in b['truth']])
        self.assertEqual((head,body,hidden),(False,False,0))
        self.assertEqual(adjusted_truth({'truth':[]},{'objects':[]},p,occluder)[0],[])

if __name__=='__main__':unittest.main()
