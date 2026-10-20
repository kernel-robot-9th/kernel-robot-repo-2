# =============================================================================
# 파일   : delivery_executor/logic.py
# 역할   : 배송 실행 상태 기계 (ROS·HTTP를 직접 모른다 — 주행기·마커·EMR을 주입받아 테스트한다)
# 작성일 : 2026-10-20
# 구성   :
#   - compare_maps()      EMR 맵과 로봇 /map이 같은지 (test_waypoint/test_waypoint.py에서 옮김)
#   - Navigator / MarkerSource / Emr   주입 인터페이스 (Protocol)
#   - WorkerSettings      설정값
#   - DeliveryWorker      로봇 한 대의 반복: 복구 → claim → 주행 → 도착 → 마커 대기 → 수령/미수령 → 복귀
# 계약: dev_ws/docs/api_contract_delivery_2026-10-20.md 4장
# =============================================================================
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from delivery_executor.emr_client import EmrResponse, EmrUnavailable

NAV_SUCCEEDED = "succeeded"

MAP_RESOLUTION_TOLERANCE = 1e-6
MAP_ORIGIN_TOLERANCE_M = 0.005
MAP_YAW_TOLERANCE_RAD = 0.001


def angle_difference_rad(first_rad: float, second_rad: float) -> float:
    """두 각의 차이(-π~π). [입력] first_rad, second_rad [출력] float"""
    return math.atan2(math.sin(first_rad - second_rad), math.cos(first_rad - second_rad))


def compare_maps(emr_map: dict[str, Any], robot_map: dict[str, Any] | None) -> list[str]:
    """EMR 맵과 로봇 Nav2 맵이 같은 파일에서 나왔는지 해상도·원점·크기로 비교한다.
    [입력] emr_map: GET /maps/{id} / robot_map: {width, height, resolution, origin{x, y, yaw}} 또는 None
    [출력] list[str]: 다른 점 (빈 목록이면 같음)
    """
    if robot_map is None:
        return ["로봇 /map을 받지 못했습니다(Nav2 map_server가 떠 있는지, 도메인 번호가 맞는지 확인)."]
    problems = []
    if abs(float(robot_map["resolution"]) - float(emr_map["resolution_m_per_pixel"])) > MAP_RESOLUTION_TOLERANCE:
        problems.append(f"해상도 EMR {emr_map['resolution_m_per_pixel']} / 로봇 {robot_map['resolution']} m/px")
    origin = robot_map["origin"]
    for axis, emr_key in (("x", "origin_x_m"), ("y", "origin_y_m")):
        if abs(float(origin[axis]) - float(emr_map[emr_key])) > MAP_ORIGIN_TOLERANCE_M:
            problems.append(f"원점 {axis} EMR {emr_map[emr_key]} / 로봇 {origin[axis]:.3f} m")
    if abs(angle_difference_rad(float(origin["yaw"]), float(emr_map["origin_yaw_rad"]))) > MAP_YAW_TOLERANCE_RAD:
        problems.append(f"원점 방향 EMR {emr_map['origin_yaw_rad']} / 로봇 {origin['yaw']:.3f} rad")
    if emr_map.get("image_width_px") is not None:
        emr_size = (int(emr_map["image_width_px"]), int(emr_map["image_height_px"]))
        robot_size = (int(robot_map["width"]), int(robot_map["height"]))
        if emr_size != robot_size:
            problems.append(f"크기 EMR {emr_size[0]}x{emr_size[1]} / 로봇 {robot_size[0]}x{robot_size[1]} px")
    return problems


class Navigator(Protocol):
    def navigate(self, x_m: float, y_m: float, yaw_rad: float, timeout_s: float) -> str:
        """목표까지 주행. [출력] 'succeeded' | 'aborted' | 'canceled' | 'rejected' | 'timeout' | 'unavailable'"""

    def robot_map(self, wait_s: float) -> dict[str, Any] | None:
        """로봇 /map 정보 {width, height, resolution, origin{x,y,yaw}} (없으면 None)"""


