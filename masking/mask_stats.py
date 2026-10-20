# Recompute one camera's per-episode and global stats from the (already masked) videos.
import sys, glob, json, numpy as np, pandas as pd, av
from pathlib import Path
from lerobot.datasets.compute_stats import sample_indices, auto_downsample_height_width, get_feature_stats, aggregate_stats, DEFAULT_QUANTILES
DST, CAM = Path(sys.argv[1]), sys.argv[2]
KEY = f'observation.images.{CAM}'; K = f'videos/{KEY}/'
fps = json.load(open(DST/'meta/info.json'))['fps']
ep_files = sorted(glob.glob(str(DST/'meta/episodes/*/*.parquet')))
eps = pd.concat(pd.read_parquet(f) for f in ep_files).set_index('episode_index').sort_index()
new = {}
for vid in sorted((DST/'videos'/KEY).glob('chunk-*/file-*.mp4')):
    ci, fi = int(vid.parent.name[6:]), int(vid.stem[5:])
    mine = eps[(eps[K+'chunk_index']==ci) & (eps[K+'file_index']==fi)]
    want = {}  # global frame index in file -> episode
    for ep, r in mine.iterrows():
        i0 = int(round(r[K+'from_timestamp']*fps))
        for i in sample_indices(int(r['length'])): want[i0+i] = ep
    got = {ep: [] for ep in mine.index}; n = 0
    with av.open(str(vid)) as c:
        for n, f in enumerate(c.decode(video=0)):
            if n in want: got[want[n]].append(auto_downsample_height_width(f.to_ndarray(format='rgb24').transpose(2,0,1)))
    frames = range(n+1)
    for ep, fr in got.items():
        st = get_feature_stats(np.stack(fr), axis=(0,2,3), keepdims=True, quantile_list=DEFAULT_QUANTILES)
        new[ep] = {k: (v if k=='count' else np.squeeze(v/255.0, axis=0)) for k,v in st.items()}
    print(vid.name, len(frames), 'frames', flush=True)
assert len(new) == len(eps)
for f in ep_files:
    df = pd.read_parquet(f)
    for col in [c for c in df.columns if c.startswith(f'stats/{KEY}/')]:
        k = col.split('/')[-1]; df[col] = [new[e][k].tolist() for e in df['episode_index']]
    df.to_parquet(f)
agg = aggregate_stats([{KEY: new[e]} for e in sorted(new)])[KEY]
stats = json.load(open(DST/'meta/stats.json'))
stats[KEY] = {k: np.asarray(v).tolist() for k,v in agg.items()}
json.dump(stats, open(DST/'meta/stats.json','w'), indent=4)
print('mean', stats[KEY]['mean'], 'done')
