# =============================================================================
# 파일   : delivery_executor/ros_io.py
# 역할   : 로봇 한 대의 ROS 2 연결 — 로봇별 도메인 Context + 노드 + 전용 스핀 스레드
# 작성일 : 2026-10-20
# 구성   :
#   - RobotRos      Context(domain_id)·노드·실행기 스레드. close()로 정리
#   - RosNavigator  navigate_to_pose 액션 (수락·결과·제한 시간·취소), /map 1회 수신 → logic.Navigator
#                   cancel_current(): 실행기를 멈출 때 진행 중 목표를 취소해 로봇을 세운다
#   - RosMarkers    receipt_marker(std_msgs/Int32) 구독 → logic.MarkerSource (카메라 마커 노드가 발행, 없으면 사람이 ros2 topic pub)
# 작업 스레드(logic.DeliveryWorker)는 future에 done 콜백 + threading.Event로 기다린다 — 스핀은 전용 스레드가 한다
# (vla_executor/executor_node.py의 _wait_result와 같은 방식). Pinky upstream은 namespace 미지원 → 보통 namespace ''
# =============================================================================
from __future__ import annotations

import logging
import math
import queue
import threading
from typing import Any

import rclpy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Int32

RESULT_NAMES = {GoalStatus.STATUS_SUCCEEDED: "succeeded", GoalStatus.STATUS_ABORTED: "aborted",
                GoalStatus.STATUS_CANCELED: "canceled"}
SERVER_WAIT_S = 5.0
ACCEPT_WAIT_S = 5.0
MAP_QOS = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
log = logging.getLogger("delivery_executor")


def _wait_future(future, timeout_s: float):
    """future가 끝날 때까지(스핀은 다른 스레드) 기다린다. [출력] 결과 (시간 초과면 None)"""
    done = threading.Event()
    future.add_done_callback(lambda _: done.set())
    if not done.wait(timeout_s):
        return None
    return future.result()


def _yaw_from_quaternion(z: float, w: float, x: float = 0.0, y: float = 0.0) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class RobotRos:
    """로봇 한 대용 ROS 연결. 도메인이 로봇마다 다를 수 있어 Context를 따로 만든다."""

    def __init__(self, robot_name: str, ros_domain_id: int, namespace: str = "") -> None:
        self.context = Context()
        # rclpy 기본 SIGINT 처리기는 ROS만 끊고 실행기 본체에는 알리지 않는다 — 신호는 main.py가 직접 받는다
        rclpy.init(context=self.context, domain_id=ros_domain_id, signal_handler_options=SignalHandlerOptions.NO)
        node_name = f"delivery_executor_{robot_name}".replace("-", "_")
        self.node = Node(node_name, namespace=namespace or "", context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self._spin_thread = threading.Thread(target=self._spin, name=f"ros-{robot_name}", daemon=True)
        self._spin_thread.start()
        log.info("[%s] ROS 도메인 %s, namespace '%s'", robot_name, ros_domain_id, namespace)

    def _spin(self) -> None:
        try:
            self.executor.spin()
        except Exception as error:  # 종료 중 예외는 무시
            if self.context.ok():
                log.error("ROS 스핀 중단: %s", error)

    def close(self) -> None:
        """노드·Context 정리. 순서: Context 종료(스핀이 빠져나옴) → 스핀 스레드 끝 대기 → 실행기·노드 정리.
        스핀 중에 노드를 먼저 없애면 C++ 쪽이 abort한다(2026-10-20 확인).
        """
        if self.context.ok():
            rclpy.shutdown(context=self.context)
        self._spin_thread.join(timeout=5)
        try:
            self.executor.shutdown(timeout_sec=1.0)
            self.node.destroy_node()
        except Exception as error:   # 이미 Context가 끝나 정리할 것이 없을 때
            log.debug("ROS 정리 중 무시: %s", error)


class RosNavigator:
    """Nav2 navigate_to_pose로 주행 (map 프레임)."""

    def __init__(self, ros: RobotRos) -> None:
        self.ros = ros
        self.client = ActionClient(ros.node, NavigateToPose, "navigate_to_pose")
        self._current_goal = None   # 진행 중 목표 핸들 (취소용)
        self._map: OccupancyGrid | None = None
        self._map_event = threading.Event()
        ros.node.create_subscription(OccupancyGrid, "map", self._on_map, MAP_QOS)

    def _on_map(self, message: OccupancyGrid) -> None:
        self._map = message
        self._map_event.set()

    def robot_map(self, wait_s: float) -> dict[str, Any] | None:
        """로봇 /map 정보. [출력] {width, height, resolution, origin{x,y,yaw}} | None"""
        if not self._map_event.wait(wait_s) or self._map is None:
            return None
        info = self._map.info
        orientation = info.origin.orientation
        return {"width": info.width, "height": info.height, "resolution": info.resolution,
                "origin": {"x": info.origin.position.x, "y": info.origin.position.y,
                           "yaw": _yaw_from_quaternion(orientation.z, orientation.w, orientation.x, orientation.y)}}

    def navigate(self, x_m: float, y_m: float, yaw_rad: float, timeout_s: float) -> str:
        """[출력] succeeded | aborted | canceled | rejected | timeout | unavailable"""
        if not self.client.wait_for_server(timeout_sec=SERVER_WAIT_S):
            log.error("navigate_to_pose 액션 서버 없음 (로봇 Nav2·도메인 확인)")
            return "unavailable"
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.ros.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x_m)
        goal.pose.pose.position.y = float(y_m)
        goal.pose.pose.orientation.z = math.sin(yaw_rad / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw_rad / 2.0)
        handle = _wait_future(self.client.send_goal_async(goal), ACCEPT_WAIT_S)
        if handle is None or not handle.accepted:
            log.warning("Nav2가 목표를 거부했습니다 (%.2f, %.2f)", x_m, y_m)
            return "rejected"
        self._current_goal = handle
        try:
            result = _wait_future(handle.get_result_async(), timeout_s)
        finally:
            self._current_goal = None
        if result is None:
            log.warning("주행 시간 초과 %.0f초 — 목표 취소", timeout_s)
            _wait_future(handle.cancel_goal_async(), ACCEPT_WAIT_S)
            return "timeout"
        return RESULT_NAMES.get(result.status, f"status_{result.status}")

    def cancel_current(self) -> None:
        """진행 중 목표가 있으면 취소한다 (실행기 종료 때 로봇을 세운다)."""
        handle = self._current_goal
        if handle is not None:
            log.info("진행 중 주행 목표를 취소합니다")
            _wait_future(handle.cancel_goal_async(), ACCEPT_WAIT_S)


class RosMarkers:
    """receipt_marker(std_msgs/Int32) — 로봇 카메라가 읽은 ArUco DICT_4X4_250 번호."""

    def __init__(self, ros: RobotRos, topic: str = "receipt_marker") -> None:
        self._queue: queue.Queue[int] = queue.Queue(maxsize=100)
        ros.node.create_subscription(Int32, topic, self._on_marker, 10)

    def _on_marker(self, message: Int32) -> None:
        try:
            self._queue.put_nowait(int(message.data))
        except queue.Full:
            pass

    def wait_marker(self, timeout_s: float) -> int | None:
        try:
            return self._queue.get(timeout=max(0.0, timeout_s))
        except queue.Empty:
            return None

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
