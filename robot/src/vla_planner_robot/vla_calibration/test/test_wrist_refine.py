import numpy as np

from vla_calibration.wrist_refine import fit_affine, refined_homography


def test_fit_affine_recovers_shift_and_scale():
    src = np.array([[0.18, -0.05], [0.22, -0.07], [0.20, 0.05], [0.24, 0.03], [0.17, 0.0]])
    A_true = np.array([[1.08, 0.02, 0.012], [-0.01, 0.97, -0.003]])
    dst = src @ A_true[:, :2].T + A_true[:, 2]
    A, res = fit_affine(src, dst)
    assert np.allclose(A, A_true, atol=1e-9) and res.max() < 1e-9


def test_refined_homography_applies_the_correction_after_h():
    H = np.array([[0.001, 0.0, -0.5], [0.0, -0.001, 0.3], [0.0, 0.0, 1.0]])
    A = np.array([[1.0, 0.0, 0.03], [0.0, 1.0, 0.0]])
    p = H @ [400.0, 200.0, 1.0]
    q = refined_homography(H, A) @ [400.0, 200.0, 1.0]
    assert np.allclose(q[:2] / q[2], p[:2] / p[2] + [0.03, 0.0])
