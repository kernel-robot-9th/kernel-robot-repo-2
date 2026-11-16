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


def test_fit_plane_and_descent_lookup(tmp_path):
    import yaml
    from vla_calibration.wrist_refine import Descent, fit_plane
    xy = [(0.18, -0.05), (0.22, 0.04), (0.20, 0.10), (0.15, 0.0)]
    dz = [0.01 + 0.05 * x - 0.02 * y for x, y in xy]
    assert np.allclose(fit_plane(xy, dz), (0.01, 0.05, -0.02))
    assert fit_plane(xy[:2], [0.01, 0.02])[0] == 0.015
    path = tmp_path / 'd.yaml'
    path.write_text(yaml.safe_dump({'size_model': {'k': 13.38, 'd0': 0.0609},
                                    'rows': [[0.04, 133.0, 290.0, 90.0], [0.0, 220.0, 271.0, 297.0]]}))
    d = Descent(str(path))
    assert abs(d.height(13.38 / 0.0809) - 0.02) < 1e-9
    u, v = d.ref(176.5)
    assert abs(v - 193.5) < 1e-6 and abs(u - 280.5) < 1e-6
