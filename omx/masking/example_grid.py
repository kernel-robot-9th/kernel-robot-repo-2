# Example frames for training datasets 1, 2, 5 (top + both wrist cameras), saved as one labelled grid.
# Dataset 2 = dataset 1 with the top camera masked to x0-400, y200-480 (same as mask_dataset.py).
import glob, sys
import av, cv2, numpy as np, pandas as pd

H = "/home/omen/.cache/huggingface/lerobot/"
D1 = H + "jaewoo112/bi_gauze_one_exposure"
OLD_MASKED = H + "local/bi_gauze_masked"  # auto exposure, top masked
CAMS = ["top", "wrist_left", "wrist_right"]
ROI = (0, 200, 400, 480)


def frame(root, cam, ep, at=0.5):
    """Decode the frame at fraction `at` of episode `ep` for camera `cam`."""
    key = f"observation.images.{cam}"
    eps = pd.concat(pd.read_parquet(f) for f in glob.glob(root + "/meta/episodes/*/*.parquet"))
    r = eps[eps.episode_index == ep].iloc[0]
    ci, fi = int(r[f"videos/{key}/chunk_index"]), int(r[f"videos/{key}/file_index"])
    t = r[f"videos/{key}/from_timestamp"] + at * (r[f"videos/{key}/to_timestamp"] - r[f"videos/{key}/from_timestamp"])
    path = f"{root}/videos/{key}/chunk-{ci:03d}/file-{fi:03d}.mp4"
    with av.open(path) as c:
        s = c.streams.video[0]
        c.seek(int(max(t - 1, 0) / s.time_base), stream=s)
        for f in c.decode(s):
            if f.time >= t:
                return f.to_ndarray(format="rgb24")
    raise RuntimeError(path)


def mask(a):
    x1, y1, x2, y2 = ROI
    m = np.zeros_like(a)
    m[y1:y2, x1:x2] = a[y1:y2, x1:x2]
    return m


def label(img, text):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(out, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return out


ep1 = int(sys.argv[1]) if len(sys.argv) > 1 else 10
ep_old = int(sys.argv[2]) if len(sys.argv) > 2 else 10
D2 = H + "local/bi_gauze_one_exposure_masked"
D5 = H + "local/bi_gauze_mix_masked"  # episodes 0-49 = bi_gauze_masked, 50-108 = dataset 2
rows = [
    ("1: exposure 90", [frame(D1, c, ep1) for c in CAMS]),
    ("2: exposure 90 + mask", [frame(D2, c, ep1) for c in CAMS]),
    (f"5: ep {ep_old} (auto exposure + mask)", [frame(D5, c, ep_old) for c in CAMS]),
    (f"5: ep {50 + ep1} (exposure 90 + mask)", [frame(D5, c, 50 + ep1) for c in CAMS]),
]
grid = []
for name, imgs in rows:
    grid.append(np.hstack([label(im, f"{name} | {c}" if c == "top" else c) for im, c in zip(imgs, CAMS)]))
out = np.vstack(grid)
cv2.imwrite(sys.argv[3] if len(sys.argv) > 3 else "datasets_1_2_5_examples.jpg",
            cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
print(out.shape)
