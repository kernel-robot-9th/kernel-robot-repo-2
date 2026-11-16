import sys, glob, subprocess
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw
root, cam, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
crop = tuple(int(v) for v in sys.argv[4].split(",")) if len(sys.argv) > 4 else None
out.mkdir(parents=True, exist_ok=True)
eps = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(root / "meta/episodes/*/*.parquet"))))
k = f"videos/observation.images.{cam}"
tiles = []
for _, r in eps.iterrows():
    vid = root / f"videos/observation.images.{cam}/chunk-{int(r[k+'/chunk_index']):03d}/file-{int(r[k+'/file_index']):03d}.mp4"
    pair = []
    for tag, t in (("s", r[k+"/from_timestamp"] + 0.05), ("e", r[k+"/to_timestamp"] - 0.15)):
        png = out / f"ep{int(r.episode_index):03d}_{tag}.png"
        if not png.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(vid), "-frames:v", "1", str(png)], check=True)
        im = Image.open(png).convert("RGB")
        if crop: im = im.crop(crop)
        pair.append(im.resize((im.width // 2, im.height // 2)))
    w, h = pair[0].size
    tile = Image.new("RGB", (w * 2 + 6, h + 18), "white")
    tile.paste(pair[0], (0, 18)); tile.paste(pair[1], (w + 6, 18))
    ImageDraw.Draw(tile).text((4, 3), f"ep{int(r.episode_index)}  start | end  ({r.length/30:.1f}s)", fill="black")
    tiles.append(tile)
cols = 4; tw, th = tiles[0].size
for p in range(0, len(tiles), 20):
    page = tiles[p:p + 20]; rows = (len(page) + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * rows), "gray")
    for i, t in enumerate(page): sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
    sheet.save(out / f"sheet_{cam}_{p // 20}.jpg", quality=85)
    print(out / f"sheet_{cam}_{p // 20}.jpg", sheet.size)
