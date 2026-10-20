# =============================================================================
# 파일   : pinky_marker/follower_node.py
# 역할   : 간호사 신분증 마커 따라가기 (선택 기능, 배송과 별개). 팀원 marker_follower_2.py(2026-10-13)를 정리하고
#          Nav2·다른 조종과 부딪히지 않게 고침 (2026-10-20)
# 작성일 : 2026-10-20
# 구성   :
#   - NurseFollower  카메라 영상에서 대상 간호사 마커를 찾아 /cmd_vel로 따라간다
#       · 대상: target_id(간호사 신분증 마커 0~49). 명단 config/nurses.yaml(번호 → 이름)은 EMR 간호사 화면의 배정과 맞춘다
#       · FOLLOWING일 때만 /cmd_vel을 낸다. 멈출 때는 정지 명령을 세 번만 보내고 조용히 있다
#         (팀원 원본은 20 Hz로 늘 정지 명령을 내서 Nav2 주행을 막았다)
#       · Nav2 navigate_to_pose 목표가 수행 중이면 NAV_BUSY — 따라가지 않는다 (배송 실행기와 동시에 켜져도 안전)
#       · 서비스 ~/enable (std_srvs/SetBool)로 켜고 끈다. 파라미터 enabled_on_start로 시작 상태
#       · 상태는 follow/state(std_msgs/String)로, 상태가 바뀔 때마다 발행
# 사전은 DICT_4X4_250 — 간호사 마커(0~49)만 따라가고 일회용 수령 마커(50~249)는 무시
# 영상 QoS는 reliable·최신 1장(image_qos). 0.9 MB 영상을 best-effort(팀원 원본 qos_profile_sensor_data)로 받으면
# 이 PC의 기본 DDS에서 60장 중 0장 도착했다(2026-10-20 측정) — 조각 하나만 빠져도 그 장 전체가 버려진다
# Ctrl+C·SIGTERM은 직접 받는다 — 스크립트에서 &로 띄운 프로세스는 SIGINT가 무시된 채 시작해 안 꺼졌다(2026-10-20)
# =============================================================================
from __future__ import annotations

import os
import signal
import time

import rclpy
import yaml
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import SetBool

from pinky_marker.follow_logic import (
    FOLLOWING, TARGET_LOST, FollowParams, compute_command, decide_state, is_valid_target, publishes_velocity,
)
from pinky_marker.vision import image_to_gray, make_detector, marker_geometry

ACTIVE_GOAL_STATUSES = (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING, GoalStatus.STATUS_CANCELING)
STATUS_QOS = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
STOP_REPEAT = 3
IMAGE_QOS = {
    'reliable': QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE),
    'best_effort': qos_profile_sensor_data,
}


def default_registry_path() -> str:
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('pinky_marker'), 'config', 'nurses.yaml')
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'nurses.yaml')


