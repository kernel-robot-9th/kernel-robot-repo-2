# 현재 AMCL 위치 + 스캔 저장 (움직이지 않음) -> marker_logs/NOW_<시각>.npz, 라이다 중심 좌표 출력
import math, os, time
import numpy as np, rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener
HERE = os.path.dirname(os.path.abspath(__file__))
def yaw_of(q): return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
rclpy.init(); n = rclpy.create_node('now_pose'); scans, amcl = [], []
n.create_subscription(LaserScan, '/scan', lambda m: scans.append(m), qos_profile_sensor_data)
n.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', lambda m: amcl.append(m), 10)
cli = n.create_client(Empty, '/request_nomotion_update'); tfb = Buffer(); TransformListener(tfb, n)
def spin(s):
    t = time.time()
    while time.time() - t < s: rclpy.spin_once(n, timeout_sec=0.05)
cli.wait_for_service(timeout_sec=5); spin(1.5)
for _ in range(15): cli.call_async(Empty.Request()); spin(0.3)
p = amcl[-1].pose; x, y, th = p.pose.position.x, p.pose.position.y, yaw_of(p.pose.orientation)
lt = tfb.lookup_transform('base_footprint', scans[-1].header.frame_id, rclpy.time.Time()).transform
ltf = (lt.translation.x, lt.translation.y, yaw_of(lt.rotation))
scans.clear(); spin(0.1)
while len(scans) < 20: spin(0.1)
s0 = scans[0]
out = os.path.join(HERE, 'marker_logs', f'NOW_{time.strftime("%H%M%S")}.npz')
np.savez(out, marker='NOW', truth=np.array([x, y, th]), amcl=np.array([x, y, th]), amcl_cov=np.array(p.covariance),
         track=np.zeros((0, 3)), ranges=np.array([list(s.ranges) for s in scans[:20]], np.float32),
         angle=np.array([s0.angle_min, s0.angle_max, s0.angle_increment]), range_lim=np.array([s0.range_min, s0.range_max]),
         laser_tf=np.array(ltf))
lx, ly = x + ltf[0]*math.cos(th), y + ltf[0]*math.sin(th)
print(f'AMCL 바퀴 축 ({x*100:.1f}, {y*100:.1f}) cm, {math.degrees(th)%360:.1f}°, σ {math.sqrt(p.covariance[0])*100:.1f}/{math.sqrt(p.covariance[7])*100:.1f} cm')
print(f'라이다 중심 ({lx*100:.1f}, {ly*100:.1f}) cm'); print(out)
