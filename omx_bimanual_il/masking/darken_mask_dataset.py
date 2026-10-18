# Copy a LeRobot v3 dataset; on one camera apply a per-channel LUT (auto -> exposure 90 look), then keep only a rectangle (rest black).
# Streams frames (decode -> process -> encode) so memory stays low. Recompute stats afterwards with mask_stats.py.
import sys, shutil, json, numpy as np, av
from darken import darken
from pathlib import Path
from lerobot.datasets.video_utils import _get_codec_options
SRC, DST, CAM, LUT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], np.load(sys.argv[4])
KX1, KY1, KX2, KY2 = map(int, sys.argv[5:9])
KEY = f'observation.images.{CAM}'
assert not DST.exists(), DST
shutil.copytree(SRC, DST)
fps = json.load(open(DST/'meta/info.json'))['fps']
for vid in sorted((DST/'videos'/KEY).glob('chunk-*/file-*.mp4')):
    tmp = vid.with_suffix('.tmp.mp4'); n = 0
    opts = _get_codec_options('libsvtav1', 2, 30); opts['svtav1-params'] = 'lp=4'
    with av.open(str(SRC/vid.relative_to(DST))) as c, av.open(str(tmp), 'w') as o:
        s = o.add_stream('libsvtav1', fps, options=opts); s.pix_fmt = 'yuv420p'; s.width, s.height = 640, 480
        for f in c.decode(video=0):
            a = f.to_ndarray(format='rgb24'); m = np.zeros_like(a)
            roi = a[KY1:KY2, KX1:KX2]
            m[KY1:KY2, KX1:KX2] = darken(roi, LUT)
            for p in s.encode(av.VideoFrame.from_ndarray(m, format='rgb24')): o.mux(p)
            n += 1
        for p in s.encode(): o.mux(p)
    tmp.replace(vid); print(vid.name, n, 'frames', flush=True)