class NurseFollower(Node):
    def __init__(self) -> None:
        super().__init__('nurse_follower')
        defaults = {
            'registry': default_registry_path(), 'target_id': -1, 'dictionary': '4x4_250', 'enabled_on_start': True,
            'image_topic': 'camera/image_raw', 'image_qos': 'reliable', 'cmd_topic': 'cmd_vel', 'nav_status_topic': 'navigate_to_pose/_action/status',
            'debug': False,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        follow_defaults = FollowParams()
        for name, value in vars(follow_defaults).items():
            self.declare_parameter(name, value)
        self.params = FollowParams(**{name: type(value)(self.get_parameter(name).value) for name, value in vars(follow_defaults).items()})
        get = lambda name: self.get_parameter(name).value   # noqa: E731

        self.registry = self._load_registry(str(get('registry')))
        self.target_id = self._pick_target(int(get('target_id')))
        self.detect = make_detector(str(get('dictionary')))
        self.debug = bool(get('debug'))
        self.enabled = bool(get('enabled_on_start'))

        self.cmd_publisher = self.create_publisher(Twist, str(get('cmd_topic')), 10)
        self.state_publisher = self.create_publisher(String, 'follow/state', 10)
        self.create_subscription(Image, str(get('image_topic')), self.on_image, IMAGE_QOS[str(get('image_qos'))])
        self.create_subscription(GoalStatusArray, str(get('nav_status_topic')), self.on_nav_status, STATUS_QOS)
        self.create_service(SetBool, '~/enable', self.on_enable)
        self.create_timer(0.05, self.on_control)   # 20 Hz

        self.navigation_active = False
        self.last_seen_s: float | None = None
        self.last_command = (0.0, 0.0)
        self.state: str | None = None
        self.stop_remaining = 0
        self.get_logger().info(
            f'간호사 명단 {self.registry} | 대상 {self.target_id}번({self.registry[self.target_id]}) | '
            f'{"켜짐" if self.enabled else "꺼짐 — ~/enable 서비스로 켬"}')

    # ---- 설정 -----------------------------------------------------------------

    def _load_registry(self, path: str) -> dict[int, str]:
        with open(os.path.expanduser(path), encoding='utf-8') as registry_file:
            data = yaml.safe_load(registry_file) or {}
        registry = {int(marker_id): str(name) for marker_id, name in (data.get('nurses') or {}).items()}
        invalid = [marker_id for marker_id in registry if not is_valid_target(marker_id)]
        if invalid:
            raise RuntimeError(f'{path}: 간호사 마커는 0~49번입니다 — 범위 밖 {invalid}')
        if not registry:
            raise RuntimeError(f'{path}: nurses가 비어 있습니다 (EMR 간호사 화면에서 배정한 번호를 적으세요)')
        return registry

    def _pick_target(self, target_id: int) -> int:
        if target_id == -1:
            if len(self.registry) != 1:
                raise RuntimeError('간호사가 여럿입니다: -p target_id:=<번호>로 고르세요')
            target_id = next(iter(self.registry))
        if target_id not in self.registry:
            raise RuntimeError(f'target_id {target_id}는 명단(nurses.yaml)에 없습니다')
        return target_id

    # ---- 입력 -----------------------------------------------------------------

    def on_enable(self, request: SetBool.Request, response: SetBool.Response) -> SetBool.Response:
        self.enabled = bool(request.data)
        self.last_seen_s = None   # 다시 켜면 처음부터 찾는다
        response.success = True
        response.message = '따라가기 켬' if self.enabled else '따라가기 끔'
        self.get_logger().info(response.message)
        return response

    def on_nav_status(self, message: GoalStatusArray) -> None:
        self.navigation_active = any(status.status in ACTIVE_GOAL_STATUSES for status in message.status_list)

    def on_image(self, message: Image) -> None:
        if not self.enabled or self.navigation_active:
            return   # 꺼져 있거나 Nav2가 주행 중이면 영상 처리도 하지 않는다 (라즈베리파이 부담)
        gray = image_to_gray(message.encoding, message.height, message.width, message.step, bytes(message.data))
        corners, ids = self.detect(gray)
        if ids is None:
            return
        for corner, marker_id in zip(corners, ids.flatten()):
            marker_id = int(marker_id)
            if marker_id != self.target_id:
                if self.debug:
                    kind = '명단의 다른 간호사' if marker_id in self.registry else ('일회용 수령 마커' if marker_id >= 50 else '명단에 없음')
                    self.get_logger().info(f'{marker_id}번 보임 ({kind}) — 무시', throttle_duration_sec=2.0)
                continue
            center_x_px, width_px = marker_geometry(corner)
            linear, angular, distance_m, x_error = compute_command(center_x_px, width_px, message.width, self.params)
            self.last_seen_s = time.monotonic()
            self.last_command = (linear, angular)
            if self.debug:
                self.get_logger().info(f'{marker_id}번: {width_px:.0f}px 약 {distance_m:.2f}m 좌우 {x_error:+.2f} → '
                                       f'{linear:+.3f} m/s {angular:+.2f} rad/s', throttle_duration_sec=0.5)

    # ---- 출력 -----------------------------------------------------------------

    def on_control(self) -> None:
        state = decide_state(self.enabled, self.navigation_active, self.last_seen_s, time.monotonic(), self.params)
        if state != self.state:
            if self.state == FOLLOWING:
                self.stop_remaining = STOP_REPEAT   # 따라가다 멈추면 정지 명령을 몇 번만
            self.state = state
            self.state_publisher.publish(String(data=state))
            if state == TARGET_LOST:
                self.get_logger().warning(f'상태 → {state} (간호사를 놓침, 멈춤)')
            else:
                self.get_logger().info(f'상태 → {state}')
        if publishes_velocity(state):
            twist = Twist()
            twist.linear.x, twist.angular.z = self.last_command
            self.cmd_publisher.publish(twist)
        elif self.stop_remaining > 0:
            self.cmd_publisher.publish(Twist())
            self.stop_remaining -= 1

    def stop(self) -> None:
        """종료 직전 — 따라가던 중이었으면 정지 명령."""
        if self.state == FOLLOWING:
            for _ in range(STOP_REPEAT):
                self.cmd_publisher.publish(Twist())
                time.sleep(0.05)


def main() -> None:
    # Ctrl+C를 직접 받아, ROS가 끊기기 전에 마지막 정지 명령을 보낼 수 있게 한다 (팀원 원본과 같음)
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    node = NurseFollower()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
