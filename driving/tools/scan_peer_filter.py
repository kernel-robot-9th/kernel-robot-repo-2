# 다른 핑키를 AMCL 스캔에서 지운다: /scan → /scan_filtered (AMCL 이 이것을 씀, config: amcl.scan_topic).
# 핑키끼리 높이가 같아 교행·협로 끝에서 서로 라이다에 잡힘 → 맵에 없는 점이 AMCL 을 끌어당김 (10-29 사용자).
# 다른 로봇 위치는 FMS 가 로봇 API POST /peers 로 보내고, API 가 /peer_poses (PoseArray, map 프레임) 로 낸다.
# 그 둘레 RADIUS 안의 점은 거리 = inf (AMCL likelihood_field 는 최대 거리 이상인 빔을 안 씀).
# 위치가 MAX_AGE 넘게 안 오면 (FMS 없음·끊김) 아무것도 안 지우고 그대로 넘긴다.
# 벽 따라가기·접촉 검사(corridor_drive)는 원래 /scan 을 그대로 써서 다른 로봇이 가까우면 선다.
# nav2_followpath.launch.py 가 같이 띄운다.
import math
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseArray
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener

RADIUS = 0.10       # m, 다른 로봇 라이다 중심 둘레 (몸체 Ø11~14 반지름 7 cm + 위치 지연 ~3 cm)
MAX_AGE = 1.5       # s


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class PeerFilter(Node):
    def __init__(self):
        super().__init__('scan_peer_filter')
        self.peers, self.peers_t = np.zeros((0, 2)), 0.0
        self.tfb = Buffer(); self.tfl = TransformListener(self.tfb, self)
        self.pub = self.create_publisher(LaserScan, 'scan_filtered', qos_profile_sensor_data)
        self.create_subscription(LaserScan, 'scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(PoseArray, 'peer_poses', self.on_peers, 10)
        self.masked, self.last_log = 0, 0.0

    def on_peers(self, m):
        self.peers = np.array([[p.position.x, p.position.y] for p in m.poses]).reshape(-1, 2)
        self.peers_t = time.time()

    def on_scan(self, m):
        if len(self.peers) == 0 or time.time() - self.peers_t > MAX_AGE:
            self.pub.publish(m); return
        try:
            t = self.tfb.lookup_transform('map', m.header.frame_id, rclpy.time.Time()).transform
        except TransformException:
            self.pub.publish(m); return
        lx, ly, lth = t.translation.x, t.translation.y, yaw_of(t.rotation)
        # 로봇에서 RADIUS 보다 먼 peer 만 (자기 자신이 표에 섞여도 안 지움)
        P = self.peers[np.hypot(self.peers[:, 0] - lx, self.peers[:, 1] - ly) > RADIUS]
        if len(P) == 0:
            self.pub.publish(m); return
        R = np.asarray(m.ranges, dtype=float)
        a = m.angle_min + np.arange(len(R)) * m.angle_increment + lth
        ok = np.isfinite(R)
        X = lx + np.where(ok, R, 0) * np.cos(a)
        Y = ly + np.where(ok, R, 0) * np.sin(a)
        d = np.min(np.hypot(X[:, None] - P[None, :, 0], Y[:, None] - P[None, :, 1]), axis=1)
        hit = ok & (d < RADIUS)
        n = int(hit.sum())
        if n:
            R[hit] = float('inf')
            m.ranges = R.astype(np.float32).tolist()
        self.pub.publish(m)
        self.masked += n
        if time.time() - self.last_log > 10:
            self.get_logger().info(f'다른 로봇 {len(P)}대, 최근 10초 지운 빔 {self.masked}')
            self.masked, self.last_log = 0, time.time()


def main():
    rclpy.init()
    n = PeerFilter()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
