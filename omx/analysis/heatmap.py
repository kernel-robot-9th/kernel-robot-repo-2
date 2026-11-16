"""Draw a grasp-position heatmap over the top-camera image from grasp_points.csv (no recomputation needed).

Usage: python heatmap.py [dir] [--sigma 18] [--alpha 0.55] [--cmap jet] [--dot 5] [--out heatmap.jpg]
  dir      folder with grasp_points.csv and background.jpg (default: grasp_v2)
  --sigma  blur radius of each point in pixels (bigger = smoother heatmap)
  --alpha  heatmap opacity over the image (0..1)
  --cmap   OpenCV colormap name: jet, turbo, hot, inferno, viridis, magma, plasma ...
  --dot    radius of the white point markers (0 = no points)
  --min-area  skip episodes whose detected arm blob is smaller than this (failed detection)
"""
import argparse

import cv2
import numpy as np
import pandas as pd

p = argparse.ArgumentParser()
p.add_argument('dir', nargs='?', default='grasp_v2')
p.add_argument('--sigma', type=float, default=18)
p.add_argument('--alpha', type=float, default=0.55)
p.add_argument('--cmap', default='jet')
p.add_argument('--dot', type=int, default=5)
p.add_argument('--min-area', type=int, default=2000)
p.add_argument('--out', default=None)
a = p.parse_args()

df = pd.read_csv(f'{a.dir}/grasp_points.csv')
bad = df[df.arm_area < a.min_area]
df = df[df.arm_area >= a.min_area]
bg = cv2.imread(f'{a.dir}/background.jpg')
h, w = bg.shape[:2]

density = np.zeros((h, w), np.float32)
for x, y in zip(df.x, df.y):
    density[int(np.clip(y, 0, h - 1)), int(np.clip(x, 0, w - 1))] += 1
density = cv2.GaussianBlur(density, (0, 0), a.sigma)
norm = (density / density.max() * 255).astype(np.uint8)
cmap = getattr(cv2, f'COLORMAP_{a.cmap.upper()}')
color = cv2.applyColorMap(norm, cmap)
weight = (norm.astype(np.float32) / 255 * a.alpha)[..., None]
out = (bg * (1 - weight) + color * weight).astype(np.uint8)
if a.dot:
    for x, y in zip(df.x, df.y):
        cv2.circle(out, (int(x), int(y)), a.dot, (255, 255, 255), -1)
        cv2.circle(out, (int(x), int(y)), a.dot, (0, 0, 0), 1)
cv2.putText(out, f'grasp points n={len(df)}  (skipped {len(bad)}: failed detection)', (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
dst = a.out or f'{a.dir}/heatmap.jpg'
cv2.imwrite(dst, out, [cv2.IMWRITE_JPEG_QUALITY, 90])
print('saved', dst, '| points', len(df), '| skipped episodes', bad.episode.tolist())
print(f'x mean {df.x.mean():.0f} sd {df.x.std():.0f} range {df.x.min()}-{df.x.max()} | '
      f'y mean {df.y.mean():.0f} sd {df.y.std():.0f} range {df.y.min()}-{df.y.max()}')
