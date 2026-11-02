"""ROS 2 노드: 자이로를 rad/s로 바꿔 Pinky IMU를 다시 발행.

Pinky의 BNO055 드라이버는 /imu_raw의 angular_velocity를 deg/s로 발행함 (check_sensors.py --motion에서
자이로가 오도메트리보다 ~57배 더 회전했음). ROS (REP-103), robot_localization, Nav2는
rad/s를 기대하므로, IMU를 융합하는 노드는 대신 이 노드의 /imu/data를 읽어야 함.

  python3 robot/imu_fix.py
  python3 robot/imu_fix.py --ros-args -p in_topic:=/imu_raw -p out_topic:=/imu/data
"""
import math

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu

DEG = math.pi / 180.0


class ImuFix(Node):
    def __init__(self):
        super().__init__("pinky_imu_fix")
        src = self.declare_parameter("in_topic", "/imu_raw").value
        dst = self.declare_parameter("out_topic", "/imu/data").value
        self.pub = self.create_publisher(Imu, dst, qos_profile_sensor_data)
        self.create_subscription(Imu, src, self.cb, qos_profile_sensor_data)
        self.get_logger().info(f"{src} (deg/s) -> {dst} (rad/s)")

    def cb(self, m: Imu):
        w = m.angular_velocity
        w.x, w.y, w.z = w.x * DEG, w.y * DEG, w.z * DEG
        m.angular_velocity_covariance = [c * DEG * DEG for c in m.angular_velocity_covariance] \
            if m.angular_velocity_covariance[0] > 0 else m.angular_velocity_covariance
        self.pub.publish(m)


def main():
    rclpy.init()
    n = ImuFix()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
