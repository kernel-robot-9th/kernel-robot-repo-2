"""바닥의 검은 테이프 선 = "넘지 말 것" (병원의 열린 방은 이것으로 막혀 있음).

선을 볼 수 있는 센서는 두 가지:
  * CameraLine: 카메라 영상의 아래쪽은 Pinky 앞 15-30 cm의 바닥을 봄. 거기에 있는 어둡고
    길고 가는 덩어리가 테이프. 카메라 기하 (높이, 기울기, fx/fy)로 픽셀을 바닥 위 미터로
    바꾸므로, 선은 base_footprint 기준 선분 (x 앞, y 왼쪽)으로 반환됨.
  * IRLine (선택): Pinky의 바닥 IR 센서 (pinkylib.IR). 이 API는 아직 확인되지 않음:
        python3 robot/line_detector.py --probe-ir      # IR 클래스와 실시간 값 출력
    Pinky를 카펫 위에, 그다음 테이프 위에 두고 출력을 보내 주세요.
        python3 robot/line_detector.py --ir-test       # 실시간: floor / BLACK (guide_mode와 같은 판정),
                                                       # 어느 센서 (L/M/R)가 테이프 위인지: 왼쪽 앞 모서리만
                                                       # 테이프에 올려서 L이라고 나오는지 확인

사진으로 카메라 검출기 테스트 (Pinky 카메라로 찍은 똑바른 사진):
  python3 robot/line_detector.py --image floor.jpg            # 선을 출력하고 floor_line.jpg 저장
Pinky에서 실시간 테스트 (cam_pub.py + vslam.launch.py 실행 중): /vslam/image_raw 한 프레임을 받아
~/line_test.jpg와 ~/line_test_line.jpg를 저장하고 찾은 어두운 덩어리마다 설명함:
  python3 robot/line_detector.py --ros
"""
from __future__ import annotations

import argparse
import inspect
import math
import time
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Line:
    dist: float                         # 로봇 중심에서 로봇 경로 위 선까지의 m (inf: 경로 옆)
    p1: tuple[float, float]             # 바닥 위 선분 끝점, base_footprint (x 앞, y 왼쪽)
    p2: tuple[float, float]
    contour: np.ndarray | None = None   # 영상 픽셀, 디버그 영상용


