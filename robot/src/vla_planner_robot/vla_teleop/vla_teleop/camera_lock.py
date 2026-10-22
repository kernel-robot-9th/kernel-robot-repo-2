"""Fixed camera exposure and white balance (UVC, through v4l2-ctl), so colors look the same in every capture.

Auto exposure drifts with the scene and washed the pastel erasers out to white (S 50-80 at V 255). `tune` picks a
manual exposure that keeps the bright work area just under clipping and a white balance that keeps white paper
neutral; `lock` re-applies the saved values (UVC cameras forget them when they are unplugged).
"""
import os
import re
import subprocess
import time

import yaml

TARGET_V = 230          # 98th percentile of V in the work area: white paper just below clipping
PERCENTILE = 98


def parse_ctrls(text):
    """`v4l2-ctl --list-ctrls` output -> {name: {'min', 'max', 'default', 'value'}} (ints only)."""
    ctrls = {}
    for line in text.splitlines():
        match = re.match(r'\s*(\w+) 0x[0-9a-f]+ \((\w+)\)\s*:(.*)', line)
        if not match:
            continue
        fields = dict(re.findall(r'(\w+)=(-?\d+)', match.group(3)))
        ctrls[match.group(1)] = {k: int(v) for k, v in fields.items() if k in ('min', 'max', 'default', 'value')}
    return ctrls


def read_ctrls(device):
    out = subprocess.run(['v4l2-ctl', '-d', device, '--list-ctrls'], capture_output=True, text=True, check=True)
    return parse_ctrls(out.stdout)


def set_ctrls(device, values):
    """Set controls in the given order (auto modes must be switched off before their manual values apply)."""
    for name, value in values.items():
        subprocess.run(['v4l2-ctl', '-d', device, '-c', f'{name}={value}'], capture_output=True, text=True, check=True)


def search_exposure(measure, low, high, target=TARGET_V, steps=12):
    """Largest exposure whose brightness `measure(exposure)` stays at or under target (brightness rises with
    exposure). [출력] (exposure, brightness)."""
    best = (low, measure(low))
    for _ in range(steps):
        if high - low <= 1:
            break
        mid = (low + high) // 2
        value = measure(mid)
        if value <= target:
            best, low = (mid, value), mid
        else:
            high = mid
    return best


def search_focus(measure, low, high, coarse=16):
    """Focus value with the highest `measure` (image sharpness): a coarse sweep, then a finer one around the best.
    [출력] (focus, sharpness)."""
    step = max(1, (high - low) // coarse)
    best = max(((f, measure(f)) for f in range(low, high + 1, step)), key=lambda fv: fv[1])
    fine = max(1, step // 4)
    lo, hi = max(low, best[0] - step), min(high, best[0] + step)
    return max([best] + [(f, measure(f)) for f in range(lo, hi + 1, fine) if f != best[0]], key=lambda fv: fv[1])


def grab(cap, frames=6):
    frame = None
    for _ in range(frames):          # a few frames for the new setting to reach the image
        ok, image = cap.read()
        if ok:
            frame = image
    return frame


def work_area(frame, rows=(0.40, 0.90)):
    h = frame.shape[0]
    return frame[int(h * rows[0]):int(h * rows[1])]


def tune(device, width=None, height=None):
    """[출력] dict of control values for `device`: manual exposure under clipping + white balance for neutral white."""
    import cv2
    import numpy as np
    ctrls = read_ctrls(device)
    base = {'auto_exposure': 1}                                   # 1 = manual mode
    if 'exposure_dynamic_framerate' in ctrls:
        base['exposure_dynamic_framerate'] = 0
    if 'gain' in ctrls:
        base['gain'] = ctrls['gain']['min']
    if 'backlight_compensation' in ctrls:
        base['backlight_compensation'] = 0
    if 'focus_automatic_continuous' in ctrls:                     # a moving focus changes the lens model (K)
        base['focus_automatic_continuous'] = 0
    set_ctrls(device, base)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    grab(cap, frames=30)                                          # warm-up: the first frames after opening are dark

    def brightness(exposure):
        set_ctrls(device, {'exposure_time_absolute': exposure})
        frame = grab(cap)
        if frame is None:
            raise RuntimeError(f'{device}: no image (busy or unplugged?)')
        hsv = cv2.cvtColor(work_area(frame), cv2.COLOR_BGR2HSV)
        return float(np.percentile(hsv[..., 2], PERCENTILE))

    exp = ctrls['exposure_time_absolute']
    if brightness(exp['max']) < 60:
        cap.release()
        set_ctrls(device, {'auto_exposure': ctrls['auto_exposure']['value']})
        raise RuntimeError(f'{device}: image stays dark even at the longest exposure (lens covered? lights off?)')
    exposure, v = search_exposure(brightness, exp['min'], exp['max'])
    set_ctrls(device, {'exposure_time_absolute': exposure})
    result = dict(base, exposure_time_absolute=exposure)
    if 'focus_absolute' in ctrls:     # autofocus off: sweep the lens and keep the sharpest setting for the work area

        def sharpness(focus):
            set_ctrls(device, {'focus_absolute': focus})
            gray = cv2.cvtColor(work_area(grab(cap, frames=12)), cv2.COLOR_BGR2GRAY)
            return float(cv2.Laplacian(gray, cv2.CV_64F).var())

        fc = ctrls['focus_absolute']
        focus, sharp = search_focus(sharpness, fc['min'], fc['max'])
        set_ctrls(device, {'focus_absolute': focus})
        result['focus_absolute'] = focus
    if 'white_balance_temperature' in ctrls:
        set_ctrls(device, {'white_balance_automatic': 0})
        wb = ctrls['white_balance_temperature']

        def tint(temperature):        # blue minus red on bright, unsaturated pixels (white paper, walls)
            set_ctrls(device, {'white_balance_temperature': temperature})
            image = work_area(grab(cap)).astype(np.float32)
            hsv = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_BGR2HSV)
            white = (hsv[..., 1] < 40) & (hsv[..., 2] > 150)
            return float(image[..., 0][white].mean() - image[..., 2][white].mean()) if white.any() else 0.0

        candidates = range(wb['min'], wb['max'] + 1, 300)
        coarse = min(candidates, key=lambda t: abs(tint(t)))
        fine = min(range(max(wb['min'], coarse - 300), min(wb['max'], coarse + 300) + 1, 100), key=lambda t: abs(tint(t)))
        set_ctrls(device, {'white_balance_temperature': fine})
        result.update(white_balance_automatic=0, white_balance_temperature=fine)
    cap.release()
    print(f'   {device}: exposure {exposure} (V p{PERCENTILE} {v:.0f}, target {TARGET_V}), '
          f'white balance {result.get("white_balance_temperature", "n/a")} K, focus {result.get("focus_absolute", "n/a")}')
    return result


def lock(device, values):
    """Apply saved values; [출력] {name: (wanted, read back)} for the ones that did not stick."""
    set_ctrls(device, values)
    now = read_ctrls(device)
    return {k: (v, now.get(k, {}).get('value')) for k, v in values.items() if now.get(k, {}).get('value') != v}


def load(path):
    try:
        with open(os.path.expanduser(path)) as handle:
            return yaml.safe_load(handle) or {}
    except OSError:
        return {}


def save(path, settings):
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as handle:
        handle.write(f'# fixed camera controls (v4l2-ctl names), written by `teleop camera --tune` {time.strftime("%F %T")}\n')
        yaml.safe_dump(settings, handle, sort_keys=False)
