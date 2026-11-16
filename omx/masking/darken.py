# Darken an auto-exposure frame toward the exposure-90 look; near-white pixels are pulled to neutral grey (no pink tint).
import numpy as np
def darken(a, lut, lo=200, hi=245):
    d = np.stack([lut[ch][a[..., ch]] for ch in range(3)], -1).astype(np.float32)
    w = np.clip((a.min(-1).astype(np.float32) - lo) / (hi - lo), 0, 1)[..., None]
    return ((1 - w) * d + w * d.mean(-1, keepdims=True)).astype(np.uint8)
