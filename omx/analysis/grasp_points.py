"""Grasp positions in the top-camera image for a LeRobot dataset (one point per episode).

Grasp moment = first frame where the gripper is commanded to close after it first opens (leader trigger).
Grasp point  = the left-arm pixels that are dark at the grasp moment but were not dark at the episode start;
               the mean of the 30 of those pixels farthest from the left arm base (the yellow circle).
Saves (in OUT): grasp_points.csv, frames/ep###_grasp.jpg (annotated), and the raw start/grasp frames
so the heatmap can be redrawn without recomputing (see heatmap.py).
Usage: python grasp_points.py <dataset_root> <out_dir> [base_x base_y]
"""
import glob, json, os, sys
import av, cv2, numpy as np, pandas as pd

ROOT, OUT = sys.argv[1], sys.argv[2]
BASE = np.array([int(sys.argv[3]), int(sys.argv[4])]) if len(sys.argv) > 4 else np.array([100, 470])
os.makedirs(OUT + '/frames', exist_ok=True)
fps = json.load(open(ROOT + '/meta/info.json'))['fps']
data = pd.concat(pd.read_parquet(f, columns=['episode_index', 'frame_index', 'action', 'observation.state'])
                 for f in glob.glob(ROOT + '/data/*/*.parquet')).sort_values(['episode_index', 'frame_index'])
eps = pd.concat(pd.read_parquet(f) for f in glob.glob(ROOT + '/meta/episodes/*/*.parquet')).set_index('episode_index')
K = 'videos/observation.images.top/'

moments = {}
for e, g in data.groupby('episode_index'):
    grip = np.stack(g['action'].values)[:, 5]
    o = int(np.argmax(grip > 55))
    if grip[o] <= 55: continue
    c = o + int(np.argmax(grip[o:] < 52))
    if grip[c] >= 52: continue
    moments[e] = (c, np.stack(g['observation.state'].values)[c])

want = {}  # (chunk, file) -> {file frame index: (episode, 'start'|'grasp')}
for e, (c, _) in moments.items():
    r = eps.loc[e]; i0 = int(round(r[K + 'from_timestamp'] * fps))
    m = want.setdefault((int(r[K + 'chunk_index']), int(r[K + 'file_index'])), {})
    m[i0] = (e, 'start'); m[i0 + c] = (e, 'grasp')

frames = {}
for (ci, fi), m in sorted(want.items()):
    with av.open(f'{ROOT}/videos/observation.images.top/chunk-{ci:03d}/file-{fi:03d}.mp4') as cont:
        s = cont.streams.video[0]; s.thread_count = 2
        last = max(m)
        for idx, f in enumerate(cont.decode(s)):
            if idx in m: frames[m[idx]] = f.to_ndarray(format='rgb24')
            if idx >= last: break
    print('decoded', f'file-{fi:03d}', flush=True)

def dark(a): return a.max(axis=2) < 70
rows = []
for e, (c, st) in sorted(moments.items()):
    start, grasp = frames[(e, 'start')], frames[(e, 'grasp')]
    new = (dark(grasp) & ~dark(start)).astype(np.uint8)
    new = cv2.morphologyEx(new, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(new)
    if n < 2: continue
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.where(lab == k)
    d = np.hypot(xs - BASE[0], ys - BASE[1]); i = np.argsort(d)[-30:]
    tip = (int(xs[i].mean()), int(ys[i].mean()))
    rows.append(dict(episode=e, grasp_frame=c, time_s=round(c / fps, 2), x=tip[0], y=tip[1],
                     arm_area=int(stats[k, cv2.CC_STAT_AREA]),
                     **{f'left_{n}': round(float(v), 1) for n, v in zip(
                         ['pan', 'lift', 'elbow', 'wflex', 'wroll', 'grip'], st[:6])}))
    vis = cv2.cvtColor(grasp, cv2.COLOR_RGB2BGR)
    ov = vis.copy(); ov[lab == k] = (0, 0, 255); vis = cv2.addWeighted(vis, 0.6, ov, 0.4, 0)
    cv2.circle(vis, tip, 9, (0, 255, 255), 3); cv2.circle(vis, tuple(int(v) for v in BASE), 7, (255, 0, 255), 3)
    cv2.putText(vis, f'ep {e}  {c / fps:.1f}s  tip {tip}', (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.imwrite(f'{OUT}/frames/ep{e:03d}_grasp.jpg', vis, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if e == min(moments):
        cv2.imwrite(f'{OUT}/background.jpg', cv2.cvtColor(start, cv2.COLOR_RGB2BGR))
pd.DataFrame(rows).to_csv(OUT + '/grasp_points.csv', index=False)
print('episodes', len(data.episode_index.unique()), 'with grasp', len(moments), 'points', len(rows), flush=True)
