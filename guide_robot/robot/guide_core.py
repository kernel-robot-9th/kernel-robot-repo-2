"""Pinky 안내원 모드의 로직, ROS 없이 (노트북에서도 테스트 가능).

  * scan_points / free_distance / pick_heading: LiDAR만 쓰는 지역 주행 (작은 "VFH").
  * FrontierPlanner: SLAM 지도에서 다음으로 갈 미탐색 경계를 고름.
  * GuideBrain: 행동 상태 머신
        EXPLORE  프런티어를 향해 장애물을 피하며 주행
        GREET    앞에 사람: 멈추고 인사 (Task 01), 사람이 있는 동안 대기
        WAIT     인사 후에도 같은 사람이 앞에 있음: 정지 유지, 반복 인사 없음
        YIELD    사람이 아닌 것이 길을 막음 (벽, 박스, 다른 Pinky): 정지 (빨간 LED)
        BACKUP   1 s 안에 비키지 않거나 더 다가옴: ~9 cm 후진 (Task 02)
        ESCAPE   더 빈 쪽으로 회전한 뒤 다시 EXPLORE ("다른 길 찾기")
        LOOK     사람을 찾기 위해 제자리에서 천천히 한 바퀴 (각 순찰 지점 후)
        LINE     앞 바닥에 검은 테이프 (= 막힌 방): 정지, 조금 후진
        TURN     뒤로 돌기 (~180°, 더 빈 쪽으로), 그다음 다시 EXPLORE
    본 선은 지도에 보이지 않는 벽으로 남음: Pinky는 그 너머로 주행하거나 경로를 계획하지 않으므로
    복도 안에만 머묾.
    PATROL은 지도에 프런티어가 더 없을 때의 EXPLORE: Pinky는 사람을 찾아 계속 돌아다님.

robot/guide_mode.py가 센서 값을 넣어 주고 명령을 보냄.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


# ---------------------------------------------------------------- LiDAR 보조 함수
def robot_ahead(pts: np.ndarray, see: float = 0.40, fov: float = math.radians(30), w_min: float = 0.06,
                w_max: float = 0.16, jump: float = 0.05) -> tuple[float, float] | None:
    """앞에 다른 Pinky: 길 위에 독립적으로 서 있는 작은 물체의 (거리, 방위), 없으면 None.
    LiDAR는 Pinky를 짧은 조각 하나 (~11 cm 몸체)로 보며, 양쪽에 더 먼 점으로의 뚜렷한 단차가 있음
    (그 뒤로 복도 벽이나 빈 바닥이 이어짐). 복도를 가로지르는 벽이나 모서리는 옆벽과 이어져
    있고 (단차 없음, w_max보다 넓음), 사람의 두 신발은 나란한 두 조각임."""
    if len(pts) == 0:
        return None
    r = np.hypot(pts[:, 0], pts[:, 1])
    a = np.arctan2(pts[:, 1], pts[:, 0])
    sel = (pts[:, 0] > 0.03) & (r < see + 0.25) & (np.abs(a) < fov + math.radians(20))  # see에서 자르지 않은 전체 조각
    if sel.sum() < 3:
        return None
    order = np.argsort(a[sel])
    q, qa, qr = pts[sel][order], a[sel][order], r[sel][order]
    cuts = np.where(np.hypot(*np.diff(q, axis=0).T) > 0.03)[0] + 1
    pieces = np.split(np.arange(len(q)), cuts)

    def beyond(ang: float) -> float:  # 조각 바로 바깥의 가장 가까운 거리 (see 미만만이 아니라 모든 거리)
        m = np.abs(a - ang) < math.radians(1.0)
        return float(r[m].min()) if m.any() else math.inf
    found = []
    for idx in pieces:
        if len(idx) < 3:
            continue
        width = float(np.hypot(*(q[idx[-1]] - q[idx[0]])))
        if not (w_min <= width <= w_max):
            continue
        d = float(qr[idx].min())
        lo, hi = qa[idx[0]], qa[idx[-1]]
        if d >= see or d < 0.15 or abs((lo + hi) / 2) > fov:
            continue  # 15 cm보다 가까움: Pinky 옆의 벽 모서리 (이렇게 가까운 로봇은 일반 YIELD로 처리)
        # 양쪽에 더 먼 점으로의 단차: 한쪽은 jump 이상, 다른 쪽은 최소 2 cm (18 cm 복도에서 한쪽으로
        # 치우친 Pinky는 그쪽 벽까지 ~1.5 cm만 남김)
        steps = sorted((beyond(lo - math.radians(2.5)) - d, beyond(hi + math.radians(2.5)) - d))
        if steps[0] > 0.02 and steps[1] > jump:
            found.append((d, float((lo + hi) / 2), width))
    if not found:
        return None
    for d, b, _ in found:  # 나란히 붙어 있는 두 조각 = 사람의 두 발
        if any(abs(d2 - d) < 0.08 and 0.0 < abs(b2 - b) * d < 0.25 for d2, b2, _ in found if b2 != b):
            return None
    d, b, _ = min(found)
    return d, b


def scan_points(ranges, angle_min: float, angle_inc: float, range_min: float, range_max: float,
                tf: tuple[float, float, float] = (0.0, 0.0, 0.0), self_radius: float = 0.0) -> np.ndarray:
    """LaserScan -> base_footprint 기준 Nx2 점 (x 앞, y 왼쪽). tf = 로봇 위 LiDAR 자세 (x, y, yaw).
    로봇 중심에서 self_radius보다 가까운 점은 Pinky 자신의 몸 (기둥, 케이블)이므로 버림."""
    r = np.asarray(ranges, dtype=np.float64)
    a = angle_min + np.arange(len(r)) * angle_inc + tf[2]
    ok = np.isfinite(r) & (r > max(range_min, 0.03)) & (r < range_max)
    r, a = r[ok], a[ok]
    pts = np.stack([tf[0] + r * np.cos(a), tf[1] + r * np.sin(a)], axis=1)
    if self_radius > 0:
        pts = pts[np.hypot(pts[:, 0], pts[:, 1]) > self_radius]
    return pts


def free_distance(pts: np.ndarray, theta: float, half_width: float, max_dist: float) -> float:
    """로봇 (폭 2*half_width의 통로)이 theta 방향으로 점에 부딪히기 전까지 갈 수 있는 거리."""
    if len(pts) == 0:
        return max_dist
    c, s = math.cos(theta), math.sin(theta)
    along = pts[:, 0] * c + pts[:, 1] * s
    side = -pts[:, 0] * s + pts[:, 1] * c
    hit = along[(along > 0) & (np.abs(side) < half_width)]
    return float(min(max_dist, hit.min())) if len(hit) else max_dist


def rear_free(pts: np.ndarray, half_width: float, max_dist: float = 1.0) -> float:
    return free_distance(pts, math.pi, half_width, max_dist)


def seg_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def join_corners(segs, reach: float = 0.12):
    """방 모서리에서 만나는 두 테이프 조각 (L자)은 따로 보이며, 그 끝은 모서리 앞에서 끊김.
    둘 다 모서리까지 늘려서 Pinky가 틈으로 대각선으로 빠져나가지 못하게 함.
    reach는 2026-10-29까지 0.25였음: 그때 18 cm 떨어진 옆 방 박스의 변이 이 박스의 모서리로
    당겨져 두 박스 사이의 옆 복도를 막음 (Pinky가 작은 복도로 들어가지 않았음)."""
    segs = [list(sg) for sg in segs]
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            x1, y1, x2, y2 = segs[i]
            x3, y3, x4, y4 = segs[j]
            d1x, d1y, d2x, d2y = x2 - x1, y2 - y1, x4 - x3, y4 - y3
            den = d1x * d2y - d1y * d2x
            n1, n2 = math.hypot(d1x, d1y), math.hypot(d2x, d2y)
            if n1 < 1e-3 or n2 < 1e-3 or abs(den) < 0.5 * n1 * n2:  # 30° 미만으로 벌어짐: 모서리가 아님
                continue
            t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den
            px, py = x1 + t * d1x, y1 + t * d1y
            # 양 끝이 모서리 근처 (또는 모서리가 이미 선분 위: 한 조각이 이미 닿아 있음)
            if any(seg_dist(px, py, *sg) > reach for sg in (segs[i], segs[j])):
                continue
            for sg in (segs[i], segs[j]):
                if seg_dist(px, py, *sg) > 1e-6:
                    if math.hypot(sg[0] - px, sg[1] - py) < math.hypot(sg[2] - px, sg[3] - py):
                        sg[0], sg[1] = px, py
                    else:
                        sg[2], sg[3] = px, py
    return [tuple(sg) for sg in segs]


def wall_points(walls, rx: float, ry: float, ryaw: float, near: float = 1.2, step: float = 0.02) -> np.ndarray:
    """바닥 선 선분 (map 좌표계) -> base_footprint 기준 점, 추가 LiDAR 점처럼 사용."""
    out = []
    c, s = math.cos(ryaw), math.sin(ryaw)
    for x1, y1, x2, y2 in walls:
        if seg_dist(rx, ry, x1, y1, x2, y2) > near:
            continue
        n = max(2, int(math.hypot(x2 - x1, y2 - y1) / step) + 1)
        xs, ys = np.linspace(x1, x2, n) - rx, np.linspace(y1, y2, n) - ry
        out.append(np.stack([c * xs + s * ys, -s * xs + c * ys], axis=1))
    return np.vstack(out) if out else np.zeros((0, 2))


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass
class Params:
    max_lin: float = 0.10          # m/s; 테스트 필드는 ~1.2 x 0.55 m
    max_ang: float = 0.8           # rad/s
    half_width: float = 0.06       # 로봇 폭의 절반: 병원 복도 폭은 ~18 cm뿐
    corridor: bool = True          # 지도 목표점 대신 복도 따라가기 (벽과 테이프로 된 좁은 복도)
    corr_half: float = 0.06        # 복도 모드: Pinky 폭의 띠가 비어 있으면 열린 방향 ...
    corr_open: float = 0.22        # ... 이 거리까지
    corr_mid: float = 0.09         # 복도 폭의 절반: 반대쪽이 열려 있을 때 벽과 유지하는 거리
    corr_commit: float = 2.5       # s: 선택한 갈래를 이 시간 동안 유지 (교차로 통과)
    wiggle_flips: int = 4          # 8 s 안에 제자리에서 좌/우 전환이 이만큼 = 흔들림: 다른 길 선택
    uturn_min: float = 5.5         # 복도 모드, ESCAPE (사람 / 다른 Pinky / 장애물): ~150° 이상 회전 = 온 길로 ...
    uturn_max: float = 8.0         # ... 되돌아가서 다른 길을 찾음
    ir_steer: float = 0.5          # rad/s: 측면 IR 센서가 테이프 위 (복도 가장자리) -> 반대쪽으로 조향, 정지 없음
    ir_m_hold: float = 1.0         # s: 가운데 IR 센서만 이 시간 동안 테이프 위 (조향이 효과 없음) -> LINE
    stop_dist: float = 0.11        # 경로 위 장애물이 이만큼 가까움 (로봇 중심 기준 = 앞코 ~5 cm) -> YIELD.
                                   # 0.15는 18 cm 복도에 너무 멀었음: L자 모서리에서 Pinky가 끝 벽에서
                                   # ~10 cm 이내로 가야 옆 복도가 열림
    slow_dist: float = 0.35        # 감속 시작
    clear_need: float = 0.20       # 이만큼 비어 있으면 사용할 수 있는 방향
    look_ahead: float = 1.0
    yield_wait: float = 1.0        # s: 후진 전에 (빨간색으로) 서 있는 시간, 장애물이 비켜갈 수도 있으므로
    approach_speed: float = 0.03   # m/s: 장애물이 이보다 빠르게 다가옴 -> BACKUP
    too_close: float = 0.13        # m: 이보다 가까움 -> BACKUP
    backup_speed: float = 0.06
    backup_time: float = 1.5
    robot_stop: float = 0.30       # m: 다른 Pinky (로봇 크기의 독립 물체)가 앞쪽 이 거리 이내 -> 양보:
                                   # 빨간색, 정지, 후진, 다른 길 선택 (가까이 다가가지 않음)
    rear_clear: float = 0.15
    escape_min: float = 1.5        # s: 회피할 때 항상 최소 ~40° 회전
    escape_max: float = 5.0
    greet_dist: float = 0.16       # 사람이 이보다 가까움 (로봇 중심 기준 m = Pinky 앞코에서 ~10 cm) -> GREET
    approach_max: float = 10.0     # s: greet_dist에 끝내 도달하지 못한 APPROACH -> 사람 아님, 8 s 동안 무시
    approach_dist: float = 0.35    # 앞의 사람이 이보다 가까움: 천천히 다가감 (사람에게는 YIELD 없음)
    approach_speed_lin: float = 0.03
    greet_step: float = 0.05       # m: 사람을 인식한 뒤 이만큼 천천히 더 다가감
    greet_step_min: float = 0.10   # ... 단 이보다 가까이는 가지 않음 (로봇 중심 기준 전방 거리)
    person_half_fov: float = math.radians(25)
    person_greet_fov: float = math.radians(15)  # 거의 정면에 있는 사람에게만 인사
    greet_hold: float = 5.0        # 최소 이 시간 동안 정지 (인사는 ~4.5 s)
    greet_cooldown: float = 20.0   # 이 시간 안에는 다시 인사하지 않음 (같은 사람이 다시 보임)
    person_gone: float = 3.0       # 이 시간 동안 사람이 안 보임 = 떠났음
    person_wait_max: float = 12.0  # 사람이 아무 요청 없이 이 시간 동안 앞에 서 있음 -> 돌아서 계속 탐색
    look_around: bool = False      # 각 순찰 지점에서 LOOK; 꺼짐: 복도에서는 사람이 벽 쪽이 아니라 앞에 있음
    look_speed: float = 0.5        # rad/s, LOOK: 사람을 찾기 위해 제자리에서 한 바퀴 회전
    look_time: float = 12.6        # s (2*pi / look_speed)
    line_stop: float = 0.11        # 로봇 중심 기준 m (= 앞코가 테이프에서 ~5 cm): LINE (되돌아감).
                                   # 카메라는 15 cm부터만 바닥을 보므로, 마지막 몇 cm는 지도에 저장된
                                   # 선을 기준으로 주행
    line_blind_stop: float = 0.17  # 아직 지도 위치 없음 (선 저장 불가): 카메라가 이 거리에서 보는 즉시 정지
    line_backup_time: float = 1.0  # s: 선을 본 뒤 backup_speed로 후진하는 시간
    turn_time: float = 6.5         # s: 0.6*max_ang 기준 = 최대 ~180°
    turn_min: float = 2.5          # s (~70°): 이후 앞길이 비면 바로 회전 중지 (복도)


@dataclass
class Person:
    bearing: float          # rad, + = 왼쪽
    dist: float | None      # LiDAR 기준 m, 그 방향에서 LiDAR가 아무것도 못 봤으면 None
    height_frac: float      # 박스 높이 / 영상 높이 (가까운 사람은 영상을 가득 채움)


@dataclass
class Command:
    lin: float = 0.0
    ang: float = 0.0
    say: bool = False       # 지금 인사 재생


@dataclass
class GuideBrain:
    p: Params = field(default_factory=Params)
    state: str = "EXPLORE"
    explored: bool = False
    t_state: float = 0.0
    last_greet: float = -1e9
    person_seen: float = -1e9
    person_since: float = 0.0
    ignore_person_until: float = -1e9
    hist: list = field(default_factory=list)      # 양보하는 동안의 (t, 전방 거리)
    escape_dir: float = 1.0
    escape_t: float = -1e9
    visits: dict = field(default_factory=dict)    # 복도 모드: 10 cm 셀마다 머문 시간(초) (map 좌표계)
    branch: float | None = None                   # 복도 모드: 선택한 방향 (map 좌표계 yaw)
    branch_t: float = -1e9
    last_t: float = 0.0
    ir_side: tuple = ("", -1e9)                   # 복도 모드: 마지막으로 테이프 위에 있던 측면 IR 센서와 그 시각
    ir_m_t: float | None = None                   # 가운데 IR 센서만 테이프 위에 있기 시작한 시각
    clear_t: float | None = None                  # YIELD: 앞길이 비기 시작한 시각
    turn_sign: float = 0.0                        # 복도 모드: 마지막 회전 방향 (흔들림 검사)
    flips: list = field(default_factory=list)     # 최근 회전 방향 전환의 (t, x, y)
    line_t: float = -1e9                          # 마지막 LINE (앞에 테이프)
    ir_cmd: bool = False                          # 이번 스텝의 명령은 IR 조향
    wiggles: int = 0                              # 흔들림을 끊은 횟수 (guide_mode가 로그 출력)
    wiggle_t: float = -1e9
    branch_hold_until: float = -1e9               # 측면 IR 감지는 이 시각 전까지 갈래를 버리지 않음
    yield_robot: bool = False                     # 다른 Pinky 때문의 YIELD: 기다리지 않고 항상 후진
    robots: int = 0                               # 다른 Pinky에게 양보한 횟수 (guide_mode가 로그 출력)
    robot_seen: tuple = (0.0, 0.0)                # 그 Pinky의 (거리, 방위)

    def _go(self, s: str, now: float):
        if s == "YIELD":
            self.clear_t = None
        self.state, self.t_state = s, now

    def person_ahead(self, people: list[Person], front: float = 0.0) -> bool:
        """Pinky 앞코에서 ~10 cm, 바로 앞에 있는 사람. 엄격함 (2026-10-29: 박스와 벽에 인사했음):
        LiDAR가 박스 방위에서 greet_dist보다 가깝게 측정해야 하고, 그 물체가 Pinky의
        경로 (앞) 위에 있어야 함. 그래서 잘못된 박스 옆의 복도 벽은 해당되지 않음. LiDAR 거리 없음 = 인사 없음."""
        for q in people:
            if abs(q.bearing) > self.p.person_greet_fov or q.dist is None:
                continue
            if q.dist < self.p.greet_dist and front < self.p.greet_dist + 0.03:
                return True
        return False

    def person_near(self, people: list[Person]) -> float | None:
        """approach_dist (LiDAR 거리) 이내 앞에 있는 가장 가까운 사람의 방위, 없으면 None."""
        near = [q for q in people if abs(q.bearing) < self.p.person_half_fov and q.dist is not None
                and q.dist < self.p.approach_dist]
        return min(near, key=lambda q: q.dist).bearing if near else None

    def look(self, now: float):
        """사람을 찾기 위해 제자리에서 한 바퀴 회전 (카메라 시야는 58°뿐)."""
        if self.p.look_around and self.state in ("EXPLORE", "PATROL"):
            self._go("LOOK", now)

    def step(self, now: float, pts: np.ndarray, people: list[Person], goal_bearing: float | None,
             line: float | None = None, walls: np.ndarray | None = None, goal_dist: float | None = None,
             pose: tuple[float, float, float] | None = None, ir: dict | None = None) -> Command:
        self.ir_cmd = False
        cmd = self._step(now, pts, people, goal_bearing, line, walls, goal_dist, pose, ir)
        if self.p.corridor and pose is not None:
            self._check_wiggle(now, cmd, pose)
        return cmd

    def _check_wiggle(self, now: float, cmd: Command, pose):
        """같은 자리에서 왼쪽, 오른쪽, 왼쪽, 오른쪽 (2026-10-29 테스트, LINE 후: 앞에 테이프, 옆의
        열린 길이 번갈아 양쪽 다 열려 보였고, 측면 IR 감지가 선택을 뒤집었음). 8 s와 15 cm 안에서
        회전 방향이 wiggle_flips번 바뀌면: 흔들린 방향들을 방문한 것으로 처리하고, 갈래를 다시
        선택하며 (다른 길), 그 선택을 더 오래 유지함."""
        if self.state not in ("EXPLORE", "PATROL") or abs(cmd.ang) < 0.25 or cmd.lin > 0.01 or self.ir_cmd:
            return  # 제자리 회전만 셈; 테이프 복도에서 측면 IR에 의한 좌/우 조향은 정상
        sign = 1.0 if cmd.ang > 0 else -1.0
        if sign == self.turn_sign:
            return
        self.turn_sign = sign
        self.flips = [(t, x, y) for t, x, y in self.flips if now - t < 8.0
                      and math.hypot(pose[0] - x, pose[1] - y) < 0.15] + [(now, pose[0], pose[1])]
        if len(self.flips) >= self.p.wiggle_flips:
            for turn in (-0.7, 0.0, 0.7):
                self.avoid_ahead(pose, 200.0, turn)
            self.flips = []
            self.branch = None
            self.wiggles += 1
            self.wiggle_t = now
            self.branch_hold_until = now + 4.0  # 측면 IR 결과와 관계없이 다음 선택을 4 s 유지

    def _step(self, now: float, pts: np.ndarray, people: list[Person], goal_bearing: float | None,
              line: float | None = None, walls: np.ndarray | None = None, goal_dist: float | None = None,
              pose: tuple[float, float, float] | None = None, ir: dict | None = None) -> Command:
        """ir (복도 모드): 어떤 바닥 IR 센서가 테이프 위에 있는지, {"L": bool, "M": bool, "R": bool}."""
        """line: distance (m) of a black floor line in the path, None if none.
        walls: points (base_footprint) of lines seen before; they block the way like obstacles,
        but nothing physical is there, so meeting one means "turn back", not "give way"."""
        p = self.p
        if pose is not None:  # Pinky가 있었던 곳을 기억: 복도 모드는 최근에 보지 않은 곳을 선호
            k = (int(math.floor(pose[0] / 0.1)), int(math.floor(pose[1] / 0.1)))
            self.visits[k] = self.visits.get(k, 0.0) + min(0.5, max(0.0, now - self.last_t))
        self.last_t = now
        self.pose = pose
        front = free_distance(pts, 0.0, p.half_width, p.look_ahead)
        allpts = pts if walls is None or len(walls) == 0 else np.vstack([pts, walls])
        person = self.person_ahead(people, front) and now >= self.ignore_person_until
        if not person and self.state == "APPROACH" and now - self.person_seen < 1.5 and front < p.greet_dist \
                and now >= self.ignore_person_until:
            person = True  # 방금 본 사람에게 다가감: 이렇게 가까우면 카메라에는 신발만 보임
        if person:
            self.person_seen = now

        # ---- Task 01: 앞에 있는 사람이 항상 우선
        if person and self.state not in ("GREET", "WAIT"):
            self.person_since = now
            if now - self.last_greet > p.greet_cooldown:
                self.last_greet = now
                self._go("GREET", now)
                return Command(say=True)
            self._go("WAIT", now)                 # 방금 인사함: 그냥 서 있고 반복하지 않음
            return Command()
        # ---- 조금 더 앞에 있는 사람: 양보하지 않고 천천히 다가감
        near = self.person_near(people) if now >= self.ignore_person_until else None
        if near is not None and self.state == "APPROACH" and now - self.t_state > p.approach_max:
            self.ignore_person_until = now + 8.0  # 끝내 가까워지지 않음: 사람 아님 (사진, 박스): 계속 주행
            self._go("EXPLORE", now)
            near = None
        if near is not None and self.state in ("EXPLORE", "PATROL", "LOOK", "YIELD", "APPROACH") \
                and now - self.last_greet > p.greet_cooldown:
            self.person_seen = now
            if self.state != "APPROACH":
                self._go("APPROACH", now)
            if front < p.greet_step_min:      # 사람보다 더 가까운 무언가: LiDAR 거리를 기다림
                return Command()
            return Command(lin=p.approach_speed_lin, ang=max(-p.max_ang, min(p.max_ang, 1.5 * near)))
        if self.state == "APPROACH":
            if now - self.person_seen < p.person_gone:
                return Command()              # 잠깐 놓침: 서 있음
            self._go("EXPLORE", now)
        if self.state in ("GREET", "WAIT"):
            if self.state == "GREET" and now - self.t_state < p.greet_hold:
                # greet_step만큼 천천히 더 다가간 뒤 서 있음
                if now - self.t_state < p.greet_step / p.approach_speed_lin and front > p.greet_step_min:
                    return Command(lin=p.approach_speed_lin)
                return Command()
            if now - self.person_seen > p.person_gone:
                self._go("EXPLORE", now)          # 떠났음
            elif person and now - self.person_since > p.person_wait_max:
                self.ignore_person_until = now + 8.0  # 계속 서 있음: 돌아서 지나감
                self._start_escape(now, allpts)
            else:
                if self.state == "GREET":
                    self._go("WAIT", now)
                return Command()

        # ---- Task 02: 앞에 다른 Pinky -> 일찍 양보 (빨간색), 후진, 다른 길 선택
        if self.state in ("EXPLORE", "PATROL") and now - self.person_seen > 2.0:
            rb = robot_ahead(pts, see=p.robot_stop)
            if rb is not None:
                self.robots += 1
                self.robot_seen = rb
                self.yield_robot = True
                self.hist = [(now, front)]
                if pose is not None:
                    self.avoid_ahead(pose, 120.0, rb[1])  # 그 길: 당분간 다시 가지 않음
                self.branch = None
                self._go("YIELD", now)
                return Command()
        # ---- 그 밖의 장애물 -> 정지, 후진, 다른 길 찾기
        if self.state == "YIELD" and self.yield_robot:
            if now - self.t_state < p.yield_wait:
                return Command()
            self.yield_robot = False
            if rear_free(pts, p.half_width) > p.rear_clear:
                self._go("BACKUP", now)
                return Command(lin=-p.backup_speed)
            self._start_escape(now, allpts)
        if self.state == "YIELD":
            self.hist = [(t, d) for t, d in self.hist if now - t < 1.0] + [(now, front)]
            t0, d0 = self.hist[0]
            closing = (d0 - front) / (now - t0) if now - t0 > 0.4 else 0.0
            # YIELD에 들어갈 때보다 나올 때 조금 더 넓은 복도: 경계에서 깜빡임 방지
            if free_distance(pts, 0.0, p.half_width + 0.02, p.look_ahead) <= p.clear_need:
                self.clear_t = None
            elif self.clear_t is None:
                self.clear_t = now
            # 0.5 s 동안 비어 있음: ~8 cm 앞의 장애물은 자기 몸 필터 경계에 걸려 스캔에서
            # 깜빡임 (2026-10-29: 1초에 4번 YIELD <-> EXPLORE)
            if self.clear_t is not None and now - self.clear_t > 0.5:
                self._go("EXPLORE", now)          # 비켜갔음 (다른 Pinky가 지나감)
            elif closing > p.approach_speed or now - self.t_state > p.yield_wait:
                if rear_free(pts, p.half_width) > p.rear_clear:
                    self._go("BACKUP", now)
                    return Command(lin=-p.backup_speed)
                self._start_escape(now, allpts)      # 뒤에 공간 없음: 회전만
            else:
                return Command()
        if self.state == "BACKUP":
            if now - self.t_state < p.backup_time and rear_free(pts, p.half_width) > p.rear_clear:
                return Command(lin=-p.backup_speed)
            self._start_escape(now, allpts)
        if self.state == "ESCAPE":
            turned = now - self.t_state
            emin, emax = (p.uturn_min, p.uturn_max) if p.corridor else (p.escape_min, p.escape_max)
            if (turned > emin and free_distance(allpts, 0.0, p.half_width, p.look_ahead) > p.clear_need * 1.5) \
                    or turned > emax:
                self._go("EXPLORE", now)
            else:
                return Command(ang=0.6 * p.max_ang * self.escape_dir)
        if self.state == "LOOK":
            if now - self.t_state < p.look_time:
                return Command(ang=p.look_speed)
            self._go("EXPLORE", now)
        if self.state == "LINE":
            if now - self.t_state < p.line_backup_time and rear_free(pts, p.half_width) > p.rear_clear:
                return Command(lin=-p.backup_speed)
            if p.corridor:
                # 큰 회전 없음 (2026-10-28): 아래 복도 선택이 다음 열린 길로 회전하고, 테이프는 지도에
                # 저장되며 앞쪽은 방문한 것으로 처리; 진짜 막다른 길이면 None -> U턴 (ESCAPE)
                self.branch = None  # 선택했던 갈래가 테이프로 이어짐: 다시 선택
                if self.pose is not None:
                    for turn in (-0.6, 0.6):  # 카메라가 테이프의 일부만 봄: 양 끝은 열려 보임
                        self.avoid_ahead(self.pose, 60.0, turn)
                self._go("EXPLORE", now)
            else:
                self._start_turn(now, allpts)
        if self.state == "TURN":
            turned = now - self.t_state
            if turned < p.turn_time and not (turned > p.turn_min and free_distance(
                    allpts, 0.0, p.half_width, p.look_ahead) > p.clear_need * 1.5):
                return Command(ang=0.6 * p.max_ang * self.escape_dir)
            self._go("EXPLORE", now)

        # ---- EXPLORE / PATROL
        if not (ir and ir.get("M") and not ir.get("L") and not ir.get("R")):
            self.ir_m_t = None
        if p.corridor and ir:
            # 바닥 IR 센서는 바퀴보다 4 cm 앞, 왼쪽 / 가운데 / 오른쪽. 18 cm 복도에서 테이프는
            # 대개 복도의 옆면: 측면 센서 하나가 테이프 위 = Pinky가 치우침, 조금 반대로 조향하고 계속 주행.
            # 길을 가로지르는 테이프 (양쪽, 또는 가운데만 ir_m_hold s 동안)만 "되돌아가기" (LINE).
            l, m, r = ir.get("L"), ir.get("M"), ir.get("R")
            if l != r:
                self.ir_side = ("L" if l else "R", now)
            if l and r:
                self._go("LINE", now)
                return Command()
            if l or r:
                if pose is not None:
                    # 측면 테이프 뒤의 방은 LiDAR에 열려 보임: 그쪽을 "방문함"으로 표시하고 그쪽의
                    # 선택된 갈래를 버림, 그렇지 않으면 복도 선택이 곧바로 다시 테이프로 조향함
                    side = 1.0 if l else -1.0
                    self.avoid_ahead(pose, 20.0, side * math.radians(60))
                    if self.branch is not None and wrap(self.branch - pose[2]) * side > math.radians(15) \
                            and now > self.branch_hold_until:
                        self.branch = None
                self.state = "PATROL" if self.explored else "EXPLORE"
                self.ir_cmd = True
                return Command(lin=0.0 if m else 0.02, ang=-p.ir_steer if l else p.ir_steer)
            if m:
                # 가운데 센서만: 대개 Pinky가 측면 테이프를 작은 각도로 넘었고 측면 센서는 이미
                # 벗어남. 마지막으로 본 쪽의 반대로 (또는 더 열린 쪽으로) 제자리 회전; 그래도 ir_m_hold s 동안
                # 효과가 없을 때만 테이프가 정말 길을 가로지르는 것.
                if self.ir_m_t is None:
                    self.ir_m_t = now
                if now - self.ir_m_t > p.ir_m_hold:
                    self.ir_m_t = None
                    self._go("LINE", now)
                    return Command()
                side, t = self.ir_side
                if now - t < 2.0:
                    away = -1.0 if side == "L" else 1.0
                else:
                    away = 1.0 if free_distance(allpts, math.radians(45), p.half_width, 0.5) >= \
                        free_distance(allpts, math.radians(-45), p.half_width, 0.5) else -1.0
                self.state = "PATROL" if self.explored else "EXPLORE"
                self.ir_cmd = True
                return Command(ang=away * p.ir_steer)
        if p.corridor:
            # 옆 복도로 제자리 회전할 때는 앞에 빈 공간이 필요 없음 (18 cm 복도에서는 회전 중
            # 벽 모서리가 항상 "앞"에 있음): 이때는 YIELD / LINE 없음
            theta = self.corridor_heading(now, allpts, pose if pose is not None else (0.0, 0.0, 0.0))
            if theta is not None and abs(theta) > math.radians(20):  # 18 cm: 대각선 주행 금지
                self.state = "PATROL" if self.explored else "EXPLORE"
                return Command(ang=max(-p.max_ang, min(p.max_ang, 1.5 * theta)))
        if front < p.stop_dist:
            self.hist = [(now, front)]
            self._go("YIELD", now)
            return Command()
        no_walls = walls is None or len(walls) == 0
        # 복도 모드: Pinky 옆면에서 1-2 cm 옆으로 복도를 따라 붙은 테이프는 "앞"이 아님
        wall_front = p.look_ahead if no_walls else free_distance(walls, 0.0, 0.035 if p.corridor else p.half_width,
                                                                 p.look_ahead)
        if (line is not None and line < p.line_stop) or wall_front < p.line_stop \
                or (no_walls and line is not None and line < p.line_blind_stop):
            if p.corridor and now - self.line_t < 1.5:
                # LINE 직후 다시 LINE: 후진할 공간이 없고 (뒤가 벽) 복도 선택이 여전히
                # 테이프를 가리킴 -> LINE에 계속 머무르지 않고 회전 (시뮬레이션 2026-10-29)
                self._start_escape(now, allpts)
                return Command(ang=0.6 * p.max_ang * self.escape_dir)
            self.line_t = now
            self._go("LINE", now)                 # 앞에 막힌 방: 되돌아감
            return Command()
        if not p.corridor:
            theta, _ = pick_heading(pts, 0.0 if goal_bearing is None else goal_bearing, p,
                                    None if no_walls else walls, goal_dist)
        if theta is None:
            self._start_escape(now, allpts)
            return Command(ang=0.6 * p.max_ang * self.escape_dir)
        self.state = "PATROL" if self.explored else "EXPLORE"
        ang = max(-p.max_ang, min(p.max_ang, 1.5 * theta))
        # 실제 장애물 (stop_dist에서 정지)과 저장된 선 (line_stop에서 정지) 앞에서 감속
        speed = min(1.0, max(0.0, (front - p.stop_dist) / (p.slow_dist - p.stop_dist)),
                    max(0.15, (wall_front - p.line_stop) / (p.slow_dist - p.line_stop)))
        lin = 0.0 if abs(theta) > math.radians(45) else p.max_lin * speed * math.cos(theta)
        if p.corridor and abs(theta) <= math.radians(45) and front > p.stop_dist:
            lin = max(lin, 0.015)  # L자 모서리까지 마지막 몇 cm를 천천히 접근: 옆 복도는 거기서만 열림
        return Command(lin=lin, ang=ang)

    def avoid_ahead(self, pose, weight: float = 120.0, turn: float = 0.0):
        """앞에 테이프 (LINE): Pinky 앞 30 cm를 2분 동안 방문한 것으로 처리해서, 복도 선택이
        같은 테이프로 다시 이끌지 않게 함 (테이프 뒤의 방은 LiDAR에 열려 보임).
        turn: 그쪽 방향에도 동일 (rad, 왼쪽 +): 측면 IR 센서 아래의 테이프."""
        x, y, yaw = pose
        yaw += turn
        c, s = math.cos(yaw), math.sin(yaw)
        for d in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
            for side in (-0.05, 0.0, 0.05):
                k = (int(math.floor((x + c * d - s * side) / 0.1)), int(math.floor((y + s * d + c * side) / 0.1)))
                self.visits[k] = self.visits.get(k, 0.0) + weight

    def corridor_heading(self, now: float, pts: np.ndarray, pose) -> float | None:
        """좁은 복도 (18 cm, 옆면은 벽 또는 테이프): 복도를 따라 가운데로 주행.
        열린 방향 (10 cm 띠가 corr_open까지 비어 있음)이 그룹을 이룸: 그룹 하나 = 복도, 두 개 이상 =
        교차로. 교차로에서는 앞 30 cm를 가장 적게 방문한 갈래를 택하고 (같으면 직진),
        corr_commit s 동안 유지. 열린 방향 없음 = 막다른 길: None (Pinky가 돌아섬).
        pts: LiDAR 점 + 저장된 테이프 선, 그래서 테이프도 옆벽 역할을 함."""
        p = self.p
        degs = list(range(-135, 136, 5))  # ±90보다 넓게: 옆 복도로 회전하는 동안에도 시야에 남음
        free = [free_distance(pts, math.radians(d), p.corr_half, 0.6) for d in degs]
        groups, cur = [], []
        for d, f in zip(degs, free):
            if f >= p.corr_open:
                cur.append((d, f))
            elif cur:
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        # 옆 복도는 Pinky가 그 앞에 섰을 때만 선택 (~90°에서 열림): 교차로 전부터 40-60°로
        # 보이는 것을 택하면 벽 모서리를 가로지르게 됨
        x, y, yaw = pose
        committed = self.branch is not None and (now - self.branch_t < p.corr_commit or now < self.branch_hold_until)
        groups = [g for g in groups if min(abs(d) for d, _ in g) <= 30 or max(abs(d) for d, _ in g) >= 85
                  or (committed and any(abs(wrap(yaw + math.radians(d) - self.branch)) < math.radians(35)
                                        for d, _ in g))]
        if not groups:
            # corr_open 거리까지 열린 곳 없음: 바로 앞이 복도 끝이거나 L자 모서리. 끝까지 계속 굴러감
            # (옆 갈래는 Pinky가 가로 복도 안에 들어가야 열림); 진짜 막다른 길 -> None
            fwd = [d for d, f in zip(degs, free) if abs(d) <= 10 and f >= p.stop_dist + 0.005]
            if fwd:
                return math.radians(min(fwd, key=abs))  # 직진 (벽 모서리로 대각선 진입 금지)
            self.branch = None
            return None
        cands = []
        for g in groups:
            fmax = max(f for _, f in g)
            if min(abs(d) for d, _ in g) > 30:   # 옆 복도: 직각으로 회전해 진입
                cands.append(math.radians(max((d for d, _ in g), key=abs)))
            else:
                top = [d for d, f in g if f >= fmax - 0.02]
                cands.append(math.radians(top[len(top) // 2]))  # 가장 긴 빈 방향들의 가운데
        best, best_s = None, 1e9
        for ang in cands:
            world = yaw + ang
            tx, ty = x + 0.3 * math.cos(world), y + 0.3 * math.sin(world)
            v = sum(self.visits.get((int(math.floor(tx / 0.1)) + i, int(math.floor(ty / 0.1)) + j), 0.0)
                    for i in (-1, 0, 1) for j in (-1, 0, 1))
            sc = v + 3.0 * abs(ang) / math.pi
            if committed and abs(wrap(world - self.branch)) < math.radians(35):
                sc -= 1e6  # 이 교차로에서 선택한 갈래를 유지
            if sc < best_s:
                best, best_s = ang, sc
        kept = committed and abs(wrap(yaw + best - self.branch)) < math.radians(35)
        if committed and not kept:
            return wrap(self.branch - yaw)  # 회전 중 잠깐 시야에서 사라짐: 계속 그쪽으로 회전
        if not kept:
            self.branch, self.branch_t = wrap(yaw + best), now
        # 가운데 유지: Pinky 옆의 가장 가까운 좌우 점을 비교
        side = pts[(pts[:, 0] > -0.05) & (pts[:, 0] < 0.12) & (np.abs(pts[:, 1]) < 0.15)] if len(pts) else pts
        left = side[side[:, 1] > 0][:, 1].min() if len(side) and (side[:, 1] > 0).any() else None
        right = -side[side[:, 1] < 0][:, 1].max() if len(side) and (side[:, 1] < 0).any() else None
        if abs(best) < math.radians(30):
            if left is not None and right is not None:
                best += math.atan2((left - right) / 2, 0.15)
            elif left is not None and left < p.corr_mid + 0.04:   # 교차로: 오른쪽이 열려 있음
                best += math.atan2(left - p.corr_mid, 0.15)
            elif right is not None and right < p.corr_mid + 0.04:
                best -= math.atan2(right - p.corr_mid, 0.15)
        return best

    def _start_turn(self, now: float, pts: np.ndarray):
        self._start_escape(now, pts)
        self._go("TURN", now)

    def _start_escape(self, now: float, pts: np.ndarray):
        left = max(free_distance(pts, math.radians(a), self.p.half_width, 1.0) for a in (60, 90, 120))
        right = max(free_distance(pts, math.radians(-a), self.p.half_width, 1.0) for a in (60, 90, 120))
        if now - self.escape_t > 15.0 or abs(left - right) > 0.10:  # 아니면 같은 방향으로 계속 회전: 좌우로 흔들지 않음
            self.escape_dir = 1.0 if left >= right else -1.0
        self.escape_t = now
        if self.p.corridor and getattr(self, "pose", None) is not None:
            self.avoid_ahead(self.pose, 60.0)  # 온 길로 되돌아감: 당분간 이 길을 다시 선택하지 않음
        self._go("ESCAPE", now)


def pick_heading(pts: np.ndarray, goal: float, p: Params, walls: np.ndarray | None = None,
                 goal_dist: float | None = None) -> tuple[float | None, float]:
    """±90° 안의 가장 좋은 빈 방향: 목표 방위에 가깝고, 너무 급하지 않고, 주행할 공간이 있음.
    walls: 저장된 바닥 선. Pinky는 선까지 line_stop 거리만큼 접근할 수 있으므로 (좁은 복도),
    선은 그보다 가까울 때만 방향을 막음.
    goal_dist: 목표 너머의 빈 공간은 세지 않으므로 30 cm 앞의 옆문이 긴 빈 복도보다
    우선됨 (그렇지 않으면 Pinky가 복도에서 절대 꺾지 않음)."""
    cap = p.look_ahead if goal_dist is None else max(p.clear_need + 0.05, min(p.look_ahead, goal_dist))
    best, best_s, best_f = None, -1e9, 0.0
    goal = wrap(goal)
    for deg in range(-90, 91, 10):
        th = math.radians(deg)
        f = free_distance(pts, th, p.half_width, p.look_ahead)
        if f < p.clear_need:
            continue
        if walls is not None:
            fw = free_distance(walls, th, p.half_width, p.look_ahead)
            if fw < p.line_stop - 0.02:
                continue
            f = min(f, fw)
        s = min(f, cap) / cap - 1.2 * abs(wrap(th - goal)) / math.pi - 0.3 * abs(th) / math.pi
        if s > best_s:
            best, best_s, best_f = th, s, f
    return best, best_f


# ---------------------------------------------------------------- 프런티어 탐색
class FrontierPlanner:
    """다음 목표 = SLAM 지도에서 알려진 빈 셀과 미지 셀 사이의 가장 가까운 경계."""

    def __init__(self, robot_radius: float = 0.08, min_cells: int = 4, reach: float = 0.15,
                 goal_timeout: float = 40.0, done_after: int = 10):
        self.robot_radius, self.min_cells, self.reach = robot_radius, min_cells, reach
        self.pass_radius = 0.05
        self.goal_timeout, self.done_after = goal_timeout, done_after
        self.goal: tuple[float, float] | None = None
        self.goal_t = 0.0
        self.blacklist: list[tuple[float, float]] = []
        self.empty_count = 0
        self.done = False
        self.patrol: tuple[float, float] | None = None
        self.patrol_reached = False  # 마지막 순찰 지점에 도착함 (시간 초과 아님)
        self.patrol_t = 0.0
        self.lines: list[tuple[float, float, float, float]] = []  # 발견한 검은 바닥 선 (map 좌표계)
        self.join_reach = 0.12  # 테이프 조각은 모서리에서 이 거리 이내일 때만 모서리로 연결 (join_corners 참고)
        self.walls: list[tuple[float, float, float, float]] = []  # 같은 선을 실제 벽까지 늘린 것

    def add_line(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """검은 바닥 선을 기억 (map 좌표계). 카메라는 한 번에 ~30 cm의 테이프를 보므로, 알려진 선을
        잇는 새 조각은 그 선을 늘림. 새 선일 때만 True 반환."""
        L = math.hypot(x2 - x1, y2 - y1)
        for i, (a1, b1, a2, b2) in enumerate(self.lines):
            K = math.hypot(a2 - a1, b2 - b1)
            if K < 1e-3 or L < 1e-3:
                continue
            ux, uy = (a2 - a1) / K, (b2 - b1) / K
            off = max(abs(-(x - a1) * uy + (y - b1) * ux) for x, y in ((x1, y1), (x2, y2)))  # 그 선으로부터의 거리
            cos = abs(ux * (x2 - x1) + uy * (y2 - y1)) / L
            t1, t2 = sorted(((x1 - a1) * ux + (y1 - b1) * uy, (x2 - a1) * ux + (y2 - b1) * uy))
            if off < 0.05 and cos > 0.95 and t1 < K + 0.10 and t2 > -0.10:  # 같은 테이프: 합침
                lo, hi = min(0.0, t1), max(K, t2)
                self.lines[i] = (a1 + ux * lo, b1 + uy * lo, a1 + ux * hi, b1 + uy * hi)
                self.walls = join_corners(self.lines, self.join_reach)
                return False
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if any(seg_dist(mx, my, *seg) < 0.06 for seg in self.lines):
            return False  # 같은 테이프를 약간 다른 각도에서 봄
        self.lines.append((x1, y1, x2, y2))
        self.walls = join_corners(self.lines, self.join_reach)
        return True

    def forget_near(self, x: float, y: float, r: float) -> int:
        """(x, y)에서 r보다 가까운 저장된 선을 지움: Pinky가 선에 갇혔으므로 일부는 잘못된 것
        (또는 회전 중 두 번 보임). 진짜 테이프는 카메라와 IR 센서가 다시 찾음."""
        keep = [seg for seg in self.lines if seg_dist(x, y, *seg) >= r]
        n = len(self.lines) - len(keep)
        if n:
            self.lines = keep
            self.walls = join_corners(self.lines, self.join_reach)
        return n

    def stretch(self, seg, grid: np.ndarray, res: float, ox: float, oy: float, max_ext: float = 0.15):
        """본 테이프 끝과 문틀 사이의 작은 틈을 메움: max_ext 이내에 점유된 지도 셀이 있으면
        선분을 그 셀까지 늘림. 짧게만 늘림: L자 테이프 모서리를 더 늘리면
        좁은 복도를 막음 (T6을 왼쪽으로 늘리면 협로가 막힘). 더 긴 테이프는
        카메라가 본 것으로 연결함 (add_line)."""
        x1, y1, x2, y2 = seg
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-3:
            return seg
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        h, w = grid.shape

        def walk(x, y, sx, sy):
            for k in range(int(max_ext / (res / 2))):
                px, py = x + sx * k * res / 2, y + sy * k * res / 2
                c, r = int((px - ox) / res), int((py - oy) / res)
                if not (0 <= r < h and 0 <= c < w) or grid[r, c] > 50:
                    return px, py
            return x, y  # 가까운 벽 없음: 테이프를 본 곳에 끝점을 그대로 둠
        a = walk(x1, y1, -ux, -uy)
        b = walk(x2, y2, ux, uy)
        return (a[0], a[1], b[0], b[1])

    def blocked(self, grid: np.ndarray, res: float, ox: float, oy: float) -> np.ndarray:
        """바닥 선을 벽으로 그려 넣은 지도 (3셀 두께, 대각선으로 새지 않게)."""
        g = grid.copy()
        self.walls = join_corners([self.stretch(s, grid, res, ox, oy) for s in self.lines], self.join_reach)
        for x1, y1, x2, y2 in self.walls:
            p1 = (int((x1 - ox) / res), int((y1 - oy) / res))
            p2 = (int((x2 - ox) / res), int((y2 - oy) / res))
            m = np.zeros(g.shape, np.uint8)
            cv2.line(m, p1, p2, 1, 3)
            g[m > 0] = 100
        return g

    @staticmethod
    def reachable(grid: np.ndarray, res: float, ox: float, oy: float, rx: float, ry: float) -> np.ndarray | None:
        """Pinky가 벽이나 바닥 선을 넘지 않고 갈 수 있는 빈 셀 (자기 복도)."""
        free = (grid == 0).astype(np.uint8)
        n, lab = cv2.connectedComponents(free, connectivity=4)
        c, r = int((rx - ox) / res), int((ry - oy) / res)
        h, w = grid.shape
        k = int(math.ceil(0.2 / res))
        best = None
        for rr in range(max(0, r - k), min(h, r + k + 1)):
            for cc in range(max(0, c - k), min(w, c + k + 1)):
                if lab[rr, cc] > 0:
                    d = (rr - r) ** 2 + (cc - c) ** 2
                    if best is None or d < best[0]:
                        best = (d, lab[rr, cc])
        return None if best is None else lab == best[1]

    @staticmethod
    def frontiers(grid: np.ndarray, res: float, robot_radius: float, min_cells: int) -> list[tuple[int, int, int]]:
        """[(row, col, size)] 프런티어 군집마다 목표 셀 하나. grid: -1 미지, 0 빈 곳, 100 점유."""
        free = (grid == 0).astype(np.uint8)
        unknown = (grid < 0).astype(np.uint8)
        occ = (grid > 50).astype(np.uint8)
        k3 = np.ones((3, 3), np.uint8)
        r = max(1, int(math.ceil(robot_radius / res)))
        near_occ = cv2.dilate(occ, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        front = free & cv2.dilate(unknown, k3) & (1 - near_occ)
        n, lab, stats, cents = cv2.connectedComponentsWithStats(front, connectivity=8)
        out = []
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < min_cells:
                continue
            rr, cc = np.nonzero(lab == i)
            j = np.argmin((cc - cents[i][0]) ** 2 + (rr - cents[i][1]) ** 2)
            out.append((int(rr[j]), int(cc[j]), int(stats[i, cv2.CC_STAT_AREA])))
        return out

    def patrol_goal(self, grid: np.ndarray, res: float, ox: float, oy: float, rx: float, ry: float, now: float,
                    rng=np.random.default_rng()):
        """지도가 완성된 뒤: 임의의 빈 지점, 그래서 Pinky가 계속 돌아다니며 사람을 만남."""
        g = self.patrol
        grid = self.blocked(grid, res, ox, oy)
        reach = self.reachable(grid, res, ox, oy, rx, ry)

        def inside(p):
            c, r = int((p[0] - ox) / res), int((p[1] - oy) / res)
            return reach is None or (0 <= r < reach.shape[0] and 0 <= c < reach.shape[1] and reach[r, c])
        if g is not None and now - self.patrol_t < 40.0 and math.hypot(g[0] - rx, g[1] - ry) > self.reach and inside(g):
            return g  # 아직 가는 중 (그 사이 발견한 바닥 선에 막히지 않음)
        self.patrol_reached = g is not None and math.hypot(g[0] - rx, g[1] - ry) <= self.reach
        ok = self.traversable(grid, res)  # 넓은 홀만이 아니라 좁은 (30 cm) 복도도 포함
        if reach is not None:
            ok &= reach  # Pinky 자신의 복도 안 지점만, 바닥 선 뒤는 절대 안 됨
        rr, cc = np.nonzero(ok)
        if len(rr) == 0:
            return None
        xs, ys = ox + (cc + 0.5) * res, oy + (rr + 0.5) * res
        far = np.hypot(xs - rx, ys - ry) > 0.3
        if far.any():
            xs, ys = xs[far], ys[far]
        i = int(rng.integers(len(xs)))
        self.patrol, self.patrol_t = (float(xs[i]), float(ys[i])), now
        return self.patrol

    def give_up(self):
        """Pinky가 바닥 선에서 되돌아감: 가던 목표는 (아마) 선 뒤에 있음. 다른 것을 고름."""
        if self.goal is not None:
            self.blacklist.append(self.goal)
            self.goal = None
        self.patrol = None
        self.patrol_reached = False

    def traversable(self, grid: np.ndarray, res: float) -> np.ndarray:
        """Pinky 중심이 들어갈 수 있는 빈 셀: 벽이나 바닥 선에서 pass_radius 이내가 아님.
        일부러 robot_radius보다 작음: 병원의 협로는 폭 ~20 cm뿐 (Pinky ~12 cm);
        주행 중에는 LiDAR가 실제 거리를 지킴."""
        r = max(1, int(round(self.pass_radius / res)))
        near = cv2.dilate((grid > 50).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        return (grid == 0) & (near == 0)

    def waypoint(self, grid: np.ndarray, res: float, ox: float, oy: float, rx: float, ry: float, goal,
                 ahead: float = 0.35):
        """목표까지의 최단 빈 경로를 따라 ~ahead m 앞의 점 (모서리를 돌아, 복도를 따라).
        블록 뒤의 목표로 곧장 가면 복도 미로에 갇히지만, 이 방법은 그렇지 않음.
        경로가 없으면 (목표가 막힘) None: 그러면 Pinky는 다음 계획까지 그냥 돌아다님."""
        if goal is None:
            return None
        grid = self.blocked(grid, res, ox, oy)
        ok = self.traversable(grid, res)
        h, w = grid.shape
        gc, gr = int((goal[0] - ox) / res), int((goal[1] - oy) / res)
        rc, rr = int((rx - ox) / res), int((ry - oy) / res)
        if not (0 <= gr < h and 0 <= gc < w and 0 <= rr < h and 0 <= rc < w):
            return None
        k = int(math.ceil(0.12 / res))
        for r0, c0 in ((rr, rc), (gr, gc)):  # 로봇 / 프런티어가 벽에 robot_radius보다 가까울 수 있음
            win = (slice(max(0, r0 - k), r0 + k + 1), slice(max(0, c0 - k), c0 + k + 1))
            ok[win] |= grid[win] == 0
        ok[gr, gc] = True
        dist = np.full((h, w), -1, np.int32)
        dist[gr, gc] = 0
        q = deque([(gr, gc)])
        nb = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
        while q:
            r, c = q.popleft()
            if r == rr and c == rc:
                break
            for dr, dc in nb:
                r2, c2 = r + dr, c + dc
                if 0 <= r2 < h and 0 <= c2 < w and ok[r2, c2] and dist[r2, c2] < 0:
                    dist[r2, c2] = dist[r, c] + 1
                    q.append((r2, c2))
        if dist[rr, rc] < 0:
            return None
        r, c = rr, rc
        for _ in range(int(ahead / res)):
            best = None
            for dr, dc in nb:
                r2, c2 = r + dr, c + dc
                if 0 <= r2 < h and 0 <= c2 < w and 0 <= dist[r2, c2] < dist[r, c] and (best is None or dist[r2, c2] < dist[best]):
                    best = (r2, c2)
            if best is None:
                break
            r, c = best
        return ox + (c + 0.5) * res, oy + (r + 0.5) * res

    def update(self, grid: np.ndarray, res: float, ox: float, oy: float, rx: float, ry: float, now: float):
        """map 좌표계의 목표 (x, y)를 반환, 없으면 None (더 탐색할 곳 없음 / 아직 지도 없음)."""
        if self.goal is not None:
            if math.hypot(self.goal[0] - rx, self.goal[1] - ry) < self.reach:
                self.goal = None
            elif now - self.goal_t > self.goal_timeout:
                self.blacklist.append(self.goal)  # 도달하지 못함
                self.goal = None
        grid = self.blocked(grid, res, ox, oy)
        reach = self.reachable(grid, res, ox, oy, rx, ry) if self.lines else None
        cands = []
        for r, c, size in self.frontiers(grid, res, self.robot_radius, self.min_cells):
            if reach is not None and not reach[r, c]:
                continue  # 바닥 선 뒤: 막힌 방
            x, y = ox + (c + 0.5) * res, oy + (r + 0.5) * res
            if any(math.hypot(x - bx, y - by) < 0.25 for bx, by in self.blacklist):
                continue
            d = math.hypot(x - rx, y - ry)
            if d < self.reach:
                continue
            cands.append((d - 0.01 * size, x, y))
        if not cands:
            self.empty_count += 1
            if self.empty_count >= self.done_after:
                self.done = True
            self.goal = None
            return None
        self.empty_count = 0
        self.done = False
        _, x, y = min(cands)
        # 현재 목표가 아직 프런티어면 유지 (비슷한 선택지 사이의 지그재그 방지)
        if self.goal is not None and any(math.hypot(self.goal[0] - cx, self.goal[1] - cy) < 0.3 for _, cx, cy in cands):
            return self.goal
        self.goal, self.goal_t = (x, y), now
        return self.goal
