import sys, glob
import numpy as np, pandas as pd
root = sys.argv[1]
df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{root}/data/*/*.parquet"))])
fps = 30
L = slice(0, 6)  # left arm (action order: left first)
starts, ends, s_still, e_still, start_end_gap = [], [], [], [], []
for ep, g in df.groupby("episode_index"):
    st = np.stack(g["observation.state"].to_numpy())[:, L]
    starts.append(st[0]); ends.append(st[-1])
    moved = np.abs(st - st[0]).max(axis=1) > 2.0
    s_still.append(np.argmax(moved) / fps if moved.any() else len(st) / fps)
    moved_e = np.abs(st - st[-1]).max(axis=1) > 2.0
    last = len(st) - 1 - np.argmax(moved_e[::-1]) if moved_e.any() else 0
    e_still.append((len(st) - 1 - last) / fps)
    start_end_gap.append(np.abs(st[-1] - st[0]).max())
starts, ends = np.array(starts), np.array(ends)
print(f"episodes {len(starts)}")
print(f"시작 자세 퍼짐(관절별 표준편차, 단위 -100..100): {np.round(starts.std(0),1)}")
print(f"시작 후 멈춰 있는 시간  평균 {np.mean(s_still):.1f}s  최대 {np.max(s_still):.1f}s")
print(f"끝나기 전 멈춰 있는 시간 평균 {np.mean(e_still):.1f}s  최대 {np.max(e_still):.1f}s")
print(f"끝 자세 - 시작 자세 최대 차이: 중앙값 {np.median(start_end_gap):.1f}  최대 {np.max(start_end_gap):.1f}")
