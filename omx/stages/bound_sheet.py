"""Contact sheet of stage boundaries: top + left-wrist frames at open / close / release for a few episodes."""
import sys, glob, av, cv2, numpy as np, pandas as pd
from pathlib import Path
repo = sys.argv[1] if len(sys.argv) > 1 else 'jaewoo112/bi_gauze_v5'; eps = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else '0,14,31,48').split(',')]
root = Path.home() / '.cache/huggingface/lerobot' / repo
b = pd.read_csv(Path(__file__).parent / f'{root.name}_bounds.csv').set_index('episode')
m = pd.concat(pd.read_parquet(f) for f in glob.glob(f'{root}/meta/episodes/*/*.parquet')).set_index('episode_index')
def frame(ep, cam, i):
    k = f'videos/observation.images.{cam}/'
    f = root / f"videos/observation.images.{cam}/chunk-{int(m.loc[ep, k+'chunk_index']):03d}/file-{int(m.loc[ep, k+'file_index']):03d}.mp4"
    ts = m.loc[ep, k + 'from_timestamp'] + i / 30
    with av.open(str(f)) as c:
        s = c.streams.video[0]; c.seek(int(max(ts - 1, 0) / s.time_base), stream=s)
        for fr in c.decode(s):
            if fr.time >= ts - 1e-3: return fr.to_ndarray(format='rgb24')
L = lambda x, t: cv2.putText(np.ascontiguousarray(cv2.resize(x, (320, 240))), t, (5, 20), 0, 0.55, (255, 255, 0), 2)
rows = []
for ep in eps:
    r = b.loc[ep]; pts = [('search->grasp', int(r.open)), ('grasp->carry', int(r.close))] + ([('release', int(r.release))] if not np.isnan(r.release) else [])
    rows.append(np.hstack([L(frame(ep, cam, i), f'ep{ep} {n} {cam[:5]}') for n, i in pts for cam in ('top', 'wrist_left')] + [np.zeros((240, 320 * (6 - 2 * len(pts)), 3), np.uint8)] * (len(pts) < 3)))
out = Path(__file__).parent / f'{root.name}_bounds.jpg'
cv2.imwrite(str(out), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80]); print('saved', out)
