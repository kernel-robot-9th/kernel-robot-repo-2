# Preview the top-camera mask (keep x0-400, y200-480) on bi_gauze_v2 frames: start + grasp moments.
import glob, json, av, cv2, numpy as np, pandas as pd
D = '/home/omen/.cache/huggingface/lerobot/jaewoo112/bi_gauze_v2'
X1, Y1, X2, Y2 = 0, 200, 400, 480
fps = json.load(open(D + '/meta/info.json'))['fps']
eps = pd.concat(pd.read_parquet(f) for f in glob.glob(D + '/meta/episodes/*/*.parquet')).set_index('episode_index')
pts = pd.read_csv('grasp_v2/grasp_points.csv').set_index('episode')
K = 'videos/observation.images.top/'
def frame(e, i):
    r = eps.loc[e]; idx = int(round(r[K + 'from_timestamp'] * fps)) + i
    with av.open(f"{D}/videos/observation.images.top/chunk-{int(r[K+'chunk_index']):03d}/file-{int(r[K+'file_index']):03d}.mp4") as c:
        s = c.streams.video[0]; s.thread_count = 2
        for n, f in enumerate(c.decode(s)):
            if n == idx: return f.to_ndarray(format='rgb24')
def mask(a):
    m = np.zeros_like(a); m[Y1:Y2, X1:X2] = a[Y1:Y2, X1:X2]; return m
def lab(a, t):
    a = a.copy(); cv2.rectangle(a, (0, 0), (640, 30), (0, 0, 0), -1)
    cv2.putText(a, t, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2); return a
shots = [(5, 0, 'ep5 start'), (5, int(pts.loc[5, 'grasp_frame']), 'ep5 grasp'), (31, int(pts.loc[31, 'grasp_frame']), 'ep31 grasp')]
rows = []
for e, i, name in shots:
    a = frame(e, i); box = a.copy(); cv2.rectangle(box, (X1, Y1), (X2 - 1, Y2 - 1), (255, 255, 0), 3)
    rows.append(np.hstack([lab(box, f'{name} | original (keep area)'), lab(mask(a), f'{name} | masked')]))
cv2.imwrite('/home/omen/main_project/v2_mask_preview.jpg', cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
print('ok')
