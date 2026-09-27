#!/usr/bin/env python3
"""Stage a reviewed character cutout on a uniform chroma backdrop, offline."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageOps
from video_to_sprite import matte

def prepare(image, out, matte_config=None, height_ratio=0.65, background=(255,0,255)):
    if not 0.3 <= height_ratio <= 0.75:
        raise ValueError('height_ratio must be 0.3..0.75 to retain motion margins')
    out=Path(out)
    if out.exists(): raise ValueError('Output already exists; preserve earlier references')
    im=ImageOps.exif_transpose(Image.open(image)).convert('RGBA')
    if im.getchannel('A').getextrema()[0]==255:
        if not matte_config:
            raise ValueError('Opaque input: supply a reviewed cutout or explicit --matte-config for the ORIGINAL background. Padding alone cannot replace its background.')
        cfg=json.loads(Path(matte_config).read_text())
        im,_=matte(im,cfg.get('matte',cfg))
    box=im.getbbox()
    if not box: raise ValueError('Empty character cutout')
    figure=im.crop(box)
    target_height=round(640*height_ratio)
    figure.thumbnail((448,target_height),Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(640,640),background)
    canvas.paste(figure,((640-figure.width)//2,round(640*0.85)-figure.height),figure)
    out.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(out)
    return {'output':str(out),'background':list(background),'figure_size':list(figure.size),'network_calls':0}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--out',required=True)
    p.add_argument('--matte-config',help='Opt-in matte settings for the original opaque reference')
    p.add_argument('--height-ratio',type=float,default=0.65)
    p.add_argument('--background',default='FF00FF',help='Six-digit RGB; choose another color if it occurs on the character')
    a=p.parse_args();color=a.background.lstrip('#')
    if len(color)!=6: p.error('background must be six hexadecimal digits')
    rgb=tuple(int(color[i:i+2],16) for i in (0,2,4))
    print(json.dumps(prepare(a.image,a.out,a.matte_config,a.height_ratio,rgb)))

if __name__=='__main__': main()
