# 차선 그래프 구간 주행 (교행 복도): 테이프 따라가기 / 제자리 회전 / 차선 바꾸기를 이어서 실행하고 구간별 시간을 남긴다.
# **로봇에서** 실행 (IR 노드 pinky_sensor_adc 가 /ir_sensor/range 를 내고 있어야 함). 로봇이 움직임!
#   python3 lane_drive.py "follow:180:40" "rotate:270" "transfer:7.5" "rotate:0" "follow:0:130:lidar"
# 단계 (좌표는 그림 cm = 지도 m x100, 방향 deg 0=+x 90=+y):
#   follow:<방향>:<x 또는 y>[:lidar]  테이프 따라 진행 방향 축 좌표가 목표에 닿을 때까지 (기본 바퀴 축 기준 = 회전 중심.
#                                     :lidar 면 라이다 중심 = 그래프 노드 기준). 방향이 0/180 이면 x, 90/270 이면 y
#   rotate:<방향>                      제자리 회전 (odom 으로 돌고 AMCL 로 다시 맞춤, 최대 3번)
#   transfer:<차선 y 또는 x>           테이프 없는 차선 바꾸기: 방향 유지 직진, 새 테이프를 IR 가 밟으면 센서-축 거리만큼 더 가서 멈춤
#                                     (바퀴 축이 새 테이프 위). 예상 거리 +4cm 안에 못 찾으면 실패
# 결과: ir_logs/lane_<시각>.csv (단계별 시간·끝 자세)
import math
import os
import sys
import time

import rclpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from line_follow import DY_TAU, HERE, LineFollow, tape_pos, wrap  # noqa: E402

LIDAR_BEHIND_AXLE = 0.017   # m
SENSOR_AHEAD = 0.03         # m, IR 센서 줄이 바퀴 축 앞 (회전 시험 추정)
SPEED = 0.05                # m/s, 테이프 따라가기
XFER_SPEED = 0.03           # m/s, 차선 바꾸기
KP, KD = 8.0, 15.0          # line_follow.py 10-26 보정 시험 값
WMAX = 0.4
ROT_SETTLE = 0.3            # s, 회전 앞뒤로 AMCL 이 따라오게 멈추는 시간 (10-29: 0.6 → 0.3, rot_test 로 끝 오차 ≤1.5° 확인)
ROT_WMAX = 1.5              # rad/s, 제자리 회전 최대 각속도 (10-29: 0.3 → 0.6 → 1.5 = velocity_smoother 한도. 회전이 주행 시간의 34% 라서. 90° 7.5 → 3.6 s)
MAX_DEV = 0.04              # m, 차선 축에서 AMCL 옆 벗어남 한도 (테이프가 지도 축과 1~2° 어긋남)
TAPE_SEEN = 1.5             # 흰 정도 합 (세 센서가 테이프를 가로로 밟음)
LOST_S = 0.8                # s, 테이프를 이만큼 못 찾으면 lost (그동안 마지막 본 쪽으로 제자리 회전)
EARLY = 0.02                # m, 차선 바꾸기: 예상보다 이만큼 먼저까지만 새 테이프로 인정 (10-28: 수술실 문 앞 y≈25 의 흰 것을 4cm 일찍 테이프로 잡음, 0.04 → 0.02)


