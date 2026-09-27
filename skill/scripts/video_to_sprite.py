#!/usr/bin/env python3
"""Local, reproducible video -> timed PNGs -> matte -> loop candidates -> sprite pack."""
import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def fresh(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f'Output is not empty: {path}. Choose a new version directory.')
    path.mkdir(parents=True, exist_ok=True)
    return path


def contact(images, labels, path, columns=6, size=160):
    canvas = Image.new('RGB', (columns * size, math.ceil(len(images) / columns) * (size + 22)), '#dadada')
    draw = ImageDraw.Draw(canvas)
    for i, (im, label) in enumerate(zip(images, labels)):
        im = im.copy().convert('RGBA')
        im.thumbnail((size, size), Image.Resampling.NEAREST)
        x, y = i % columns * size, i // columns * (size + 22)
        canvas.paste(im, (x + (size-im.width)//2, y + (size-im.height)//2), im)
        draw.text((x+4, y+size+3), str(label), fill='black')
    canvas.save(path)


def extract(source, out):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError(f'Missing video: {source}')
    out = fresh(out)
    frames = out / 'frames'
    frames.mkdir()
    reader = imageio_ffmpeg.read_frames(str(source))
    metadata = next(reader)
    reader.close()
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-i', str(source),
           '-map', '0:v:0', '-an', '-vf', 'showinfo', '-fps_mode', 'passthrough',
           '-start_number', '0', str(frames / '%06d.png')]
    run = subprocess.run(cmd, capture_output=True, text=True)
    (out / 'decode.log').write_text(run.stderr)
    if run.returncode:
        raise RuntimeError(run.stderr[-3000:])
    pts = [float(t) for t in re.findall(r'\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.eE+\-]+)', run.stderr)]
    paths = sorted(frames.glob('*.png'))
    if len(pts) != len(paths) or not pts:
        raise ValueError('Decoded frame/timestamp count mismatch; see decode.log')
    pts = np.array(pts) - pts[0]
    if len(pts) > 1 and np.any(np.diff(pts) <= 0):
        raise ValueError('Non-monotonic timestamps; cannot build reliable animation timing')
    last_duration = float(np.median(np.diff(pts))) if len(pts)>1 else 1/metadata['fps']
    entries = []
    for i, path in enumerate(paths):
        dt = float(pts[i+1]-pts[i]) if i+1<len(pts) else last_duration
        entries.append(dict(index=i, file=str(path.relative_to(out)), time=float(pts[i]), duration=dt))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    result = dict(version=1, source=str(source), source_sha256=digest, metadata=metadata,
                  timestamp_source='ffmpeg showinfo presentation timestamps; last duration estimated',
                  frame_count=len(entries), frames=entries)
    dump(out/'source.json', result)
    ids = np.unique(np.linspace(0,len(paths)-1,min(30,len(paths)),dtype=int))
    contact([Image.open(paths[i]) for i in ids], [f'{i:03d} / {pts[i]:.3f}s' for i in ids], out/'overview.jpg')
    print(json.dumps(dict(output=str(out), frames=len(paths), metadata=metadata)))


def matte(im, cfg):
    rgb = np.array(im.convert('RGB'), dtype=np.float32)
    h,w = rgb.shape[:2]
    if cfg.get('key_color') is not None:
        key = np.array(cfg['key_color'], dtype=np.float32)
    else:
        n=max(2,min(h,w)//25)
        corners=np.concatenate([rgb[:n,:n].reshape(-1,3),rgb[:n,-n:].reshape(-1,3),
                                rgb[-n:,:n].reshape(-1,3),rgb[-n:,-n:].reshape(-1,3)])
        key=np.median(corners,axis=0)
        if np.percentile(np.linalg.norm(corners-key,axis=1),95)>cfg.get('corner_tolerance',25):
            raise ValueError('Background corners are not uniform. Use explicit key_color or external masks.')
    distance=np.linalg.norm(rgb-key,axis=2)
    threshold=float(cfg.get('threshold',32))
    # Only remove key-colored areas connected to the image border; preserve enclosed pale armor.
    near=distance<=threshold
    shadow=cfg.get('shadow',{})
    if shadow.get('enabled',False):
        yy=np.arange(h)[:,None]
        chroma=rgb.max(axis=2)-rgb.min(axis=2)
        near |= ((yy>=int(shadow.get('start_y',h*.80))) &
                 (chroma<=shadow.get('max_chroma',12)) &
                 (rgb.mean(axis=2)>=shadow.get('min_luma',70)))
    seed=np.zeros((h,w),bool)
    seed[0]=near[0];seed[-1]=near[-1];seed[:,0]=near[:,0];seed[:,-1]=near[:,-1]
    background=ndi.binary_propagation(seed, mask=near)
    fg=~background
    # Optional enclosed-hole keying; intentionally opt-in because an exact-key
    # costume region is mathematically indistinguishable from backdrop.
    hole_threshold=float(cfg.get('enclosed_key_threshold',0))
    if hole_threshold>0:
        holes,nholes=ndi.label(fg & (distance<hole_threshold))
        areas=np.bincount(holes.ravel())
        remove=(holes>0) & (areas[holes]>=int(cfg.get('enclosed_min_area',12)))
        fg[remove]=False
    labels,count=ndi.label(fg)
    if not count:
        raise ValueError('No foreground detected')
    sizes=np.bincount(labels.ravel()); sizes[0]=0
    minimum=int(cfg.get('min_component_area',80))
    if cfg.get('largest_component',True):
        fg=labels==sizes.argmax()
    else:
        fg=(sizes[labels]>=minimum) & (labels>0)
    if fg.sum()<minimum:
        raise ValueError('Foreground too small')
    # Conservative one-pixel boundary alpha + background unmixing; interiors unchanged.
    edge=fg & ~ndi.binary_erosion(fg)
    alpha=fg.astype(np.float32)
    softness=float(cfg.get('edge_softness',18))
    if softness>0:
        alpha[edge]=np.clip((distance[edge]-threshold*.5)/softness,0,1)
    out_rgb=rgb.copy()
    partial=(alpha>0)&(alpha<1)
    out_rgb[partial]=np.clip((rgb[partial]-(1-alpha[partial,None])*key)/alpha[partial,None],0,255)
    # Recover the foreground color in mixed edge pixels instead of retaining the
    # gray source backdrop as opaque RGB. Only a narrow configurable band changes.
    radius=int(cfg.get('decontaminate_radius',0))
    if radius>0:
        depth=ndi.distance_transform_edt(fg)
        core=depth>radius
        if core.any():
            _,nearest=ndi.distance_transform_edt(~core,return_indices=True)
            interior=rgb[nearest[0],nearest[1]]
            direction=interior-key
            denom=np.sum(direction*direction,axis=2)
            fitted=np.clip(np.sum((rgb-key)*direction,axis=2)/np.maximum(denom,1),0,1)
            reconstructed=key+fitted[:,:,None]*direction
            residual=np.linalg.norm(rgb-reconstructed,axis=2)
            band=fg & ~core & (denom>400) & (residual<float(cfg.get('decontaminate_tolerance',32)))
            alpha[band]=np.minimum(alpha[band],fitted[band])
            mixed=band & (alpha>0.01) & (alpha<0.98)
            out_rgb[mixed]=np.clip((rgb[mixed]-(1-alpha[mixed,None])*key)/alpha[mixed,None],0,255)
            if cfg.get('neutral_fringe_cleanup',False):
                # Video compression may tint gray fringe enough to fail the color-fit gate.
                # Target only bright neutral boundary pixels adjacent to a dark core.
                pale=(rgb.max(axis=2)-rgb.min(axis=2)<25) & (rgb.mean(axis=2)>110)
                dark_core=interior.mean(axis=2)<100
                fringe=fg & ~core & pale & dark_core
                alpha[fringe]=np.minimum(alpha[fringe],fitted[fringe])
                out_rgb[fringe]=interior[fringe]
            alpha[alpha<float(cfg.get('alpha_floor',0.12))]=0
    rgba=np.dstack([out_rgb,alpha*255]).astype(np.uint8)
    rgba[alpha==0,:3]=0
    return Image.fromarray(rgba),key.tolist()


def prepare(source_dir, config, out):
    source_dir=Path(source_dir).resolve()
    source=json.loads((source_dir/'source.json').read_text())
    cfg=json.loads(Path(config).read_text())
    out=fresh(out); (out/'frames').mkdir()
    entries=[]; features=[]; keys=[]; boxes=[]
    external=cfg.get('mask_directory')
    for entry in source['frames']:
        im=Image.open(source_dir/entry['file']).convert('RGB')
        if external:
            mask_path=(Path(config).resolve().parent/ external / f"{entry['index']:06d}.png").resolve()
            mask=Image.open(mask_path).convert('L')
            if mask.size!=im.size: raise ValueError(f'Mask size mismatch: {mask_path}')
            rgba=im.convert('RGBA');rgba.putalpha(mask);key=None
        else:
            rgba,key=matte(im,cfg.get('matte',{}))
        box=rgba.getbbox()
        if not box: raise ValueError('Empty matte')
        boxes.append(box);keys.append(key)
        rel=f"frames/{entry['index']:06d}.png";rgba.save(out/rel)
        entries.append(dict(entry,file=rel,bbox=list(box)))
        tiny=np.array(rgba.resize((80,80),Image.Resampling.BOX),dtype=np.float32)/255
        # Premultiplied color helps distinguish opposite arm/leg phases.
        features.append(np.concatenate([tiny[:,:,:3]*tiny[:,:,3:],tiny[:,:,3:]],axis=2))
    minlag=int(cfg.get('loop_min_frames',12));maxlag=int(cfg.get('loop_max_frames',36))
    margin=int(cfg.get('loop_margin_frames',6))
    features=np.array(features)
    candidates=[]
    for start in range(margin,len(entries)-minlag-1):
        for lag in range(minlag,maxlag+1):
            end=start+lag
            if end+1>=len(entries)-margin: continue
            # Compare endpoint and neighboring poses, not just a repeated silhouette.
            score=float(np.mean((features[start:start+2]-features[end:end+2])**2))
            candidates.append(dict(start=start,end_exclusive=end,frame_count=lag,
                                   duration=entries[end]['time']-entries[start]['time'],score=score))
    candidates.sort(key=lambda x:x['score'])
    # Avoid flooding the shortlist with immediately adjacent starts at the same period.
    best=[]
    for c in candidates:
        if all(abs(c['start']-b['start'])>=3 or abs(c['frame_count']-b['frame_count'])>=3 for b in best):
            best.append(c)
        if len(best)==12:break
    dump(out/'matte.json',dict(version=1,source_dir=str(source_dir),source_sha256=source['source_sha256'],
                             config=cfg,frame_count=len(entries),frames=entries,background_keys=keys,
                             loop_candidates=best,warning='Similarity is a shortlist, not proof of correct gait or a seamless loop.'))
    ids=np.unique(np.linspace(0,len(entries)-1,min(30,len(entries)),dtype=int))
    contact([Image.open(out/entries[i]['file']) for i in ids],
            [f'{i:03d} / {entries[i]["time"]:.3f}s' for i in ids],out/'overview.jpg')
    dump(out/'loop-candidates.json',best)
    print(json.dumps(dict(output=str(out),candidates=best[:4])))


def checker(size):
    yy,xx=np.indices((size[1],size[0]));v=np.where((xx//12+yy//12)%2,190,225).astype(np.uint8)
    return Image.fromarray(np.dstack([v,v,v])).convert('RGBA')


def build(matte_dir, config, out):
    matte_dir=Path(matte_dir).resolve()
    meta=json.loads((matte_dir/'matte.json').read_text())
    cfg=json.loads(Path(config).read_text())
    start=int(cfg['start']);end=int(cfg['end_exclusive'])
    entries=meta['frames']
    # Need endpoint timestamp so end is a real source frame, excluded from export.
    if not 0<=start<end<len(entries):raise ValueError('Need 0 <= start < end_exclusive < source frame count')
    ids=cfg.get('indices',list(range(start,end)))
    if not ids or ids[0]!=start or ids!=sorted(set(ids)) or any(i<start or i>=end for i in ids):
        raise ValueError('indices must be increasing unique source indices in [start,end), starting at start')
    cell=tuple(cfg.get('cell',[128,128]));padding=int(cfg.get('padding',8))
    if min(cell)<=2*padding:raise ValueError('Cell too small for padding')
    ims=[Image.open(matte_dir/entries[i]['file']).convert('RGBA') for i in ids]
    boxes=[im.getbbox() for im in ims]
    union=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
    scale=min((cell[0]-padding*2)/(union[2]-union[0]),(cell[1]-padding*2)/(union[3]-union[1]))
    target=(max(1,round((union[2]-union[0])*scale)),max(1,round((union[3]-union[1])*scale)))
    origin=((cell[0]-target[0])//2,cell[1]-padding-target[1])
    filter_name=cfg.get('resample','nearest')
    if filter_name not in ['nearest','lanczos']:raise ValueError('resample: nearest or lanczos')
    resample=Image.Resampling.NEAREST if filter_name=='nearest' else Image.Resampling.LANCZOS
    out=fresh(out);(out/'frames').mkdir()
    result=[];frames=[];durations=[]
    for k,(idx,im) in enumerate(zip(ids,ims)):
        frame=Image.new('RGBA',cell)
        frame.paste(im.crop(tuple(union)).resize(target,resample),origin)
        # Same crop, scale and placement for EVERY frame: preserve body bob and flight.
        rel=f'frames/{k:03d}.png';frame.save(out/rel)
        next_idx=ids[k+1] if k+1<len(ids) else end
        dt=entries[next_idx]['time']-entries[idx]['time']
        frames.append(frame);durations.append(dt)
        a=np.array(frame.getchannel('A'))
        touches=bool(a[0].any() or a[-1].any() or a[:,0].any() or a[:,-1].any())
        result.append(dict(file=rel,source_index=idx,source_time=entries[idx]['time'],duration=dt,
                           bbox=list(frame.getbbox()),touches_edge=touches))
    columns=int(cfg.get('columns',6))
    if columns<1:raise ValueError('columns must be positive')
    sheet=Image.new('RGBA',(cell[0]*columns,cell[1]*math.ceil(len(frames)/columns)))
    for i,frame in enumerate(frames):sheet.paste(frame,(i%columns*cell[0],i//columns*cell[1]))
    sheet.save(out/'spritesheet.png')
    # GIF is a convenience preview: browser preview below preserves millisecond timing more closely.
    gifs=[]
    for frame in frames:
        base=checker(cell);base.alpha_composite(frame)
        gifs.append(base.convert('RGB').resize((cell[0]*3,cell[1]*3),Image.Resampling.NEAREST))
    gifs[0].save(out/'preview.gif',save_all=True,append_images=gifs[1:],duration=[round(d*1000) for d in durations],**({'loop':0} if cfg.get('loop',True) else {}))
    contact(frames,[f'{i:02d} / src {idx}' for i,idx in enumerate(ids)],out/'contact.png',columns=columns)
    arrays=[np.array(f.resize((64,64)),dtype=float)/255 for f in frames]
    prem=[a[:,:,:3]*a[:,:,3:4] for a in arrays]
    delta=[float(np.mean(abs(prem[(i+1)%len(prem)]-prem[i]))) for i in range(len(prem))]
    source_path=Path(meta['source_dir'])/'source.json'
    provenance=json.loads(source_path.read_text())
    manifest=dict(version=1,name=cfg.get('name','animation'),loop=cfg.get('loop',True),cell=list(cell),
        frame_count=len(frames),duration=sum(durations),fps=len(frames)/sum(durations),
        source_sha256=meta['source_sha256'],source_video=provenance['source'],selection=cfg,
        transform=dict(source_union=union,scale=scale,target_size=list(target),placement=list(origin),
                       per_frame_alignment=False),frames=result,
        qc=dict(unique_frames=len({hashlib.sha256(f.tobytes()).hexdigest() for f in frames}),
                touches_edge=any(f['touches_edge'] for f in result),seam_difference=delta[-1],
                median_adjacent_difference=float(np.median(delta[:-1])) if len(delta)>1 else 0,
                production_approved=False,notes='Visual gait/identity/foot-contact review is still required.'))
    dump(out/'animation.json',manifest)
    payload=json.dumps(dict(frames=result,duration=sum(durations),cell=cell,loop=cfg.get('loop',True))).replace('</','<\\/')
    (out/'preview.html').write_text('''<!doctype html><meta charset="utf-8"><title>Sprite loop preview</title>
<style>body{background:#252936;color:#eee;font:16px system-ui;padding:24px}canvas{image-rendering:pixelated;background:repeating-conic-gradient(#ddd 0% 25%,#aaa 0% 50%) 0/24px 24px;margin:16px}button,input{margin:8px}a{color:#9cd}</style>
<h1>循环预览</h1><p>同一画布和缩放；保留腾空与重心起伏。左右键逐帧。</p>
<button id="play">暂停</button><label>速度 <input id="speed" type="range" min="0.25" max="2" value="1" step="0.25"></label><input id="scrub" type="range" min="0" value="0"><span id="info"></span><br><canvas id="actual"></canvas><canvas id="large"></canvas>
<script>const data='''+payload+''';const imgs=data.frames.map(f=>{let im=new Image();im.src=f.file;return im});let playing=true,index=0,elapsed=0,last=0;let times=data.frames.map(f=>f.duration);const scrub=document.getElementById('scrub');scrub.max=imgs.length-1;
const small=document.getElementById('actual'),large=document.getElementById('large');for(const c of [small,large]){c.width=data.cell[0];c.height=data.cell[1]}large.style.width=data.cell[0]*3+'px';large.style.height=data.cell[1]*3+'px';
function draw(){for(const c of [small,large]){let ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(imgs[index].complete)ctx.drawImage(imgs[index],0,0)}scrub.value=index;document.getElementById('info').textContent=`${index+1}/${imgs.length} · source ${data.frames[index].source_index}`}
document.getElementById('play').onclick=()=>{playing=!playing;document.getElementById('play').textContent=playing?'暂停':'播放'};scrub.oninput=()=>{playing=false;index=+scrub.value;elapsed=0;draw()};document.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){playing=false;index=(index+(e.key==='ArrowRight'?1:-1)+imgs.length)%imgs.length;elapsed=0;draw()}};
function tick(t){if(last&&playing){elapsed+=Math.min((t-last)/1000,.2)*document.getElementById('speed').value;while(elapsed>=times[index]){elapsed-=times[index];if(index===imgs.length-1&&!data.loop){playing=false;elapsed=0;break}index=(index+1)%imgs.length}}last=t;draw();requestAnimationFrame(tick)}requestAnimationFrame(tick);</script>''')
    # Portable Godot 4 SpriteFrames resource, usable by AnimatedSprite2D or AnimatedSprite3D.
    lines=['[gd_resource type="SpriteFrames" load_steps="'+str(len(frames)+1)+'" format=3]','']
    for i,f in enumerate(result):lines.append(f'[ext_resource type="Texture2D" path="{f["file"]}" id="{i+1}"]')
    lines+=['','[resource]','animations = [{','"frames": [']
    lines += [('{"duration": '+str(f['duration'])+', "texture": ExtResource("'+str(i+1)+'")}'+(',' if i<len(result)-1 else '')) for i,f in enumerate(result)]
    lines+= ['],','"loop": '+str(cfg.get('loop',True)).lower()+',','"name": &'+json.dumps(cfg.get('name','animation'))+',','"speed": 1.0','}]']
    (out/'animation.tres').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(output=str(out),frames=len(frames),duration=sum(durations),qc=manifest['qc'])))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('extract');p.add_argument('video');p.add_argument('--out',required=True)
    for name in ['prepare','build']:
        p=sub.add_parser(name);p.add_argument('input');p.add_argument('--config',required=True);p.add_argument('--out',required=True)
    a=parser.parse_args()
    try:
        if a.command=='extract':extract(a.video,a.out)
        elif a.command=='prepare':prepare(a.input,a.config,a.out)
        else:build(a.input,a.config,a.out)
    except (ValueError,RuntimeError,OSError) as e:
        parser.exit(1,f'Error: {e}\n')

if __name__=='__main__': main()
