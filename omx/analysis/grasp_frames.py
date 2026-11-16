# Find the grasp moment (first gripper close after the first open) in each episode and save top-camera frames.
import glob, json, av, cv2, numpy as np, pandas as pd
D = '/home/omen/.cache/huggingface/lerobot/jaewoo112/bi_gauze_one_exposure'
fps = json.load(open(D + '/meta/info.json'))['fps']
tr = pd.concat(pd.read_parquet(f, columns=['episode_index', 'frame_index', 'action', 'observation.state'])
               for f in glob.glob(D + '/data/*/*.parquet')).sort_values(['episode_index', 'frame_index'])
eps = pd.concat(pd.read_parquet(f) for f in glob.glob(D + '/meta/episodes/*/*.parquet')).set_index('episode_index')
K = 'videos/observation.images.top/'
rows = []
for e, g in tr.groupby('episode_index'):
    grip = np.stack(g['action'].values)[:, 5]
    o = np.argmax(grip > 55)
    if grip[o] <= 55: continue
    c = o + np.argmax(grip[o:] < 52)
    if grip[c] >= 52: continue
    rows.append((e, int(c), int(o)))
# decode: group needed frames per video file
want = {}
for e, c, o in rows:
    r = eps.loc[e]; ci, fi = int(r[K + 'chunk_index']), int(r[K + 'file_index'])
    i0 = int(round(r[K + 'from_timestamp'] * fps))
    for tag, idx in (('grasp', i0 + c), ('start', i0)):
        want.setdefault((ci, fi), {})[idx] = (e, tag)
frames = {}
for (ci, fi), m in want.items():
    with av.open(f'{D}/videos/observation.images.top/chunk-{ci:03d}/file-{fi:03d}.mp4') as cont:
        s = cont.streams.video[0]; s.thread_count = 2
        last = max(m)
        for idx, f in enumerate(cont.decode(s)):
            if idx in m: frames[m[idx]] = f.to_ndarray(format='rgb24')
            if idx >= last: break
np.savez_compressed('grasp_frames.npz', **{f'{e}_{t}': v for (e, t), v in frames.items()})
pd.DataFrame(rows, columns=['episode', 'grasp_frame', 'open_frame']).to_csv('grasp_moments.csv', index=False)
print(len(rows), 'episodes with a grasp,', len(frames), 'frames saved')