class CameraLine:
    def __init__(self, fx: float, fy: float, cx: float, cy: float, cam_x: float = 0.03, cam_z: float = 0.062,
                 pitch: float = 0.072, max_dist: float = 0.30, dark_ratio: float = 0.55, dark_max: int = 80,
                 min_len: float = 0.08, path_half: float = 0.10, max_thick: float = 0.08, white_min: int = 160):
        self.fx, self.fy, self.cx, self.cy = fx, fy, cx, cy
        self.cam_x, self.cam_z, self.pitch = cam_x, cam_z, pitch
        self.max_dist = max_dist        # 바닥을 이 거리까지 봄
        self.dark_ratio = dark_ratio    # 테이프 픽셀 < 바닥 밝기 * 이 값
        self.dark_max = dark_max        # ... 그리고 이 값보다 어두움 (0-255)
        self.white_min = white_min      # 더 밝은 픽셀은 흰 벽 / 흰 테이프: 바닥 밝기 계산에서 제외
        self.min_len = min_len          # m: 더 짧은 어두운 덩어리는 먼지, 케이블, 신발
        self.max_thick = max_thick      # m: 더 넓은 덩어리는 그림자나 어두운 매트, 테이프가 아님
        self.path_half = path_half      # m: 선이 Pinky 앞의 이 띠를 가로지르면 해당

    def row_of(self, d: float) -> float:
        """바닥이 로봇 중심 앞 d 미터인 영상 행."""
        a = math.atan2(self.cam_z, d - self.cam_x) - self.pitch
        return self.cy + self.fy * math.tan(a)

    def to_floor(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """픽셀 -> base_footprint 기준 바닥 점 (x 앞, y 왼쪽). 지평선 위의 행 -> nan."""
        down = self.pitch + np.arctan2(v - self.cy, self.fy)
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = np.where(down > 0.01, self.cam_z / np.tan(down), np.nan)
        rng = np.hypot(xc, self.cam_z)
        y = -(u - self.cx) / self.fx * rng
        return xc + self.cam_x, y

    def detect(self, bgr: np.ndarray, scale: float = 0.5, why: list | None = None) -> Line | None:
        """Pinky 경로 위의 가장 가까운 테이프 선, 없으면 None."""
        path = [ln for ln in self.detect_all(bgr, scale, why) if math.isfinite(ln.dist)]
        return min(path, key=lambda ln: ln.dist) if path else None

    def detect_all(self, bgr: np.ndarray, scale: float = 0.5, why: list | None = None,
                   exclude: list | None = None) -> list[Line]:
        """시야 안의 모든 테이프 선, 경로 옆 포함 (좁은 복도에서는 테이프가 옆면을 따라 이어지는 경우가 많음).
        why: 리스트를 넘기면 어두운 덩어리마다 한 줄씩 설명 (테이프인지 아닌지와 그 이유).
        exclude: 무시할 영상 박스 (x1, y1, x2, y2, ...): 사람 (어두운 신발과 바지는 테이프처럼 보임)."""
        h, w = bgr.shape[:2]
        top = int(max(0, min(h - 10, self.row_of(self.max_dist))))
        roi = cv2.resize(bgr[top:], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        # 카펫만으로 바닥 밝기 계산: 흰 벽과 흰 테이프 선 (2026-10-29 지도)이 18 cm 복도에서
        # 시야의 많은 부분을 차지해 중앙값을 올리므로, 회색 카펫 자체가 "어둡게" 보이게 됨
        not_white = gray[gray < self.white_min]
        floor = float(np.median(not_white)) if not_white.size > 0.2 * gray.size else float(np.median(gray))
        thr = min(self.dark_max, floor * self.dark_ratio)
        mask = (gray < thr).astype(np.uint8)
        for b in exclude or []:
            x1, y1, x2, y2 = b[:4]
            mx = 0.15 * (x2 - x1)
            mask[max(0, int((y1 - top) * scale)):max(0, int((y2 + 0.1 * (y2 - y1) - top) * scale)),
                 max(0, int((x1 - mx) * scale)):max(0, int((x2 + mx) * scale))] = 0
        if why is not None:
            why.append(f"floor brightness {floor:.0f}, tape must be darker than {thr:.0f}; darkest {gray.min()}, "
                       f"rows {top}-{h} = floor {self.max_dist:.2f}-{self.to_floor(np.array([w / 2]), np.array([h - 1.0]))[0][0]:.2f} m ahead")
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)  # 모든 경계 픽셀
        found = []
        for c in contours:
            if cv2.contourArea(c) < 30:
                continue  # 픽셀 몇 개: 노이즈
            pix = c.reshape(-1, 2).astype(np.float64) / scale + (0, top)
            x, y = self.to_floor(pix[:, 0], pix[:, 1])
            ok = np.isfinite(x)
            if ok.sum() < 3:
                continue
            fl = np.stack([x[ok], y[ok]], axis=1).astype(np.float32)
            (mx, my), (a, b), ang = cv2.minAreaRect(fl)
            length, thick = max(a, b), min(a, b)
            desc = f"dark blob at ({mx:.2f}, {my:+.2f}) m: {length * 100:.0f} cm long, {thick * 100:.0f} cm wide"
            if length < self.min_len or thick > self.max_thick:
                if why is not None:
                    why.append(desc + (f" -> too short (< {self.min_len * 100:.0f} cm)" if length < self.min_len
                                       else f" -> too wide (> {self.max_thick * 100:.0f} cm)"))
                continue
            band = fl[np.abs(fl[:, 1]) < self.path_half]
            dist = float(band[:, 0].min()) if len(band) else math.inf
            if why is not None:
                why.append(desc + (f" -> TAPE, {dist:.2f} m ahead" if len(band) else " -> TAPE, beside the path"))
            # 사각형의 긴 축 = 바닥 위 테이프 방향
            t = math.radians(ang) if a >= b else math.radians(ang + 90)
            dx, dy = math.cos(t) * length / 2, math.sin(t) * length / 2
            found.append(Line(dist, (mx - dx, my - dy), (mx + dx, my + dy), pix.astype(np.int32)))
        return found


class IRLine:
    """Pinky의 바닥 IR 센서 3개 (pinkylib.IR.read_ir() -> [왼쪽?, 가운데, 오른쪽?], 12비트 ADC 0-4095), 바퀴 축보다
    ~4 cm 앞. 검은 테이프는 IR을 적게 반사하므로 값이 올라감 (probe 2026-10-27: 바닥 ~2750/3030/2800,
    테이프와 공중은 더 높음, 4095 = 센서 아래에 아무것도 없음). 흰 테이프는 더 많이 반사하므로 값이 내려감 (2026-10-29:
    흰 테이프 위에서 시작하니 "바닥"이 1266/1432). 검정만 해당; 흰 선은 카펫처럼 무시함.
    센서마다 자기 바닥 기준값이 있음: 시작할 때 흰색이 아닌 측정값으로 학습 (흰 테이프 위에서 시작한
    센서는 기본 카펫 값을 받음)하고, 이후 카펫을 천천히 따라가되 카펫 같은 측정값만 사용함:
    2026-10-29 전에는 검정이 아닌 모든 값을 학습해서, 흰 선을 따라 주행하면 바닥 값이 내려가고
    평범한 카펫이 "검정"으로 보였음 ("tape under LMR"과 함께 LINE -> TURN 반복).
    검정 = 3개 센서 평균이 바닥 기준보다 `margin_avg` 이상 높음 (테이프가 앞 가장자리 전체 아래),
    또는 센서 하나가 `margin` 이상 높음 (테이프가 한쪽 모서리 아래), 연속 `frames`번.
    --ir-test 2026-10-27 (손으로 이동): 정지 시 바닥 +-10, 이동 중 바닥은 센서 하나에서 최대 +330이지만 평균은
    < +260; 테이프는 세 센서 모두 +300..+850."""

    DEFAULT_FLOOR = (2750.0, 3030.0, 2800.0)  # 카펫, read_ir() 순서 (probe 2026-10-27, 2026-10-29 주행 2577-3088)

    def __init__(self, method: str = "read_ir", margin: float = 500.0, black_high: bool = True, frames: int = 2,
                 log=print, margin_avg: float = 300.0, order: str = "LMR", margin_side: float = 400.0,
                 white_below: float = 2100.0, follow: float = 250.0):
        from pinkylib import IR
        self.ir = IR()
        self.read = getattr(self.ir, method)
        self.margin, self.margin_avg, self.black_high, self.frames, self.log = margin, margin_avg, black_high, frames, log
        # read_ir() 값이 각각 어느 센서인지 (L 왼쪽, M 가운데, R 오른쪽); --ir-test로 확인
        self.order, self.margin_side = order.upper(), margin_side
        self.white_below = white_below  # 이 값보다 낮은 원시값 = 흰 테이프 (또는 아주 반짝이는 바닥): 테이프도 바닥도 아님
        self.follow = follow            # 바닥 기준값은 이만큼 가까운 측정값만 따라감 (카펫은 천천히 바뀜)
        self.side_hits = np.zeros(3)
        self.sides = {"L": False, "M": False, "R": False}
        self.white = {"L": False, "M": False, "R": False}
        self.floor = None
        self.start: list = []
        self.hits = 0
        self.last = None
        self.diff = None
        self.err_t = 0.0

    def values(self):
        try:
            v = self.read()
        except Exception as e:
            v, err = None, e
        else:
            err = "no data"
        if v is None:
            if time.time() - self.err_t > 5.0:
                self.err_t = time.time()
                self.log(f"IR read error: {err}")
            return None
        return np.atleast_1d(np.asarray(v, dtype=np.float64))

    def is_white(self, v: np.ndarray) -> np.ndarray:
        return v < self.white_below if self.black_high else v > self.white_below

    def learn(self) -> None:
        """센서별 바닥 기준값 = 카펫이었던 시작 측정값의 중앙값 (흰색, 테이프, 공중 제외)."""
        a = np.array(self.start)
        n = a.shape[1]
        default = np.array([self.DEFAULT_FLOOR[i] if i < 3 else self.DEFAULT_FLOOR[1] for i in range(n)])
        floor, note = default.copy(), []
        for i in range(n):
            col = a[:, i]
            ok = col[~self.is_white(col) & (np.abs(col - default[i]) < 700)]
            if len(ok) >= 3:
                floor[i] = np.median(ok)
            else:
                note.append(f"sensor {i} started on {'white' if np.median(col) < default[i] else 'black'} "
                            f"({np.median(col):.0f}): default {default[i]:.0f}")
        self.floor = floor
        self.diff = np.zeros_like(floor)
        self.log(f"IR floor level: {np.round(floor).astype(int).tolist()}, black: average above +{self.margin_avg:.0f} "
                 f"or one above +{self.margin:.0f}; white (below {self.white_below:.0f}) is ignored"
                 + ("; " + "; ".join(note) if note else ""))

    def black(self) -> bool:
        v = self.values()
        if v is None:
            return False
        self.last = v
        if self.floor is None:  # 처음 10개 측정값으로 바닥 학습
            self.start.append(v)
            if len(self.start) >= 10:
                self.learn()
            return False
        white = self.is_white(v)
        diff = (v - self.floor) if self.black_high else (self.floor - v)
        diff = np.where(white, 0.0, np.maximum(diff, 0.0))  # 흰 테이프와 바닥보다 밝은 값: 검정 아님
        self.diff = diff
        dark = bool(diff.mean() > self.margin_avg or diff.max() > self.margin)
        self.hits = self.hits + 1 if dark else 0
        each = diff[:3] > self.margin_side if len(diff) >= 3 else np.zeros(3, bool)
        self.side_hits = np.where(each, self.side_hits + 1, 0)
        self.sides = {k: bool(self.side_hits[i] >= self.frames) for i, k in enumerate(self.order[:3])}
        self.white = {k: bool(white[i]) for i, k in enumerate(self.order[:3]) if i < len(white)}
        if not dark:  # 카펫은 방마다 천천히 바뀜: 따라가되 흰 테이프나 검은 테이프 값으로는 절대 따라가지 않음
            near = ~white & (np.abs(v - self.floor) < self.follow)
            self.floor = np.where(near, 0.98 * self.floor + 0.02 * v, self.floor)
        return self.hits >= self.frames


def probe_ir(seconds: float = 30.0):
    try:
        from pinkylib import IR
    except Exception as e:
        print(f"pinkylib.IR not available: {e}")
        return
    print("IR:", inspect.signature(IR))
    try:
        print(inspect.getsource(IR)[:3000])
    except (OSError, TypeError):
        pass
    ir = IR()
    methods = [m for m in dir(ir) if not m.startswith("_") and callable(getattr(ir, m))]
    print("methods:", methods)
    readers = []
    for m in methods:
        try:
            if all(p.default is not inspect.Parameter.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                   for p in inspect.signature(getattr(ir, m)).parameters.values()) \
                    and any(k in m.lower() for k in ("read", "get", "value", "sensor", "ir")):
                readers.append(m)
        except (TypeError, ValueError):
            pass
    print("reading with:", readers, f"for {seconds:.0f} s. Move Pinky: carpet -> tape -> carpet")
    t_end = time.time() + seconds
    while time.time() < t_end:
        row = []
        for m in readers:
            try:
                row.append(f"{m}={getattr(ir, m)()}")
            except Exception as e:
                row.append(f"{m}: {e}")
        print("  ".join(row))
        time.sleep(0.3)


def grab(topic: str, timeout: float = 10.0) -> np.ndarray:
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    rclpy.init()
    node = rclpy.create_node("line_test")
    got = {}
    node.create_subscription(Image, topic, lambda m: got.setdefault("m", m), qos_profile_sensor_data)
    t_end = time.time() + timeout
    while "m" not in got and time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_node()
    rclpy.try_shutdown()
    if "m" not in got:
        raise SystemExit(f"no image on {topic} in {timeout:.0f} s: are cam_pub.py and vslam.launch.py running?")
    m = got["m"]
    img = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.width, -1)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if m.encoding == "rgb8" else img.copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--calib", default="~/pinky_camera.yaml")
    ap.add_argument("--probe-ir", action="store_true")
    ap.add_argument("--ir-test", action="store_true", help="실시간 IR 값과 BLACK/floor 판정 (guide_mode와 동일)")
    ap.add_argument("--ir-margin", type=float, default=500.0)
    ap.add_argument("--ir-margin-avg", type=float, default=300.0)
    ap.add_argument("--ir-order", default="LMR", help="read_ir() 값 중 어느 것이 왼쪽/가운데/오른쪽 센서인지")
    ap.add_argument("--ir-white", type=float, default=2100.0, help="이 값보다 낮은 원시값 = 흰 테이프, 무시")
    ap.add_argument("--ros", action="store_true", help="--topic에서 한 프레임 받기")
    ap.add_argument("--topic", default="/vslam/image_raw")
    a = ap.parse_args()
    if a.probe_ir:
        return probe_ir()
    if a.ir_test:
        ir = IRLine(margin=a.ir_margin, margin_avg=a.ir_margin_avg, frames=1, order=a.ir_order,
                    white_below=a.ir_white)  # guide_mode: 연속 2번
        print("keep Pinky on the floor for 2 s, then push it SLOWLY over the tape, wheels on the floor")
        while True:
            b = ir.black()
            if ir.last is not None:
                print(ir.last.astype(int).tolist(), "learning the floor" if ir.floor is None else
                      ("BLACK" if b else "floor") + f"  +{np.round(ir.diff).astype(int).tolist()}, avg +{ir.diff.mean():.0f}"
                      f"  tape under: {''.join(k for k, v in ir.sides.items() if v) or '-'}"
                      f"  white (ignored): {''.join(k for k, v in ir.white.items() if v) or '-'}  (floor {np.round(ir.floor).astype(int).tolist()})")
            time.sleep(0.2)
    import os
    import yaml
    if a.ros:
        img = grab(a.topic)
        a.image = os.path.expanduser("~/line_test.jpg")
        cv2.imwrite(a.image, img)
        print("saved", a.image)
    elif not a.image:
        ap.error("--image, --ros or --probe-ir")
    else:
        img = cv2.imread(a.image)
    if img is None:
        raise SystemExit(f"could not read {a.image}")
    h, w = img.shape[:2]
    fx = fy = 582.5 * w / 640
    cx, cy = w / 2, h / 2
    path = os.path.expanduser(a.calib)
    if os.path.exists(path):
        k = yaml.safe_load(open(path))["camera_matrix"]["data"]
        fx, cx, fy, cy = k[0], k[2], k[4], k[5]
    det = CameraLine(fx, fy, cx, cy)
    t = time.time()
    why = []
    lines = det.detect_all(img, why=why)
    print(f"{(time.time() - t) * 1000:.0f} ms")
    print("\n".join(why) if len(why) > 1 else "\n".join(why + ["no dark blob at all"]))
    if not lines:
        print("no line")
    for ln in lines:
        where = f"{ln.dist:.2f} m ahead" if math.isfinite(ln.dist) else "beside the path"
        print(f"line {where}, from ({ln.p1[0]:.2f}, {ln.p1[1]:+.2f}) to ({ln.p2[0]:.2f}, {ln.p2[1]:+.2f}) m")
        cv2.drawContours(img, [ln.contour], -1, (0, 255, 255), 2)
    cv2.line(img, (0, int(det.row_of(det.max_dist))), (w, int(det.row_of(det.max_dist))), (255, 0, 0), 1)
    out = os.path.splitext(a.image)[0] + "_line.jpg"
    cv2.imwrite(out, img)
    print("wrote", out)


if __name__ == "__main__":
    main()
