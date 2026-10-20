# =============================================================================
# 파일   : delivery_executor/main.py
# 역할   : 배송 실행기 진입점 — 설정의 로봇마다 DeliveryWorker 스레드 하나 (ros2 run delivery_executor executor)
# 작성일 : 2026-10-20
# 구성   :
#   - load_config()   --config 또는 DELIVERY_EXECUTOR_CONFIG 또는 설치된 config/executor.yaml
#   - main()          로봇별 ROS 연결·EMR 클라이언트·워커를 만들고 Ctrl+C까지. Ctrl+C·SIGTERM이면 진행 중 주행 목표를
#                     취소해 로봇을 세운다. 맡던 배송은 EMR에 그대로 남아 다음 시작 때 이어서 한다
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
from delivery_executor.logic import DeliveryWorker, WorkerSettings

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


def main(argv: list[str] | None = None) -> int:
    """[입력] argv [출력] 종료 코드"""
    argv = [argument for argument in (argv if argv is not None else sys.argv[1:]) if not argument.startswith("--ros-args")]
    parser = argparse.ArgumentParser(description="관제 PC 배송 실행기 (EMR claim → Nav2 → 보고)")
    parser.add_argument("--config", default=os.getenv("DELIVERY_EXECUTOR_CONFIG") or default_config_path())
    parser.add_argument("--robot", action="append", help="설정 중 이 로봇만 (여러 번 가능)")
    arguments, _ = parser.parse_known_args(argv)

    handler = logging.StreamHandler()
    handler.setFormatter(_RobotFormatter("%(asctime)s [%(robot)s] %(levelname)s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    config = load_config(arguments.config)
    log.info("설정 %s, EMR %s", arguments.config, config["emr_url"])
    # ROS 연결은 실제로 쓸 때만 불러온다 — logic 테스트는 rclpy 없이 돈다
    from delivery_executor.ros_io import RobotRos, RosMarkers, RosNavigator

    stop_event = threading.Event()
    connections: list[RobotRos] = []
    navigators: list[RosNavigator] = []
    threads: list[threading.Thread] = []
    for name, robot in config["robots"].items():
        if arguments.robot and name not in arguments.robot:
            continue
        settings = WorkerSettings(
            emr_robot_id=int(robot["emr_robot_id"]),
            blocked_location_ids=frozenset(int(location_id) for location_id in robot.get("blocked_location_ids") or []),
            claim_period_s=float(config.get("claim_period_s", 3.0)),
            navigation_timeout_s=float(config.get("navigation_timeout_s", 180.0)),
            map_wait_s=float(config.get("map_wait_s", 10.0)),
            receipt_debounce_s=float(config.get("receipt_debounce_s", 3.0)),
        )
        emr = RobotEmrClient(config["emr_url"], read_api_key(robot["api_key_file"]))
        ros = RobotRos(name, int(robot.get("ros_domain_id", 0)), robot.get("namespace", ""))
        connections.append(ros)
        navigator = RosNavigator(ros)
        navigators.append(navigator)
        worker = DeliveryWorker(name, emr, navigator, RosMarkers(ros), settings, stop_event=stop_event)
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
        log.info("멈춥니다 — 진행 중 주행 목표를 취소합니다 (맡던 배송은 다음 시작 때 이어서)")
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
