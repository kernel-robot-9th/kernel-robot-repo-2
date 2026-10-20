# Copy a LeRobot v3 dataset and keep only a rectangle of one camera (rest black); recompute that camera's stats.
import sys, glob, json, shutil, numpy as np, pandas as pd, av
from pathlib import Path
from lerobot.datasets.video_utils import _get_codec_options
from lerobot.datasets.compute_stats import sample_indices, auto_downsample_height_width, get_feature_stats, aggregate_stats, DEFAULT_QUANTILES
SRC, DST, CAM = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
KX1, KY1, KX2, KY2 = map(int, sys.argv[4:8])
KEY = f'observation.images.{CAM}'; K = f'videos/{KEY}/'
assert not DST.exists(), DST
shutil.copytree(SRC, DST)
info = json.load(open(DST/'meta/info.json')); fps = info['fps']
ep_files = sorted(glob.glob(str(DST/'meta/episodes/*/*.parquet')))
eps = pd.concat(pd.read_parquet(f) for f in ep_files).set_index('episode_index').sort_index()
ep_frames = {}  # episode -> list of masked frames (downsampled, CHW uint8) for stats
for vid in sorted((DST/'videos'/KEY).glob('chunk-*/file-*.mp4')):
    ci, fi = int(vid.parent.name[6:]), int(vid.stem[5:])
    mine = eps[(eps[K+'chunk_index']==ci) & (eps[K+'file_index']==fi)]
    frames = []
    with av.open(str(SRC/vid.relative_to(DST))) as c:
        for f in c.decode(video=0):
            a = f.to_ndarray(format='rgb24'); m = np.zeros_like(a)
            m[KY1:KY2, KX1:KX2] = a[KY1:KY2, KX1:KX2]; frames.append(m)
    expect = int(round((mine[K+'to_timestamp'].max()) * fps))
    assert len(frames) >= expect, (vid, len(frames), expect)
    opts = _get_codec_options('libsvtav1', 2, 30); opts['svtav1-params'] = 'lp=4'
    tmp = vid.with_suffix('.tmp.mp4')
    with av.open(str(tmp), 'w') as o:
        s = o.add_stream('libsvtav1', fps, options=opts); s.pix_fmt='yuv420p'; s.width=frames[0].shape[1]; s.height=frames[0].shape[0]
        for a in frames:
            for p in s.encode(av.VideoFrame.from_ndarray(a, format='rgb24')): o.mux(p)
        for p in s.encode(): o.mux(p)
    tmp.replace(vid)
    for ep, r in mine.iterrows():
        i0 = int(round(r[K+'from_timestamp']*fps)); n = int(r['length'])
        ep_frames[ep] = [auto_downsample_height_width(frames[i0+i].transpose(2,0,1)) for i in sample_indices(n)]
    print(vid.name, len(frames), 'frames,', len(mine), 'episodes', flush=True)
# per-episode stats
new = {}
for ep, fr in ep_frames.items():
    st = get_feature_stats(np.stack(fr), axis=(0,2,3), keepdims=True, quantile_list=DEFAULT_QUANTILES)
    new[ep] = {k: (v/255.0 if k!='count' else v) for k,v in st.items()}
assert len(new) == len(eps), (len(new), len(eps))
for f in ep_files:
    df = pd.read_parquet(f)
    for col in [c for c in df.columns if c.startswith(f'stats/{KEY}/')]:
        k = col.split('/')[-1]
        df[col] = [new[e][k].tolist() for e in df['episode_index']]
    df.to_parquet(f)
agg = aggregate_stats([{KEY: new[e]} for e in sorted(new)])[KEY]
stats = json.load(open(DST/'meta/stats.json'))
stats[KEY] = {k: np.asarray(v).tolist() for k,v in agg.items()}
json.dump(stats, open(DST/'meta/stats.json','w'), indent=4)
print('mean', stats[KEY]['mean'], 'done')
