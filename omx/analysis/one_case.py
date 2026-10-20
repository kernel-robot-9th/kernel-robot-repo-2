# One-episode check: find the grasp moment (first gripper close after the first open) and show the top-camera
# frames around it, with the left arm's joint values, so the definition can be confirmed by eye.
import glob, json, av, cv2, numpy as np, pandas as pd
D = '/home/omen/.cache/huggingface/lerobot/jaewoo112/bi_gauze_one_exposure'
E = 5
fps = json.load(open(D + '/meta/info.json'))['fps']
g = pd.concat(pd.read_parquet(f, columns=['episode_index', 'frame_index', 'action', 'observation.state'])
              for f in glob.glob(D + '/data/*/*.parquet'))
g = g[g.episode_index == E].sort_values('frame_index')
grip = np.stack(g['action'].values)[:, 5]; st = np.stack(g['observation.state'].values)
o = int(np.argmax(grip > 55)); c = o + int(np.argmax(grip[o:] < 52))
r = pd.concat(pd.read_parquet(f) for f in glob.glob(D + '/meta/episodes/*/*.parquet')).set_index('episode_index').loc[E]
K = 'videos/observation.images.top/'
i0 = int(round(r[K + 'from_timestamp'] * fps))
picks = {'start': 0, 'gripper opens': o, 'grasp (gripper closes)': c, '+1s after': min(c + 30, len(g) - 1)}
need = {i0 + v: k for k, v in picks.items()}
out = {}
with av.open(f"{D}/videos/observation.images.top/chunk-{int(r[K+'chunk_index']):03d}/file-{int(r[K+'file_index']):03d}.mp4") as cont:
    s = cont.streams.video[0]; s.thread_count = 2
    for idx, f in enumerate(cont.decode(s)):
        if idx in need: out[need[idx]] = f.to_ndarray(format='rgb24')
        if idx >= max(need): break
tiles = []
for k, v in picks.items():
    a = out[k].copy(); j = st[v]
    cv2.rectangle(a, (0, 0), (640, 56), (0, 0, 0), -1)
    cv2.putText(a, f'{k}  (frame {v}, {v/fps:.1f}s)', (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(a, f'L lift {j[1]:.0f} elbow {j[2]:.0f} wflex {j[3]:.0f} grip {j[5]:.0f}', (6, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
    tiles.append(a)
img = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
cv2.imwrite('/home/omen/main_project/grasp_one_case_ep5.jpg', cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
print('open', o, 'grasp', c, 'len', len(g))
