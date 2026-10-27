# 구간별 FollowPath 테스트 주행: 구간을 하나씩 보내고, 끝날 때마다 AMCL 위치와 목표의 차이를 기록한다.
# 좌표는 그림 cm, **라이다 중심** 기준 (follow_path_client.py 와 같음). 실패하면 그 자리에서 멈춘다.
#   python3 run_route.py --dry-run            # 경로만 출력
#   python3 run_route.py                      # 실제 주행 (로봇이 움직임!)
#   python3 run_route.py --from 3             # 3번 구간부터
#   python3 run_route.py --from 2 --approach  # 지금 자리(AMCL)에서 2번 구간 시작점으로 먼저 옮긴 뒤 2번부터
#   python3 run_route.py --dock               # 완주 뒤 카메라 정밀 주차(precise_dock.py, 로봇에서 실행)까지
import argparse
import subprocess
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from follow_path_client import LIDAR_BEHIND_AXLE, build_poses, densify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# A -> OMX 정차점: 아래 복도 가운데(y=15) -> 오른쪽 협로(x=130) -> 위 복도 가운데(y=145) -> 약제실 문 -> 정차점
# 4번째 값 = 주행 모드: None 이면 Nav2 FollowPath, dict 면 벽 따라가기(corridor_drive.py, side 쪽 벽까지 offset cm)
WALL_RIGHT_10 = dict(side='right', offset=10.0)
ROUTE_A_TO_OMX = [
    ('S1 아래 복도', [(182.7, 24.0), (165, 15), (130, 15)], 90, None),
    ('S2 오른쪽 협로', [(130, 15), (130, 145)], 180, WALL_RIGHT_10),   # 20cm 협로: Nav2 충돌 검사로는 통과 불가 (2026-10-21)
    ('S3 위 복도', [(130, 145), (98.9, 145)], 90, None),
    ('S4 약제실 문', [(98.9, 145), (98.9, 178.8)], 90, None),
]


# S4 뒤 카메라 정밀 주차: 카메라가 로봇에 붙어 있어 precise_dock.py 는 로봇에서 돈다. PC 에서 run_route 를 돌리면 ssh 로 부른다.
# 기준 자세는 aruco_ref.json 의 dock (precise_dock.py --teach). 2026-10-22 지금 기준은 수술실 시험 마커 → 실제 OMX 에서 다시 가르칠 것.
ON_ROBOT = os.path.isdir('/home/pinky/pinky_map_rev3')
DOCK_CMD = (['python3', os.path.join(HERE, 'precise_dock.py')] if ON_ROBOT else
            ['ssh', 'pinky', 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=56; '
                             'cd ~/pinky_map_rev3/tools && python3 precise_dock.py'])


