"""Copy a dataset, cut each episode shortly after the gripper releases, and give every frame a stage
sentence instead of the single task (original untouched).

Stages come from stages/<name>_bounds.csv (find_stages.py), all from the left gripper command:
  [0, open)          -> "search for the {color} gauze"   (ends when the gripper starts opening)
  [open, close)      -> "grasp the {color} gauze"        (ends when the gripper closes on the gauze)
  [close, release)   -> "put the gauze in the box"       (ends when the gripper opens over the box)
Frames after release + KEEP_AFTER are dropped (the idle hold at the end of each recording).
Usage: python stages/relabel_stages.py jaewoo112/bi_gauze_v5 local/bi_gauze_v5_stages green
"""
import json, shutil, sys
from pathlib import Path
import numpy as np, pandas as pd

KEEP_AFTER = 15  # frames kept after the release (0.5 s), so the model sees the gripper open
src_id, dst_id, color = sys.argv[1], sys.argv[2], sys.argv[3]
H = Path.home() / '.cache/huggingface/lerobot'
src, dst = H / src_id, H / dst_id
assert not dst.exists(), f'{dst} already exists'
TASKS = [f'search for the {color} gauze', f'grasp the {color} gauze', 'put the gauze in the box']
b = pd.read_csv(Path(__file__).parent / f'{src.name}_bounds.csv').set_index('episode')
assert b.ok.all(), 'some episodes have no clean boundaries'
b['keep'] = [int(min(r.length, r.release + 1 + KEEP_AFTER)) if not np.isnan(r.release) else int(r.length) for r in b.itertuples()]

shutil.copytree(src, dst, ignore=shutil.ignore_patterns('images'))
info = json.loads((dst / 'meta/info.json').read_text()); fps = info['fps']

# 1) data: drop the tail, set the stage per frame, renumber the global index
files = sorted((dst / 'data').glob('*/*.parquet'))
parts = []
for f in files:
    d = pd.read_parquet(f); d['_file'] = str(f); parts.append(d)
d = pd.concat(parts).sort_values('index')
d = d[d.frame_index < d.episode_index.map(b.keep)].copy()
o, c = d.episode_index.map(b.open), d.episode_index.map(b.close)
d['task_index'] = np.where(d.frame_index < o, 0, np.where(d.frame_index < c, 1, 2)).astype(parts[0].task_index.dtype)
d['index'] = np.arange(len(d), dtype=parts[0]['index'].dtype)
for f in files:
    d[d._file == str(f)].drop(columns='_file').to_parquet(f, index=False)

# 2) episode metadata: new length / index range / video end time / tasks
start = d.groupby('episode_index')['index'].min(); n = d.groupby('episode_index').size()
for f in sorted((dst / 'meta/episodes').glob('*/*.parquet')):
    e = pd.read_parquet(f)
    e['tasks'] = [np.array(TASKS, dtype=object)] * len(e)
    e['length'] = e.episode_index.map(n).astype(e.length.dtype)
    e['dataset_from_index'] = e.episode_index.map(start).astype(e.dataset_from_index.dtype)
    e['dataset_to_index'] = (e.dataset_from_index + e.length).astype(e.dataset_to_index.dtype)
    for col in [c for c in e.columns if c.startswith('videos/') and c.endswith('/from_timestamp')]:
        e[col.replace('from_', 'to_')] = e[col] + e.length / fps
    e.to_parquet(f, index=False)
pd.DataFrame({'task_index': range(3)}, index=pd.Index(TASKS)).to_parquet(dst / 'meta/tasks.parquet')
info['total_tasks'] = 3; info['total_frames'] = int(len(d))
(dst / 'meta/info.json').write_text(json.dumps(info, indent=4))

# 3) dataset stats for the numeric columns that changed (image stats kept from the original)
s = json.loads((dst / 'meta/stats.json').read_text())
for k in ['action', 'observation.state', 'timestamp', 'frame_index', 'index', 'task_index']:
    v = np.stack(d[k].values).astype(np.float64).reshape(len(d), -1)
    s[k] = dict(min=v.min(0).tolist(), max=v.max(0).tolist(), mean=v.mean(0).tolist(), std=v.std(0).tolist(), count=[len(v)],
                **{f'q{q:02d}': np.quantile(v, q / 100, axis=0).tolist() for q in (1, 10, 50, 90, 99)})
(dst / 'meta/stats.json').write_text(json.dumps(s, indent=4))
print('wrote', dst, '| frames', len(d), 'of', int(b.length.sum()), '| per stage', np.bincount(d.task_index).tolist())