class MarkerSource(Protocol):
    def wait_marker(self, timeout_s: float) -> int | None:
        """카메라가 읽은 마커 번호 하나를 기다린다 (없으면 None)"""

    def clear(self) -> None:
        """쌓인 번호를 버린다 (도착 전 것을 쓰지 않게)"""


class Emr(Protocol):
    def me(self) -> EmrResponse: ...
    def claim(self) -> EmrResponse: ...
    def progress(self, delivery_id: int, stage: str, failure_reason: str | None = None) -> EmrResponse: ...
    def receipt(self, delivery_id: int, aruco_marker_id: int) -> EmrResponse: ...
    def get_map(self, map_id: int) -> EmrResponse: ...


@dataclass
class WorkerSettings:
    emr_robot_id: int
    blocked_location_ids: frozenset[int] = frozenset()
    claim_period_s: float = 3.0
    navigation_timeout_s: float = 180.0
    map_wait_s: float = 10.0
    receipt_debounce_s: float = 3.0
    retry_after_error_s: float = 5.0


@dataclass
class WorkerState:
    """밖에서 볼 수 있는 상태 (로그·테스트용)."""
    phase: str = "starting"               # starting | idle | navigating | waiting_receipt | returning | halted | stopped
    home: dict[str, Any] | None = None
    map_ok: bool = False
    halted_reason: str | None = None
    finished: list[tuple[int, str]] = field(default_factory=list)   # (배송 id, received|failed:사유)


