# Compare top-camera brightness: training data (exposure 90) vs what the model saw in each eval run.
import glob, os, av, numpy as np, cv2
H = '/home/omen/.cache/huggingface/lerobot/'
def stats(path, n=40):
    vals = []; fr = None
    with av.open(path) as c:
        s = c.streams.video[0]; s.thread_count = 2
        for i, f in enumerate(c.decode(s)):
            if i % 10 == 0:
                a = f.to_ndarray(format='rgb24'); vals.append((a.mean(), (a.max(2) >= 250).mean() * 100))
                if fr is None and i >= 30: fr = a
            if len(vals) >= n: break
    v = np.array(vals); return v[:, 0].mean(), v[:, 1].mean(), fr
tr = sorted(glob.glob(H + 'jaewoo112/bi_gauze_one_exposure/videos/observation.images.top/chunk-000/*.mp4'))[0]
m, c, ftr = stats(tr); print(f'TRAIN bi_gauze_one_exposure        mean {m:6.1f}  clipped {c:4.1f}%')
rows = [('train exp90', ftr)]
for d in sorted(glob.glob(H + 'local/eval_bi_gauze_one_exposure*'), key=os.path.getmtime):
    v = glob.glob(d + '/videos/observation.images.camera1/chunk-000/*.mp4')
    if not v: continue
    m, c, f = stats(v[0]); name = d.split('/')[-1]
    print(f'EVAL  {name:38s} mean {m:6.1f}  clipped {c:4.1f}%')
    rows.append((name[-6:], f))
tiles = []
for name, f in rows[-4:] if len(rows) > 4 else rows:
    a = f.copy(); cv2.rectangle(a, (0, 0), (640, 30), (0, 0, 0), -1)
    cv2.putText(a, name, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2); tiles.append(a)
if len(tiles) % 2: tiles.append(np.zeros_like(tiles[0]))
g = np.vstack([np.hstack(tiles[i:i+2]) for i in range(0, len(tiles), 2)])
cv2.imwrite('/home/omen/main_project/exposure_train_vs_eval.jpg', cv2.cvtColor(g, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
