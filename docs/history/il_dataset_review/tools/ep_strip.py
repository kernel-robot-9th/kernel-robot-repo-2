import sys, glob, subprocess
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw
root, cam, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]); wanted = [int(x) for x in sys.argv[4].split(",")]
n = 7
eps = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(root / "meta/episodes/*/*.parquet")))).set_index("episode_index")
k = f"videos/observation.images.{cam}"
rows = []
for ep in wanted:
    r = eps.loc[ep]
    vid = root / f"videos/observation.images.{cam}/chunk-{int(r[k+'/chunk_index']):03d}/file-{int(r[k+'/file_index']):03d}.mp4"
    a, b = r[k+"/from_timestamp"] + 0.05, r[k+"/to_timestamp"] - 0.15
    ims = []
    for i in range(n):
        t = a + (b - a) * i / (n - 1); png = out / f"strip_ep{ep:03d}_{i}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(vid), "-frames:v", "1", str(png)], check=True)
        im = Image.open(png).convert("RGB").crop((0, 200, 400, 480)); ims.append(im.resize((im.width * 2 // 3, im.height * 2 // 3)))
    w, h = ims[0].size; row = Image.new("RGB", (w * n + 4 * n, h + 16), "white")
    for i, im in enumerate(ims): row.paste(im, (i * (w + 4), 16))
    ImageDraw.Draw(row).text((4, 2), f"ep{ep}  ({r.length/30:.1f}s)  0s ... end", fill="black"); rows.append(row)
sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), "gray"); y = 0
for r in rows: sheet.paste(r, (0, y)); y += r.height
sheet.save(out / sys.argv[5]); print(out / sys.argv[5], sheet.size)