def _parse_time(iso: str) -> float:
    """ISO 8601(Z 포함) → epoch 초."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class DeliveryWorker:
    """로봇 한 대의 배송 반복. run()은 stop_event가 설 때까지 돈다."""

    def __init__(self, name: str, emr: Emr, navigator: Navigator, markers: MarkerSource, settings: WorkerSettings,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
                 stop_event: threading.Event | None = None) -> None:
        self.name = name
        self.emr = emr
        self.navigator = navigator
        self.markers = markers
        self.settings = settings
        self.sleep = sleep
        self.clock = clock
        self.stop_event = stop_event or threading.Event()
        self.state = WorkerState()
        self.log = logging.LoggerAdapter(logging.getLogger("delivery_executor"), {"robot": name})

    # ---- 바깥 반복 ------------------------------------------------------------

    def run(self, max_cycles: int | None = None) -> WorkerState:
        """[입력] max_cycles: 테스트용 반복 횟수 제한 (None이면 stop까지) [출력] WorkerState"""
        cycles = 0
        while not self.stop_event.is_set() and self.state.phase != "halted":
            if max_cycles is not None and cycles >= max_cycles:
                break
            cycles += 1
            try:
                self.step()
            except EmrUnavailable as error:
                self.log.warning("EMR 연결 실패, %.0f초 뒤 다시: %s", self.settings.retry_after_error_s, error)
                self.sleep(self.settings.retry_after_error_s)
        if self.state.phase != "halted":
            self.state.phase = "stopped"
        return self.state

    def step(self) -> None:
        """한 번: (처음이면 준비·복구) → claim → 배송 처리. 맡을 것이 없으면 claim 주기만큼 쉰다."""
        if self.state.phase == "starting":
            if not self._prepare():
                self.sleep(self.settings.claim_period_s)
                return
            if self.state.phase == "starting":   # 이어서 처리한 배송이 멈춤(halted)을 남겼으면 덮어쓰지 않는다
                self.state.phase = "idle"
            return
        response = self.emr.claim()
        if response.status == 204:
            self.sleep(self.settings.claim_period_s)
            return
        if response.status == 409 and response.code == "robot_home_not_set":
            self.log.warning("EMR에 복귀 장소가 없어졌습니다 — 다시 준비합니다")
            self.state.phase = "starting"
            return
        if response.status != 200:
            self.log.error("claim 거부 HTTP %s %s — %.0f초 뒤 다시", response.status, response.body, self.settings.retry_after_error_s)
            self.sleep(self.settings.retry_after_error_s)
            return
        self.handle_delivery(response.body)

    # ---- 준비 -----------------------------------------------------------------

    def _prepare(self) -> bool:
        """/robot/me로 로봇·복귀 장소 확인, 맵 비교, 맡고 있던 배송 이어서.
        [출력] bool: 배송을 맡을 수 있으면 True
        """
        response = self.emr.me()
        if response.status != 200:
            self.log.error("/robot/me 실패 HTTP %s %s (키 확인)", response.status, response.body)
            return False
        me = response.body
        if me["robot"]["id"] != self.settings.emr_robot_id:
            self._halt(f"키가 다른 로봇 것입니다: EMR 로봇 {me['robot']['id']}({me['robot']['name']}), 설정 {self.settings.emr_robot_id}")
            return False
        home = me["home_location"]
        if home is None:
            self.log.warning("복귀 장소가 없습니다 — EMR 로봇 탭에서 좌표 있는 장소를 고르세요. 기다립니다")
            return False
        self.state.home = home
        if not self.state.map_ok:
            map_response = self.emr.get_map(home["map_id"])
            if map_response.status != 200:
                self.log.error("EMR 맵 %s 조회 실패 HTTP %s", home["map_id"], map_response.status)
                return False
            problems = compare_maps(map_response.body, self.navigator.robot_map(self.settings.map_wait_s))
            if problems:
                self.log.error("로봇 맵이 EMR 맵과 다릅니다 — 배송을 맡지 않습니다: %s", "; ".join(problems))
                return False
            self.state.map_ok = True
            self.log.info("준비 완료: 복귀 장소 %s, 맵 %s 일치", home["name"], map_response.body["name"])
        active = me.get("active_delivery")
        if active is not None:
            self.log.info("맡고 있던 배송 %s(%s)을 이어서 합니다", active["id"], active["status"])
            self.state.phase = "idle"
            self.handle_delivery(active)
        return True

    # ---- 배송 한 건 -------------------------------------------------------------

    def handle_delivery(self, delivery: dict[str, Any]) -> None:
        """dispatched면 주행부터, arrived면 수령 대기부터. 끝나면 복귀.
        [입력] delivery: 로봇용 배송 JSON (RobotDeliveryOut)
        """
        delivery_id = delivery["id"]
        destination = delivery["destination"]
        self.log.info("배송 %s → %s (%s)", delivery_id, destination["name"], delivery["status"])

        if delivery["status"] == "dispatched":
            if destination["id"] in self.settings.blocked_location_ids:
                self.log.warning("배송 %s: %s은(는) 금지 장소 — 움직이지 않고 실패 보고", delivery_id, destination["name"])
                self._report_failed(delivery_id, "destination_blocked")
                return   # 움직이지 않았으니 복귀도 없다
            self.state.phase = "navigating"
            result = self.navigator.navigate(destination["map_x_m"], destination["map_y_m"], destination["map_yaw_rad"],
                                             self.settings.navigation_timeout_s)
            if self.stop_event.is_set():
                # 실행기를 멈추느라 취소된 주행 — 실패로 보고하지 않는다. EMR에 dispatched로 남아 다음 시작 때 이어서 한다
                self.log.info("배송 %s: 실행기 종료로 주행을 멈췄습니다 (다음 시작 때 이어서)", delivery_id)
                return
            if result != NAV_SUCCEEDED:
                self.log.warning("배송 %s: 목적지 주행 실패(%s)", delivery_id, result)
                self._report_failed(delivery_id, "navigation_failed")
                self._go_home()
                return
            self.markers.clear()   # 도착 전에 읽힌 번호는 쓰지 않는다
            response = self.emr.progress(delivery_id, "arrived")
            if response.status != 200:
                self.log.error("배송 %s: 도착 보고 거부 HTTP %s %s", delivery_id, response.status, response.body)
                self._go_home()
                return
            delivery = response.body

        if delivery["status"] == "arrived":
            received = self._wait_for_receipt(delivery_id, delivery.get("receipt_deadline_at"))
            if self.stop_event.is_set() and not received:
                self.log.info("배송 %s: 실행기 종료 — 수령 대기를 멈춥니다 (다음 시작 때 남은 시간만큼 이어서)", delivery_id)
                return
            if received:
                self.state.finished.append((delivery_id, "received"))
                self.log.info("배송 %s 수령 완료", delivery_id)
            else:
                self._report_failed(delivery_id, "not_received")
        self._go_home()

    def _wait_for_receipt(self, delivery_id: int, deadline_iso: str | None) -> bool:
        """마감까지 마커를 기다려 EMR에 보낸다. 같은 번호는 receipt_debounce_s에 한 번만.
        [출력] bool: 수령되면 True
        """
        self.state.phase = "waiting_receipt"
        deadline = _parse_time(deadline_iso) if deadline_iso else self.clock() + 300.0
        last_sent: dict[int, float] = {}
        self.log.info("배송 %s: 수령 마커를 기다립니다 (마감까지 %.0f초)", delivery_id, max(0.0, deadline - self.clock()))
        while not self.stop_event.is_set():
            remaining = deadline - self.clock()
            if remaining <= 0:
                self.log.info("배송 %s: 수령 시간이 지났습니다", delivery_id)
                return False
            marker = self.markers.wait_marker(min(1.0, remaining))
            if marker is None:
                continue
            now = self.clock()
            if now - last_sent.get(marker, -1e9) < self.settings.receipt_debounce_s:
                continue
            last_sent[marker] = now
            response = self.emr.receipt(delivery_id, marker)
            if response.status == 200:
                return True
            if response.status == 409:   # 이미 끝남(수령·실패) — 더 기다릴 것이 없다
                self.log.info("배송 %s: 더는 도착 상태가 아님 (%s)", delivery_id, response.code)
                return response.code == "delivery_already_received"
            self.log.info("배송 %s: 마커 %s 거부 (%s) — 계속 기다립니다", delivery_id, marker, response.code)
        return False

    def _report_failed(self, delivery_id: int, failure_reason: str) -> None:
        """실패 보고. 그 사이 수령됐으면(409 delivery_already_received) 성공으로 본다."""
        response = self.emr.progress(delivery_id, "failed", failure_reason)
        if response.status == 409 and response.code == "delivery_already_received":
            self.state.finished.append((delivery_id, "received"))
            self.log.info("배송 %s: 실패 보고 직전에 수령되었습니다", delivery_id)
            return
        if response.status != 200:
            self.log.error("배송 %s: 실패 보고 거부 HTTP %s %s", delivery_id, response.status, response.body)
        self.state.finished.append((delivery_id, f"failed:{failure_reason}"))

    def _go_home(self) -> None:
        """복귀 장소로. 실패하면 멈춘다(사람 확인 필요 — 다음 배송을 맡지 않는다)."""
        home = self.state.home
        if home is None:
            self._halt("복귀 장소를 모릅니다")
            return
        self.state.phase = "returning"
        result = self.navigator.navigate(home["map_x_m"], home["map_y_m"], home["map_yaw_rad"], self.settings.navigation_timeout_s)
        if self.stop_event.is_set():
            self.log.info("실행기 종료로 복귀 주행을 멈췄습니다")
            return
        if result != NAV_SUCCEEDED:
            self._halt(f"복귀 주행 실패({result}) — 로봇 위치를 확인하고 실행기를 다시 시작하세요")
            return
        self.state.phase = "idle"
        self.log.info("복귀 완료: %s", home["name"])

    def _halt(self, reason: str) -> None:
        self.state.phase = "halted"
        self.state.halted_reason = reason
        self.log.error("멈춤: %s", reason)