class Driver:
    def __init__(self):
        self.n = LineFollow()
        self.trace = []   # follow 중 (시각, 남은 cm, IR 3, 흰 정도 3, 테이프 위치 cm) — edge_run 이 엣지마다 저장
        t_end = time.time() + 5
        while time.time() < t_end and (self.n.odom is None or self.n.ir is None or self.n.map_pose() is None):
            rclpy.spin_once(self.n, timeout_sec=0.05)
        if self.n.odom is None or self.n.ir is None or self.n.map_pose() is None:
            raise RuntimeError('odom / IR / TF(map) 중 안 들어오는 것 있음')

    def spin(self, sec):
        t = time.time() + sec
        while time.time() < t:
            rclpy.spin_once(self.n, timeout_sec=0.02)

    def stop(self):
        for _ in range(5):
            self.n.cmd(0.0, 0.0); time.sleep(0.02)

    def pose(self):
        """바퀴 축 (x, y) m, yaw"""
        return self.n.map_pose()

    # ---------- 제자리 회전 ----------
    def rotate(self, heading_deg, tol_deg=1.5, wmax=None, settle=None):
        wmax = ROT_WMAX if wmax is None else wmax
        settle = ROT_SETTLE if settle is None else settle
        tgt = math.radians(heading_deg)
        for _ in range(3):
            self.spin(settle)                                # AMCL 이 따라오게 잠깐 멈춤
            err = wrap(tgt - self.pose()[2])
            if abs(err) < math.radians(tol_deg):
                return 'ok'
            goal = self.n.odom[2] + err
            t_end = time.time() + abs(err) / 0.1 + 5
            while time.time() < t_end:
                rclpy.spin_once(self.n, timeout_sec=0.02)
                e = wrap(goal - self.n.odom[2])
                if abs(e) < math.radians(0.7):
                    break
                self.n.cmd(0.0, math.copysign(max(0.08, min(wmax, 1.5 * abs(e))), e))
            self.stop()
        self.spin(settle)
        return 'ok' if abs(wrap(tgt - self.pose()[2])) < math.radians(3) else 'rotate_err'

    # ---------- 테이프 따라가기 ----------
    def follow(self, heading_deg, target_cm, ref='axle'):
        hd = math.radians(heading_deg)
        ux, uy = round(math.cos(hd)), round(math.sin(hd))   # 복도 축 방향만 (0/90/180/270)
        x0, y0, _ = self.pose()
        lane = (y0 if ux else x0)                            # 옆 기준 = 출발 때 차선 좌표 (AMCL)
        tgt = target_cm / 100.0

        def remain():
            x, y, th = self.pose()
            if ref == 'lidar':
                x -= LIDAR_BEHIND_AXLE * math.cos(th); y -= LIDAR_BEHIND_AXLE * math.sin(th)
            return (tgt - x) * ux if ux else (tgt - y) * uy

        r0 = remain()
        if r0 <= 0:
            return 'already_past'
        last_t, y_prev, dy, lost_since = 0.0, None, 0.0, None
        deadline = time.time() + r0 / SPEED * 2.5 + 5
        status = 'timeout'
        while time.time() < deadline:
            rclpy.spin_once(self.n, timeout_sec=0.02)
            if time.time() - self.n.ir_t > 0.5:
                status = 'ir_stale'; break
            r = remain()
            if r <= 0.002:
                status = 'ok'; break
            x, y, _ = self.pose()
            dev = (y - lane) if ux else (x - lane)
            if abs(dev) > MAX_DEV:
                status = 'deviated'; break
            if self.n.ir_t == last_t:
                continue
            dt = self.n.ir_t - last_t if last_t else 0.05
            last_t = self.n.ir_t
            wts, yt = tape_pos(self.n.ir)
            self.trace.append((round(time.time(), 3), round(remain() * 100, 1), *self.n.ir, *(round(x, 2) for x in wts),
                               None if yt is None else round(yt * 100, 2)))
            if yt is None:   # 놓침: 멈춰서 마지막으로 본 쪽으로 천천히 돌며 다시 찾음 (10-27)
                lost_since = lost_since or time.time()
                if time.time() - lost_since > LOST_S:
                    status = 'lost'; break
                self.n.cmd(0.0, math.copysign(0.25, y_prev) if y_prev and abs(y_prev) > 0.003 else 0.0); continue
            lost_since = None
            if y_prev is not None:
                k = min(1.0, dt / (DY_TAU + dt))
                dy += k * ((yt - y_prev) / max(dt, 0.02) - dy)
            y_prev = yt
            v = SPEED if r > 0.05 else max(0.015, SPEED * r / 0.05)
            self.n.cmd(v, max(-WMAX, min(WMAX, KP * yt + KD * dy * (v / SPEED))))
        self.stop()
        return status

    # ---------- 차선 바꾸기 (테이프 없음) ----------
    def transfer(self, lane_cm):
        x0, y0, th0 = self.pose()
        ux, uy = round(math.cos(th0)), round(math.sin(th0))
        lane = lane_cm / 100.0
        expect = (lane - x0) * ux if ux else (lane - y0) * uy   # 바퀴 축이 새 차선까지 갈 거리
        if expect < 0.05:
            return 'bad_direction'
        o0 = self.n.odom
        yaw0 = o0[2]
        seen_at = None
        status = 'not_found'
        t_end = time.time() + (expect + 0.04) / XFER_SPEED * 2 + 5
        while time.time() < t_end:
            rclpy.spin_once(self.n, timeout_sec=0.02)
            d = math.hypot(self.n.odom[0] - o0[0], self.n.odom[1] - o0[1])
            if seen_at is None:
                if d > expect + 0.04:
                    break
                w, _ = tape_pos(self.n.ir)
                if d > expect - SENSOR_AHEAD - EARLY and sum(w) >= TAPE_SEEN:   # 너무 일찍 본 흰 것은 무시
                    seen_at = d
                    print(f'  새 테이프 발견: odom {d * 100:.1f} cm (예상 {(expect - SENSOR_AHEAD) * 100:.1f})')
            elif d >= seen_at + SENSOR_AHEAD:
                status = 'ok'; break
            v = XFER_SPEED if seen_at is None else max(0.015, XFER_SPEED * (seen_at + SENSOR_AHEAD - d) / 0.02)
            self.n.cmd(min(v, XFER_SPEED), -2.0 * wrap(self.n.odom[2] - yaw0))
        self.stop()
        return status


def main():
    steps = sys.argv[1:]
    if not steps:
        print(__doc__ or '단계 없음'); return 1
    rclpy.init()
    dr = Driver()
    rows = []
    status = 'ok'
    try:
        for s in steps:
            p = s.split(':')
            t0 = time.time()
            if p[0] == 'follow':
                status = dr.follow(float(p[1]), float(p[2]), p[3] if len(p) > 3 else 'axle')
            elif p[0] == 'rotate':
                status = dr.rotate(float(p[1]))
            elif p[0] == 'transfer':
                status = dr.transfer(float(p[1]))
            else:
                status = 'unknown_step'
            dr.spin(0.3)
            x, y, th = dr.pose()
            lx, ly = x - LIDAR_BEHIND_AXLE * math.cos(th), y - LIDAR_BEHIND_AXLE * math.sin(th)
            dt = time.time() - t0
            rows.append((s, status, dt, x * 100, y * 100, lx * 100, ly * 100, math.degrees(th)))
            print(f'{s:22s} {status:10s} {dt:5.1f} s  축 ({x * 100:.1f}, {y * 100:.1f})  라이다 ({lx * 100:.1f}, {ly * 100:.1f})  {math.degrees(th):.1f}°')
            if status != 'ok':
                break
    finally:
        dr.stop()
    path = os.path.join(HERE, 'ir_logs', time.strftime('lane_%m%d_%H%M%S.csv'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('step,status,time_s,axle_x,axle_y,lidar_x,lidar_y,heading\n')
        for r in rows:
            f.write(f'{r[0]},{r[1]},{r[2]:.2f},' + ','.join(f'{v:.2f}' for v in r[3:]) + '\n')
    print(f'저장: {path}')
    dr.n.destroy_node(); rclpy.shutdown()
    return 0 if status == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
