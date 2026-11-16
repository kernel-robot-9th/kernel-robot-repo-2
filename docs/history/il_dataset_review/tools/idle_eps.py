import sys, glob
import numpy as np, pandas as pd
root = sys.argv[1]
df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{root}/data/*/*.parquet"))])
rows = []
for ep, g in df.groupby("episode_index"):
    st = np.stack(g["observation.state"].to_numpy())[:, :6]
    n = len(st); moved = np.abs(st - st[0]).max(axis=1) > 2.0
    s = (np.argmax(moved) if moved.any() else n) / 30
    me = np.abs(st - st[-1]).max(axis=1) > 2.0
    e = (n - 1 - (n - 1 - np.argmax(me[::-1]))) / 30 if me.any() else n / 30
    rows.append((ep, n / 30, s, e, np.ptp(st, axis=0).max()))
r = np.array(rows)
print("에피소드 길이 분포(초): 최소 %.1f 중앙 %.1f 최대 %.1f" % (r[:,1].min(), np.median(r[:,1]), r[:,1].max()))
print("시작 3초 이상 정지:", int((r[:,2] >= 3).sum()), " 끝 3초 이상 정지:", int((r[:,3] >= 3).sum()), " 거의 안 움직임(전체 범위<5):", int((r[:,4] < 5).sum()))
for ep, n, s, e, rng in r[(r[:,2] >= 3) | (r[:,3] >= 3)][:8]:
    print(f"  ep{int(ep):3d} 길이 {n:5.1f}s 시작정지 {s:4.1f}s 끝정지 {e:4.1f}s 움직임범위 {rng:5.1f}")
