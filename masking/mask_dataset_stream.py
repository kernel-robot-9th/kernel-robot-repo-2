# Low-memory version of mask_dataset.py: streams frames (decode -> mask -> encode) instead of holding
# a whole video file in RAM (the old version hit ~12 GB and got OOM-killed on long files).
# Resumable: works in place on an existing DST copy and skips video files already listed in DONE_LOG.
# Usage: python mask_dataset_stream.py SRC DST CAM X1 Y1 X2 Y2
#   DST must already exist (a copy of SRC); masked files are recorded in DST/.masked_files.
import sys, glob, json, shutil, numpy as np, pandas as pd, av
from pathlib import Path
from lerobot.datasets.video_utils import _get_codec_options
from lerobot.datasets.compute_stats import sample_indices, auto_downsample_height_width, get_feature_stats, aggregate_stats, DEFAULT_QUANTILES

SRC, DST, CAM = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
KX1, KY1, KX2, KY2 = map(int, sys.argv[4:8])
KEY = f'observation.images.{CAM}'; K = f'videos/{KEY}/'
if not DST.exists():
    shutil.copytree(SRC, DST)
DONE_LOG = DST / '.masked_files'
done = set(DONE_LOG.read_text().split()) if DONE_LOG.exists() else set()
fps = json.load(open(DST/'meta/info.json'))['fps']
ep_files = sorted(glob.glob(str(DST/'meta/episodes/*/*.parquet')))
eps = pd.concat(pd.read_parquet(f) for f in ep_files).set_index('episode_index').sort_index()


def mask(a):
    m = np.zeros_like(a); m[KY1:KY2, KX1:KX2] = a[KY1:KY2, KX1:KX2]; return m


# 1) mask: stream every not-yet-done video file from SRC into DST
for vid in sorted((DST/'videos'/KEY).glob('chunk-*/file-*.mp4')):
    rel = str(vid.relative_to(DST))
    if rel in done:
        print('skip (already masked)', vid.name, flush=True); continue
    tmp = vid.with_suffix('.tmp.mp4'); n = 0
    opts = _get_codec_options('libsvtav1', 2, 30); opts['svtav1-params'] = 'lp=4'
    with av.open(str(SRC/rel)) as c, av.open(str(tmp), 'w') as o:
        c.streams.video[0].thread_count = 2
        s = o.add_stream('libsvtav1', fps, options=opts); s.pix_fmt = 'yuv420p'
        for f in c.decode(video=0):
            a = f.to_ndarray(format='rgb24')
            if n == 0: s.width, s.height = a.shape[1], a.shape[0]
            for p in s.encode(av.VideoFrame.from_ndarray(mask(a), format='rgb24')): o.mux(p)
            n += 1
        for p in s.encode(): o.mux(p)
    tmp.replace(vid)
    with open(DONE_LOG, 'a') as fh: fh.write(rel + '\n')
    print(vid.name, n, 'frames masked', flush=True)

# 2) stats: decode masked videos again, keep only the frames LeRobot's stats sampler would pick
ep_frames = {}
for vid in sorted((DST/'videos'/KEY).glob('chunk-*/file-*.mp4')):
    ci, fi = int(vid.parent.name[6:]), int(vid.stem[5:])
    mine = eps[(eps[K+'chunk_index'] == ci) & (eps[K+'file_index'] == fi)]
    want = {}  # file frame index -> episode
    for ep, r in mine.iterrows():
        i0 = int(round(r[K+'from_timestamp']*fps))
        for i in sample_indices(int(r['length'])): want[i0 + i] = ep
    with av.open(str(vid)) as c:
        c.streams.video[0].thread_count = 2  # default decoder threading can spike memory on long files
        for idx, f in enumerate(c.decode(video=0)):
            if idx in want:
                ep_frames.setdefault(want[idx], []).append(
                    np.ascontiguousarray(auto_downsample_height_width(f.to_ndarray(format='rgb24').transpose(2, 0, 1))))  # copy: a strided view would keep the full frame alive
    print('stats sampled', vid.name, flush=True)

new = {}
for ep, fr in ep_frames.items():
    st = get_feature_stats(np.stack(fr), axis=(0, 2, 3), keepdims=True, quantile_list=DEFAULT_QUANTILES)
    new[ep] = {k: (np.squeeze(v, axis=0)/255.0 if k != 'count' else v) for k, v in st.items()}
assert len(new) == len(eps), (len(new), len(eps))
for f in ep_files:
    df = pd.read_parquet(f)
    for col in [c for c in df.columns if c.startswith(f'stats/{KEY}/')]:
        k = col.split('/')[-1]
        df[col] = [new[e][k].tolist() for e in df['episode_index']]
    df.to_parquet(f)
agg = aggregate_stats([{KEY: new[e]} for e in sorted(new)])[KEY]
stats = json.load(open(DST/'meta/stats.json'))
stats[KEY] = {k: np.asarray(v).tolist() for k, v in agg.items()}
json.dump(stats, open(DST/'meta/stats.json', 'w'), indent=4)
print('mean', stats[KEY]['mean'], 'done', flush=True)
