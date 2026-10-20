# Estimate the gripper tip in the top image at the grasp moment: pixels that are dark in the grasp frame but
# were not dark at the episode start (the left arm moved there); tip = the arm pixel farthest from the arm base.
import cv2, numpy as np
img = cv2.imread('/home/omen/main_project/grasp_one_case_ep5.jpg')
H, W = 480, 640
start = img[0:480, 0:640].astype(int); grasp = img[480:960, 0:640].astype(int)
def dark(a): return (a.max(axis=2) < 70)
new = dark(grasp) & ~dark(start)
new[:60] = False  # label bar
new = cv2.morphologyEx(new.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
n, lab, stats, _ = cv2.connectedComponentsWithStats(new)
k = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])  # biggest new dark blob = the arm
ys, xs = np.where(lab == k)
base = np.array([100, 470])  # left arm base, bottom-left of the image
d = np.hypot(xs - base[0], ys - base[1]); i = np.argsort(d)[-30:]  # 30 farthest pixels
tip = (int(xs[i].mean()), int(ys[i].mean()))
out = img[480:960, 0:640].copy()
overlay = out.copy(); overlay[lab == k] = (0, 0, 255); out = cv2.addWeighted(out, 0.6, overlay, 0.4, 0)
cv2.circle(out, tip, 10, (0, 255, 255), 3); cv2.circle(out, tuple(base), 8, (255, 0, 255), 3)
cv2.putText(out, f'tip {tip}', (tip[0] + 14, tip[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
cv2.imwrite('/home/omen/main_project/grasp_one_case_ep5_tip.jpg', out)
print('tip', tip)
