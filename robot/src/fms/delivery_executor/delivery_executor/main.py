# =============================================================================
# 파일   : delivery_executor/main.py
# 역할   : 배송 실행기 진입점 — 설정의 로봇마다 DeliveryWorker 스레드 하나 (ros2 run delivery_executor executor)
# 작성일 : 2026-10-20
# 구성   :
#   - load_config()   --config 또는 DELIVERY_EXECUTOR_CONFIG 또는 설치된 config/executor.yaml
#   - main()          로봇별 주행기·마커·EMR 클라이언트·워커를 만들고 Ctrl+C까지. Ctrl+C·SIGTERM이면 진행 중 주행을
#                     취소해 로봇을 세운다. 맡던 배송은 EMR에 그대로 남아 다음 시작 때 이어서 한다
#   - 로봇별 navigation: pinky_api(팀원 Pinky API :8080, HTTP, 2026-10-22) | ros(Nav2 navigate_to_pose, 도메인 필요)
#   - --check: 로봇을 움직이지 않고 연결·설정만 점검하고 끝낸다 (check.py, 2026-10-22)
#     receipt_markers: false면 마커를 읽지 않는다(2026-10-22 기본 — 수령은 "받았습니다" 버튼). ROS는 쓸 때만 불러온다
# =============================================================================
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from delivery_executor.emr_client import RobotEmrClient, read_api_key
from delivery_executor.logic import DeliveryWorker, NoMarkers, WorkerSettings

log = logging.getLogger("delivery_executor")


class _RobotFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.robot = getattr(record, "robot", "-")
        return super().format(record)