def run_dock():
    """정밀 주차 실행. 반환 dict(status=ok|fail, exit=종료코드, lines=마지막 출력)"""
    t0 = time.time(); lines = []
    p = subprocess.Popen(DOCK_CMD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for ln in p.stdout:
            ln = ln.rstrip()
            if ln.startswith('[') and ('INFO' in ln or 'WARN' in ln):  # libcamera 로그
                continue
            print('  ' + ln); lines.append(ln)
        p.wait()
    except KeyboardInterrupt:
        p.terminate(); p.wait(); lines.append('취소')
    return dict(status='ok' if p.returncode == 0 else 'fail', exit=p.returncode, time_s=round(time.time() - t0, 1), lines=lines[-6:])


JOIN_AHEAD = 8.0  # cm, 경로 합류점 = 지금 위치를 경로에 내린 점에서 이만큼 앞


def join_point(cur, pts):
    """지금 위치(cur)에서 구간 경로(pts)로 합류할 점. (None, 이유) 또는 (합류점, 그 점이 놓인 변 번호)"""
    best = None
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(pts, pts[1:])):
        L = math.hypot(x1 - x0, y1 - y0); ux, uy = (x1 - x0) / L, (y1 - y0) / L
        t = max(0.0, min(L, (cur[0] - x0) * ux + (cur[1] - y0) * uy))
        d = math.hypot(cur[0] - (x0 + ux * t), cur[1] - (y0 + uy * t))
        if best is None or d < best[0]:
            best = (d, i, t, L, x0, y0, ux, uy)
    d, i, t, L, x0, y0, ux, uy = best
    if d < 2.0 and t < 2.0 and i == 0:
        return None, f'지금 {cur} 가 시작점 {pts[0]} 에서 2cm 안'
    if d < 1.0:
        return None, f'지금 {cur} 가 경로에서 1cm 안'
    t = min(L, t + JOIN_AHEAD) if t > 0 else 0.0  # 시작점보다 뒤면 시작점으로
    return (round(x0 + ux * t, 1), round(y0 + uy * t, 1)), i


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='start', type=int, default=1, help='시작 구간 번호 (1부터)')
    ap.add_argument('--step', type=float, default=2.0)
    ap.add_argument('--approach', action='store_true', help='지금 자리에서 첫 구간 시작점까지 가는 구간을 앞에 붙임')
    ap.add_argument('--dock', action='store_true', help='완주 뒤 카메라 정밀 주차까지 (precise_dock.py)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    segs = [(name, build_poses(densify(pts, a.step), fh), pts, fh, mode)
            for name, pts, fh, mode in ROUTE_A_TO_OMX][a.start - 1:]
    for name, poses, pts, fh, mode in segs:
        print(f'{name}: {pts} -> {fh}°, ' + (f'벽 따라가기 {mode}' if mode else f'Nav2 {len(poses)} poses'))
    if a.dock:
        print('S5 정밀 주차: ' + ' '.join(DOCK_CMD[:2] if ON_ROBOT else DOCK_CMD[:2] + ['… precise_dock.py']))
    if a.dry_run:
        return

    import rclpy
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from nav2_msgs.action import FollowPath
    from nav_msgs.msg import Path
    from rclpy.action import ActionClient

    rclpy.init()
    node = rclpy.create_node('run_route')
    amcl = []
    node.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', lambda m: amcl.append(m), 10)
    client = ActionClient(node, FollowPath, 'follow_path')
    if not client.wait_for_server(timeout_sec=5.0):
        print('follow_path 액션 서버 없음'); return 1
    if a.approach:
        # 멈춰 있으면 /amcl_pose 가 안 나오므로 TF(map -> base_footprint)로 현재 위치를 읽는다
        from tf2_ros import Buffer, TransformListener
        tfb = Buffer(); TransformListener(tfb, node); t1 = time.time()
        while not tfb.can_transform('map', 'base_footprint', rclpy.time.Time()) and time.time() - t1 < 5:
            rclpy.spin_once(node, timeout_sec=0.1)
        try:
            tr = tfb.lookup_transform('map', 'base_footprint', rclpy.time.Time()).transform
        except Exception as e:  # noqa: BLE001
            print(f'map -> base_footprint TF 없음: {e}'); return 1
        th = yaw_of(tr.rotation)
        cur = (round((tr.translation.x - LIDAR_BEHIND_AXLE * math.cos(th)) * 100, 1),
               round((tr.translation.y - LIDAR_BEHIND_AXLE * math.sin(th)) * 100, 1))
        name, _, pts, fh, mode = segs[0]
        j, info = join_point(cur, pts)
        if mode:
            print(f'S0 생략: {name} 은 벽 따라가기라 지금 자리 {cur} 에서 바로 축선으로 합류')
        elif j is None:
            print(f'S0 생략: {info}')
        else:
            rest = [j] + pts[info + 1:]
            segs[0] = (name, build_poses(densify(rest, a.step), fh), rest, fh, mode)
            h0 = round(math.degrees(math.atan2(rest[1][1] - j[1], rest[1][0] - j[0])), 1)
            segs.insert(0, ('S0 경로 합류', build_poses(densify([cur, j], a.step), h0), [cur, j], h0, None))
            print(f'S0 경로 합류: {cur} -> {j}, {h0}°  이어서 {name}: {rest}')
    log = []
    out = os.path.join(HERE, 'route_logs', f'route_{time.strftime("%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = True
    corridor = None
    for name, poses, pts, fh, mode in segs:
        if mode:
            from corridor_drive import CorridorDrive
            corridor = corridor or CorridorDrive(node, mode['side'], mode['offset'])
            corridor.side, corridor.d_ref = mode['side'], mode['offset'] / 100
            print(f'\n▶ {name} 시작 (벽 따라가기 {mode})')
            clog = os.path.join(HERE, 'route_logs', f'corridor_{time.strftime("%m%d_%H%M%S")}.npz')
            try:
                cr = corridor.run(pts[0], pts[-1], fh, clog)
            except KeyboardInterrupt:
                corridor.stop(); print('\n취소'); ok = False; break
            x, y, th = corridor.map_pose(); tx, ty = pts[-1]; dx, dy = x * 100 - tx, y * 100 - ty; rad = math.radians(fh)
            rec = dict(segment=name, mode='wall', **cr, log=clog, target_lidar_cm=[tx, ty, fh],
                       amcl_lidar_cm=[round(x * 100, 1), round(y * 100, 1), round(math.degrees(th), 1)],
                       err_fwd_cm=round(dx * math.cos(rad) + dy * math.sin(rad), 1),
                       err_left_cm=round(-dx * math.sin(rad) + dy * math.cos(rad), 1),
                       err_deg=round((math.degrees(th) - fh + 180) % 360 - 180, 1))
            log.append(rec)
            print(f'  결과 {cr}, AMCL 라이다 중심 {rec["amcl_lidar_cm"]}, 오차 앞 {rec["err_fwd_cm"]} / 왼 {rec["err_left_cm"]} cm, {rec["err_deg"]}°')
            if cr['status'] != 'ok':
                ok = False; break
            continue
        path = Path(); path.header.frame_id = 'map'; path.header.stamp = node.get_clock().now().to_msg()
        for x, y, yaw in poses:
            p = PoseStamped(); p.header = path.header
            p.pose.position.x, p.pose.position.y = x, y
            p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            path.poses.append(p)
        goal = FollowPath.Goal(path=path, controller_id='FollowPath', goal_checker_id='general_goal_checker',
                               progress_checker_id='progress_checker')
        print(f'\n▶ {name} 시작')
        t0 = time.time()
        fut = client.send_goal_async(goal, feedback_callback=lambda f: print(
            f'  남은 {f.feedback.distance_to_goal:.2f} m, 속도 {f.feedback.speed:.2f} m/s   ', end='\r'))
        rclpy.spin_until_future_complete(node, fut)
        gh = fut.result()
        if not gh.accepted:
            print('거부됨'); ok = False; break
        res = gh.get_result_async()
        try:
            rclpy.spin_until_future_complete(node, res)
        except KeyboardInterrupt:
            print('\n취소 요청'); rclpy.spin_until_future_complete(node, gh.cancel_goal_async()); ok = False
            break
        r = res.result()
        amcl.clear(); t1 = time.time()
        while not amcl and time.time() - t1 < 3:
            rclpy.spin_once(node, timeout_sec=0.1)
        rec = {'segment': name, 'status': r.status, 'error_code': r.result.error_code,
               'error_msg': getattr(r.result, 'error_msg', ''), 'time_s': round(time.time() - t0, 1),
               'target_lidar_cm': [pts[-1][0], pts[-1][1], fh]}
        if amcl:
            pp = amcl[-1].pose.pose; th = yaw_of(pp.orientation)
            lx = pp.position.x - LIDAR_BEHIND_AXLE * math.cos(th); ly = pp.position.y - LIDAR_BEHIND_AXLE * math.sin(th)
            tx, ty = pts[-1]; dx, dy = lx * 100 - tx, ly * 100 - ty
            dth = (math.degrees(th) - fh + 180) % 360 - 180
            rad = math.radians(fh)
            rec.update(amcl_lidar_cm=[round(lx * 100, 1), round(ly * 100, 1), round(math.degrees(th), 1)],
                       err_fwd_cm=round(dx * math.cos(rad) + dy * math.sin(rad), 1),
                       err_left_cm=round(-dx * math.sin(rad) + dy * math.cos(rad), 1), err_deg=round(dth, 1))
        log.append(rec)
        print(f'\n  결과 status={r.status} error_code={r.result.error_code} {rec.get("error_msg", "")} '
              f'{rec["time_s"]} s, AMCL 라이다 중심 {rec.get("amcl_lidar_cm")}, '
              f'오차 앞 {rec.get("err_fwd_cm")} / 왼 {rec.get("err_left_cm")} cm, {rec.get("err_deg")}°')
        if r.status != 4:  # 4 = SUCCEEDED
            ok = False; break
    if ok and a.dock:
        print('\n▶ S5 정밀 주차 시작 (카메라)')
        dr = run_dock()
        log.append(dict(segment='S5 정밀 주차', mode='dock', **dr))
        print(f'  결과 {dr["status"]} (종료코드 {dr["exit"]}, {dr["time_s"]} s)')
        ok = dr['status'] == 'ok'
    json.dump(log, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'\n{"완주" if ok else "중단"} — 기록 {out}')
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
