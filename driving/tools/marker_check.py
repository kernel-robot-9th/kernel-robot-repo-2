# 바닥 표시점 확인 (손으로 옮기는 방식) — map_drawn 기준 (맵 좌표 m = 그림 좌표 cm / 100)
# 로봇의 **라이다 중심**을 표시점 십자 위에, 정면을 화살표 방향으로 놓은 뒤:  python3 marker_check.py A
# (Nav2/AMCL 위치 = base_footprint = 바퀴 축 = 라이다보다 1.7cm 앞. 스크립트가 TF 로 변환한다)
# 1) 표시점 실제 좌표로 /initialpose (여유: 위치 3cm, 방향 3°)
# 2) AMCL request_nomotion_update 를 여러 번 → 스캔으로 다시 맞춘 위치
# 3) 스캔 여러 장 + AMCL 결과 + 라이다 장착 위치를 marker_logs/<표시점>_<시각>.npz 로 저장 (벽별 분석용)
import math
import os
import sys
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener

MARKERS = {  # 그림 좌표 cm, 방향 deg (0 = +x, 반시계 +)
    'A': (182.7, 24.0, 180), 'B': (130, 15, 90), 'C': (130, 80, 90), 'D': (130, 145, 180),
    'E': (105, 180, 90), 'F': (40, 145, 270), 'G': (40, 80, 270),
}
SIG_XY, SIG_YAW = 0.03, math.radians(3)
N_UPDATES, N_SCANS = 25, 20
HERE = os.path.dirname(os.path.abspath(__file__))


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def main():
    name = sys.argv[1].upper()
    if len(sys.argv) >= 5:
        MARKERS[name] = tuple(map(float, sys.argv[2:5]))
    xc, yc, hd = MARKERS[name]
    tx, ty, tyaw = xc / 100, yc / 100, math.radians(hd)

    rclpy.init()
    node = rclpy.create_node('marker_check')
    scans, amcl = [], []
    node.create_subscription(LaserScan, '/scan', lambda m: scans.append(m), qos_profile_sensor_data)
    node.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', lambda m: amcl.append(m), 10)
    pub = node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
    cli = node.create_client(Empty, '/request_nomotion_update')
    tfb = Buffer(); TransformListener(tfb, node)

    def spin(sec):
        t = time.time()
        while time.time() - t < sec:
            rclpy.spin_once(node, timeout_sec=0.05)

    if not cli.wait_for_service(timeout_sec=5):
        print('AMCL 서비스 없음 (/request_nomotion_update)'); return
    spin(1.5)
    if not scans:
        print('/scan 이 안 들어와요'); return
    laser = scans[-1].header.frame_id
    try:
        tf = tfb.lookup_transform('base_footprint', laser, rclpy.time.Time())
        lt = tf.transform
        laser_tf = (lt.translation.x, lt.translation.y, yaw_of(lt.rotation))
    except Exception as e:  # noqa: BLE001
        print('라이다 TF 없음:', e); return

    # 표시점 = 라이다 중심 → 바퀴 축(base_footprint) 위치로 변환
    tx -= laser_tf[0] * math.cos(tyaw) - laser_tf[1] * math.sin(tyaw)
    ty -= laser_tf[0] * math.sin(tyaw) + laser_tf[1] * math.cos(tyaw)

    # 1) 초기 위치
    msg = PoseWithCovarianceStamped()
    msg.header.frame_id = 'map'; msg.header.stamp = node.get_clock().now().to_msg()
    msg.pose.pose.position.x, msg.pose.pose.position.y = tx, ty
    msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(tyaw / 2), math.cos(tyaw / 2)
    cov = [0.0] * 36; cov[0] = cov[7] = SIG_XY ** 2; cov[35] = SIG_YAW ** 2
    msg.pose.covariance = cov
    for _ in range(3):
        pub.publish(msg); spin(0.3)
    amcl.clear(); spin(1.0)
    first = amcl[-1] if amcl else None

    # 2) 정지 상태에서 스캔으로 다시 맞추기
    track = []
    for _ in range(N_UPDATES):
        cli.call_async(Empty.Request()); spin(0.35)
        if amcl:
            p = amcl[-1].pose.pose
            track.append((p.position.x, p.position.y, yaw_of(p.orientation)))
    if not amcl:
        print('AMCL 위치가 안 나와요'); return
    fin = amcl[-1].pose
    fx, fy, fyaw = fin.pose.position.x, fin.pose.position.y, yaw_of(fin.pose.orientation)

    # 3) 스캔 저장
    scans.clear(); spin(0.1)
    while len(scans) < N_SCANS:
        spin(0.1)
    s0 = scans[0]
    R = np.array([list(s.ranges) for s in scans[:N_SCANS]], np.float32)
    os.makedirs(os.path.join(HERE, 'marker_logs'), exist_ok=True)
    out = os.path.join(HERE, 'marker_logs', f'{name}_{time.strftime("%H%M%S")}.npz')
    np.savez(out, marker=name, truth=np.array([tx, ty, tyaw]), amcl=np.array([fx, fy, fyaw]),
             amcl_cov=np.array(fin.covariance), track=np.array(track), ranges=R,
             angle=np.array([s0.angle_min, s0.angle_max, s0.angle_increment]),
             range_lim=np.array([s0.range_min, s0.range_max]), laser_tf=np.array(laser_tf))

    dx, dy = (fx - tx) * 100, (fy - ty) * 100
    dyaw = math.degrees((fyaw - tyaw + math.pi) % (2 * math.pi) - math.pi)
    sx, sy = math.sqrt(fin.covariance[0]) * 100, math.sqrt(fin.covariance[7]) * 100
    print(f'[{name}] 실제 ({xc:.1f}, {yc:.1f}) cm, {hd:.0f}°')
    print(f'    AMCL ({fx * 100:.1f}, {fy * 100:.1f}) cm, {math.degrees(fyaw) % 360:.1f}°  → 차이 dx {dx:+.1f} dy {dy:+.1f} cm, 방향 {dyaw:+.1f}°')
    print(f'    AMCL 불확실도 σx {sx:.1f} σy {sy:.1f} cm, 갱신 {len(track)}회, 라이다 {laser} @ base {laser_tf[0]*100:+.1f},{laser_tf[1]*100:+.1f} cm')
    print(f'    저장: {out}')
    node.destroy_node(); rclpy.shutdown()


if __name__ == '__main__':
    main()
