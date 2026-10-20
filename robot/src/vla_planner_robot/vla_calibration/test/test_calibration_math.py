import cv2
import numpy as np
import pytest

from vla_calibration.colors import hsv_range, range_hues
from vla_calibration.intrinsics import calibrate
from vla_calibration.table import apply_rigid, base_from_fit, fit_rigid, leave_one_out, robust_fit
from vla_calibration.wrist import choose_threshold, roi_from_masks

K = np.array([[800.0, 0, 320], [0, 800.0, 240], [0, 0, 1]])


def test_fit_rigid_recovers_transform():
    rng = np.random.default_rng(3)
    src = rng.uniform([0.1, -0.15], [0.25, 0.15], (8, 2))
    th, t = np.radians(1.5), np.array([0.008, -0.004])
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    dst = src @ R.T + t
    s, R2, t2 = fit_rigid(src, dst)
    assert s == 1.0 and np.allclose(R2, R) and np.allclose(t2, t)
    assert max(leave_one_out(src, dst)) < 1e-9
    s, _, _ = fit_rigid(src, dst * 1.01, scale=True)
    assert s == pytest.approx(1.01, rel=1e-6)
    assert np.allclose(apply_rigid((1.0, R, t), src), dst)


def test_hsv_range_handles_red_wrap():
    rng = np.random.default_rng(0)
    h = np.concatenate([rng.integers(0, 5, 500), rng.integers(175, 180, 500)])
    px = np.c_[h, rng.integers(200, 256, 1000), rng.integers(150, 256, 1000)].astype(np.uint8)
    r = hsv_range(px)
    assert len(r) == 12                    # split into two ranges around 0/179
    assert 0 in range_hues(r) and 179 in range_hues(r) and 90 not in range_hues(r)


def test_hsv_range_simple():
    px = np.c_[np.full(100, 60), np.full(100, 200), np.full(100, 180)].astype(np.uint8)
    lo_h, s_lo, v_lo, hi_h = hsv_range(px)[:4]
    assert lo_h < 60 < hi_h and s_lo <= 200 and v_lo <= 180


def test_roi_and_threshold():
    masks = []
    for dx in (0, 3, -2):
        m = np.zeros((240, 320), np.uint8)
        m[90 + dx:190, 120:215 + dx] = 255
        masks.append(m)
    x0, y0, x1, y1 = roi_from_masks(masks)
    assert 120 / 320 < x0 < x1 < 215 / 320 and 90 / 240 < y0 < y1 < 190 / 240
    thr, margin, ok = choose_threshold([0.95, 0.9], [0.0, 0.1])
    assert thr == pytest.approx(0.5) and ok
    assert not choose_threshold([0.4], [0.3])[2]


def test_intrinsics_from_synthetic_views():
    objp = np.zeros((54, 3), np.float32)
    objp[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2) * 0.03
    rng = np.random.default_rng(1)
    obj, img = [], []
    for _ in range(12):
        rvec = rng.uniform(-0.4, 0.4, 3)
        tvec = np.array([rng.uniform(-0.15, 0.0), rng.uniform(-0.1, 0.0), rng.uniform(0.5, 0.8)])
        p, _ = cv2.projectPoints(objp, rvec, tvec, K, np.zeros(5))
        obj.append(objp)
        img.append(p.astype(np.float32))
    rms, Kc, D, _ = calibrate(obj, img, (640, 480))
    assert rms < 0.01 and abs(Kc[0, 0] - 800) < 1.0


def test_param_file_has_no_aliases(tmp_path):
    from vla_calibration.common import update_param_file
    v = [1, 2, 3]
    p = update_param_file(str(tmp_path / 'x.yaml'), {'a': {'hsv.red': v}, 'b': {'hsv.red': v}})
    text = open(p).read()
    assert '&' not in text and '*' not in text
    assert 'hsv:' in text and 'red: [1, 2, 3]' in text


def test_robust_fit_drops_outlier():
    rng = np.random.default_rng(4)
    src = rng.uniform([0.1, -0.15], [0.25, 0.15], (10, 2))
    dst = src + [0.006, -0.003] + rng.normal(0, 0.001, src.shape)
    dst[3] += [0.02, 0.0]                       # one slipped placement
    T, keep = robust_fit(src, dst)
    assert 3 not in keep and len(keep) == 9
    assert np.allclose(T[2], [0.006, -0.003], atol=0.0015)


def test_base_from_fit_recovers_true_arm_base():
    # the URDF assumes the left base at (0, 0.165, yaw 0); in reality it sits at (0.008, 0.172, 1.5 deg)
    assumed, true = (0.0, 0.165, 0.0), (0.008, 0.172, np.radians(1.5))

    def to_world(base, local):
        c, s = np.cos(base[2]), np.sin(base[2])
        return np.array([base[0] + c * local[0] - s * local[1], base[1] + s * local[0] + c * local[1]])

    def to_local(base, w):
        c, s = np.cos(base[2]), np.sin(base[2])
        d = np.asarray(w) - base[:2]
        return np.array([c * d[0] + s * d[1], -s * d[0] + c * d[1]])

    cmd = np.array([[0.13, 0.27], [0.13, 0.07], [0.20, 0.285], [0.20, 0.045], [0.235, 0.165], [0.16, 0.165]])
    # the executor converts a command with the assumed base; the arm really sits at `true`
    seen = np.array([to_world(true, to_local(assumed, c)) for c in cmd])
    x, y, yaw = base_from_fit(fit_rigid(seen, cmd), assumed)
    assert (x, y) == pytest.approx(true[:2], abs=1e-9) and yaw == pytest.approx(true[2], abs=1e-9)