def default_config_path() -> str:
    """설치된 share/delivery_executor/config/executor.yaml (없으면 소스 옆 config)."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return str(Path(get_package_share_directory("delivery_executor")) / "config" / "executor.yaml")
    except Exception:
        return str(Path(__file__).resolve().parent.parent / "config" / "executor.yaml")


def load_config(path: str) -> dict[str, Any]:
    with open(os.path.expanduser(path), encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not config.get("robots"):
        raise ValueError(f"{path}: robots가 비어 있습니다")
    return config


def _optional_seconds(value: Any) -> float | None:
    """설정의 초 값. null·0·빈 값이면 None(제한 없음). [입력] value [출력] float | None"""
    return float(value) if value not in (None, "", 0, 0.0) else None


def _make_navigation(name: str, robot: dict[str, Any], config: dict[str, Any]) -> tuple[Any, Any, Any]:
    """로봇 설정 → (주행기, 마커, ROS 연결 또는 None). ROS는 navigation: ros이거나 receipt_markers: true일 때만 불러온다
    — logic·pinky_api 테스트와 Pinky API 실행은 rclpy 없이 돈다.
    [입력] name / robot: 설정의 로봇 한 대 / config: 전체 설정 [출력] tuple
    """
    navigation = robot.get("navigation", "ros")
    use_markers = bool(robot.get("receipt_markers", False))
    ros = None
    if navigation == "ros" or use_markers:
        from delivery_executor.ros_io import RobotRos
        ros = RobotRos(name, int(robot.get("ros_domain_id", 0)), robot.get("namespace", ""))
    if navigation == "pinky_api":
        from delivery_executor.pinky_api import PinkyApiClient, PinkyApiNavigator, parse_dests
        navigator = PinkyApiNavigator(PinkyApiClient(robot["pinky_api"]), parse_dests(robot.get("dests")), name=name)
    elif navigation == "ros":
        from delivery_executor.ros_io import RosNavigator
        navigator = RosNavigator(ros)
    else:
        raise ValueError(f"{name}: navigation은 pinky_api 또는 ros ({navigation})")
    if use_markers:
        from delivery_executor.ros_io import RosMarkers
        markers = RosMarkers(ros)
    else:
        markers = NoMarkers()   # 마커는 일단 끔 (2026-10-22) — 수령은 "받았습니다" → /robot/me
    return navigator, markers, ros


def main(argv: list[str] | None = None) -> int:
    """[입력] argv [출력] 종료 코드"""
    argv = [argument for argument in (argv if argv is not None else sys.argv[1:]) if not argument.startswith("--ros-args")]
    parser = argparse.ArgumentParser(description="관제 PC 배송 실행기 (EMR claim → Pinky API 또는 Nav2 → 보고)")
    parser.add_argument("--config", default=os.getenv("DELIVERY_EXECUTOR_CONFIG") or default_config_path())
    parser.add_argument("--robot", action="append", help="설정 중 이 로봇만 (여러 번 가능)")
    parser.add_argument("--check", action="store_true", help="연결·설정만 점검하고 끝냄 (로봇을 움직이지 않음)")
    arguments, _ = parser.parse_known_args(argv)

    handler = logging.StreamHandler()
    handler.setFormatter(_RobotFormatter("%(asctime)s [%(robot)s] %(levelname)s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    config = load_config(arguments.config)
    log.info("설정 %s, EMR %s", arguments.config, config["emr_url"])
    if arguments.check:
        from delivery_executor.check import check_robot
        problems = sum(check_robot(name, robot, RobotEmrClient(config["emr_url"], read_api_key(robot["api_key_file"])))
                       for name, robot in config["robots"].items() if not arguments.robot or name in arguments.robot)
        return 1 if problems else 0
    stop_event = threading.Event()
    connections: list[Any] = []   # RobotRos — ROS를 쓰는 로봇만
    navigators: list[Any] = []    # cancel_current()가 있는 주행기
    threads: list[threading.Thread] = []
    for name, robot in config["robots"].items():
        if arguments.robot and name not in arguments.robot:
            continue
        settings = WorkerSettings(
            emr_robot_id=int(robot["emr_robot_id"]),
            blocked_location_ids=frozenset(int(location_id) for location_id in robot.get("blocked_location_ids") or []),
            claim_period_s=float(config.get("claim_period_s", 3.0)),
            navigation_timeout_s=_optional_seconds(config.get("navigation_timeout_s")),
            navigation_poll_s=float(config.get("navigation_poll_s", 1.0)),
            map_wait_s=float(config.get("map_wait_s", 10.0)),
            receipt_debounce_s=float(config.get("receipt_debounce_s", 3.0)),
            receipt_poll_s=float(config.get("receipt_poll_s", 2.0)),
            check_map=robot.get("navigation", "ros") == "ros",
        )
        emr = RobotEmrClient(config["emr_url"], read_api_key(robot["api_key_file"]))
        navigator, markers, ros = _make_navigation(name, robot, config)
        if ros is not None:
            connections.append(ros)
        navigators.append(navigator)
        log.info("로봇 %s: 주행 %s, 마커 %s", name, robot.get("navigation", "ros"), "읽음" if robot.get("receipt_markers") else "안 읽음(버튼 수령)")
        worker = DeliveryWorker(name, emr, navigator, markers, settings, stop_event=stop_event)
        thread = threading.Thread(target=worker.run, name=f"worker-{name}", daemon=True)
        thread.start()
        threads.append(thread)
    if not threads:
        log.error("실행할 로봇이 없습니다 (--robot 확인)")
        return 2

    # Ctrl+C·SIGTERM: 멈춤 표시 → 진행 중 주행 목표 취소(로봇을 세움) → 작업 스레드가 끝나길 기다림
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    while any(thread.is_alive() for thread in threads) and not stop_event.is_set():
        stop_event.wait(0.5)
    if stop_event.is_set():
        log.info("멈춥니다 — 진행 중 주행을 취소합니다 (맡던 배송은 다음 시작 때 이어서)")
        stop_event.set()
    for navigator in navigators:
        navigator.cancel_current()
    for thread in threads:
        thread.join(timeout=10)
    for ros in connections:
        ros.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
