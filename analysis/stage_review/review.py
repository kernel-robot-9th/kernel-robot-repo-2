"""Independent gripper-event proposals; source labels/data are never modified.

Frames are zero-based, stage intervals are [start, end). Events are proxies,
not visual grasp-success labels. Video access uses per-camera metadata timestamps.
"""
from pathlib import Path
import json
import av
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path('/home/omen/.cache/huggingface/lerobot/local/bi_gauze_v5_stages')
OUT = Path(__file__).resolve().parent
FPS = 30
data = pd.concat(pd.read_parquet(p) for p in sorted(ROOT.glob('data/**/*.parquet')))
meta = pd.concat(pd.read_parquet(p) for p in sorted(ROOT.glob('meta/episodes/**/*.parquet'))).set_index('episode_index')

def first_run(mask, start=0, count=3):
    for i in range(start, len(mask)-count+1):
        if np.all(mask[i:i+count]):
            return i
    raise ValueError('No sustained event found')

rows = []
groups = {}
for ep, g in data.groupby('episode_index'):
    g = g.sort_values('frame_index').reset_index(drop=True)
    groups[int(ep)] = g
    a = np.stack(g.action)[:,5]
    initial = float(np.median(a[:15]))
    closed = float(np.quantile(a, .05))
    # Ignore sub-unit jitter; require three consecutive samples.
    opened = first_run(a > initial+0.8)
    open_confirmed = first_run(a > initial+3, opened)
    close = first_run(a < closed+0.8, open_confirmed)
    release = first_run(a > closed+1, close+15)
    old_open = int(g.loc[g.task_index == 1, 'frame_index'].min())
    old_close = int(g.loc[g.task_index == 2, 'frame_index'].min())
    rows.append(dict(episode=int(ep), frames=len(g), search_start=0,
                     grasp_start=opened, carry_start=close, release_onset=release,
                     end_exclusive=len(g), old_grasp_start=old_open,
                     old_carry_start=old_close,
                     grasp_shift_frames=opened-old_open, carry_shift_frames=close-old_close,
                     search_seconds=opened/FPS, grasp_seconds=(close-opened)/FPS,
                     carry_seconds=(len(g)-close)/FPS,
                     visual_review='sample_only' if ep in [0,14,31,48] else 'not_reviewed'))
bounds = pd.DataFrame(rows)
bounds.to_csv(OUT/'boundaries.csv',index=False)

FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
SMALL = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
cache = {}
def frame(ep, camera, idx):
    key=(ep,camera,idx)
    if key in cache: return cache[key]
    k=f'videos/observation.images.{camera}/'
    r=meta.loc[ep]
    p=ROOT/f'videos/observation.images.{camera}'/f"chunk-{int(r[k+'chunk_index']):03d}"/f"file-{int(r[k+'file_index']):03d}.mp4"
    t=float(r[k+'from_timestamp'])+float(groups[ep].iloc[idx].timestamp)
    with av.open(str(p)) as c:
        s=c.streams.video[0]; s.thread_count=2
        c.seek(max(0,int((t-0.1)/s.time_base)), stream=s, backward=True)
        best=None; distance=1e9
        for f in c.decode(s):
            ft=float(f.pts*s.time_base)
            if abs(ft-t)<distance: best=f; distance=abs(ft-t)
            if ft>=t: break
        assert best is not None and distance<.05,(ep,camera,idx,t,distance)
        im=best.to_image()
    cache[key]=im
    return im

def tile(ep, idx, camera, label, width=320):
    im=frame(ep,camera,idx).resize((width,width*3//4))
    canvas=Image.new('RGB',(width,width*3//4+58),'#17212b')
    canvas.paste(im,(0,58)); d=ImageDraw.Draw(canvas)
    d.text((7,4),label,fill='#ffdc70',font=FONT)
    d.text((7,25),f'ep{ep} f{idx} / {idx/FPS:.2f}s | {camera}',fill='white',font=SMALL)
    return canvas

samples=[0,14,31,48]
sheet=Image.new('RGB',(1920,298*4))
for row,ep in enumerate(samples):
    r=bounds[bounds.episode==ep].iloc[0]
    for col,(name,k) in enumerate([('Search -> grasp','grasp_start'),('Close command settled','carry_start'),('Release begins','release_onset')]):
        for j,cam in enumerate(['top','wrist_left']):
            sheet.paste(tile(ep,int(r[k]),cam,name),((col*2+j)*320,row*298))
sheet.save(OUT/'boundary_samples.jpg',quality=93)

# Inspect temporal evidence rather than treating a single closed-gripper image as success.
for ep in samples:
    r=bounds[bounds.episode==ep].iloc[0]
    sheet=Image.new('RGB',(1600,298*4))
    for event,k in enumerate(['grasp_start','carry_start']):
        center=int(r[k])
        for col,offset in enumerate([-15,-5,0,5,15]):
            idx=max(0,min(len(groups[ep])-1,center+offset))
            for j,cam in enumerate(['top','wrist_left']):
                label=f'{"Open onset" if event==0 else "Close settled"} {offset/FPS:+.2f}s'
                sheet.paste(tile(ep,idx,cam,label),(col*320,(event*2+j)*298))
    sheet.save(OUT/f'episode_{ep:02d}_before_after.jpg',quality=93)

summary={'episodes':len(bounds),'frames':len(data),'mean_seconds':len(data)/len(bounds)/FPS,
         'mean_stage_seconds':bounds[['search_seconds','grasp_seconds','carry_seconds']].mean().to_dict(),
         'sample_boundaries':bounds[bounds.episode.isin(samples)].to_dict('records')}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2),flush=True)
