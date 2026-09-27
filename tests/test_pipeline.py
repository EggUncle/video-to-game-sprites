import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

spec=importlib.util.spec_from_file_location('pipeline',Path(__file__).resolve().parents[1]/'skill/scripts/video_to_sprite.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PipelineTests(unittest.TestCase):
    def test_enclosed_background_colored_armor_is_preserved(self):
        im=Image.new('RGB',(64,64),(190,190,190));d=ImageDraw.Draw(im)
        d.rectangle((15,10,45,55),fill=(20,30,80));d.rectangle((24,22,35,40),fill=(190,190,190))
        result,_=p.matte(im,{'threshold':25})
        a=np.array(result.getchannel('A'))
        self.assertEqual(a[0,0],0);self.assertEqual(a[30,30],255)

    def test_nonuniform_background_is_rejected(self):
        im=Image.new('RGB',(64,64),'white');ImageDraw.Draw(im).rectangle((0,0,6,6),fill='black')
        with self.assertRaises(ValueError):p.matte(im,{})

    def test_edge_unmix_removes_gray_without_darkening_interior(self):
        im=Image.new('RGB',(64,64),(190,190,190));d=ImageDraw.Draw(im)
        d.rectangle((14,9,46,56),fill=(125,130,145))
        d.rectangle((16,11,44,54),fill=(20,30,80))
        out,_=p.matte(im,{'decontaminate_radius':3,'decontaminate_tolerance':50})
        a=np.array(out)
        self.assertLess(a[30,14,3],200)
        self.assertLess(a[30,14,0],50)
        np.testing.assert_array_equal(a[30,30],[20,30,80,255])

    def test_enclosed_key_is_opt_in(self):
        im=Image.new('RGB',(64,64),(190,190,190));d=ImageDraw.Draw(im)
        d.rectangle((15,10,45,55),fill=(20,30,80));d.rectangle((24,22,35,40),fill=(190,190,190))
        out,_=p.matte(im,{'enclosed_key_threshold':14})
        self.assertEqual(np.array(out)[30,30,3],0)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'existing').write_text('keep')
            with self.assertRaises(ValueError):p.fresh(tmp)
            self.assertEqual(Path(tmp,'existing').read_text(),'keep')

    def test_sampled_vfr_timing_and_shared_transform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source';src.mkdir();mat=root/'mat';mat.mkdir()
            (mat/'frames').mkdir()
            times=[0,.04,.10,.15,.23,.30];entries=[]
            for i,t in enumerate(times):
                im=Image.new('RGBA',(64,64));ImageDraw.Draw(im).rectangle((20,10+i,35,40+i),fill=(20,80,120,255))
                rel=f'frames/{i:06d}.png';im.save(mat/rel)
                entries.append(dict(index=i,time=t,duration=.04,file=rel))
            p.dump(src/'source.json',dict(source='fixture.mp4'))
            p.dump(mat/'matte.json',dict(source_dir=str(src),source_sha256='fixture',frames=entries))
            config=root/'clip.json';p.dump(config,dict(start=0,end_exclusive=5,indices=[0,2,4],cell=[64,64]))
            p.build(mat,config,root/'out')
            manifest=json.loads((root/'out/animation.json').read_text())
            self.assertAlmostEqual(manifest['duration'],.30)
            np.testing.assert_allclose([f['duration'] for f in manifest['frames']],[.10,.13,.07])
            boxes=[f['bbox'] for f in manifest['frames']]
            self.assertLess(boxes[0][1],boxes[1][1]);self.assertLess(boxes[1][1],boxes[2][1])
            self.assertEqual(manifest['frame_count'],3)
            self.assertFalse(manifest['qc']['touches_edge'])
            with Image.open(root/'out/frames/000.png') as im:
                self.assertEqual(im.mode,'RGBA')

if __name__=='__main__':unittest.main()
