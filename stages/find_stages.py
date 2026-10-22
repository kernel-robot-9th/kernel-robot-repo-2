"""Find stage boundaries in a recorded dataset from the left gripper command (read-only).

search : start -> the gripper starts opening (operator saw the gauze in the wrist camera)
grasp  : opening -> the gripper closes on the gauze
carry  : closed -> end (move to the box, release, hold)
Usage: python stages/find_stages.py [repo_id] [--sheet out.jpg]
Writes stages/<name>_bounds.csv (episode, open, close, release, length, ok).
"""
import argparse, glob
from pathlib import Path
import numpy as np, pandas as pd

def bounds(grip):
    """Indices where the left gripper command crosses halfway between its closed and fully-open value."""
    closed = np.median(grip[:15]); mid = (closed + grip.max()) / 2
    up = np.flatnonzero(grip > mid)
    if len(up) == 0: return None
    o = up[0]
    down = np.flatnonzero(grip[o:] < mid)
    if len(down) == 0: return o, None, None
    c = o + down[0]
    rel = np.flatnonzero(grip[c:] > mid)
    return o, c, (c + rel[0] if len(rel) else None)

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('repo', nargs='?', default='jaewoo112/bi_gauze_v5'); p.add_argument('--sheet')
    a = p.parse_args()
    root = Path.home() / '.cache/huggingface/lerobot' / a.repo
    d = pd.concat(pd.read_parquet(f, columns=['episode_index', 'frame_index', 'action']) for f in glob.glob(f'{root}/data/*/*.parquet')).sort_values(['episode_index', 'frame_index'])
    rows = []
    for e, x in d.groupby('episode_index'):
        g = np.stack(x['action'].values)[:, 5]
        b = bounds(g) or (None, None, None)
        o, c, r = b
        ok = o is not None and c is not None and o >= 15 and c - o >= 15
        rows.append(dict(episode=e, open=o, close=c, release=r, length=len(x), ok=ok))
    df = pd.DataFrame(rows)
    out = Path(__file__).parent / f'{root.name}_bounds.csv'; df.to_csv(out, index=False)
    print(df.to_string()); print('saved', out, '| ok', int(df.ok.sum()), '/', len(df))
