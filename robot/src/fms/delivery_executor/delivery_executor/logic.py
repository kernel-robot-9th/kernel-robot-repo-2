# =============================================================================
# 파일   : delivery_executor/logic.py
# 역할   : 배송 실행 상태 기계 (ROS·HTTP를 직접 모른다 — 주행기·마커·EMR을 주입받아 테스트한다)
# 작성일 : 2026-10-20
# 구성   :
#   - compare_maps()      EMR 맵과 로봇 /map이 같은지 (test_waypoint/test_waypoint.py에서 옮김)
#   - Navigator / MarkerSource / Emr   주입 인터페이스 (Protocol). 주행기는 ROS Nav2(ros_io) 또는 Pinky API(pinky_api, 2026-10-22)
#   - NoMarkers           마커를 읽지 않는 MarkerSource — 마커는 일단 끔(2026-10-22), 수령은 "받았습니다" 버튼 → /robot/me
#   - WorkerSettings      설정값
#   - DeliveryWorker      로봇 한 대의 반복: 복구 → claim → 주행 → 도착 → 수령 대기 → 수령/미수령 → 복귀
#                         주행은 비동기(2026-10-22): start()로 보내고 반복마다 poll() — 기다리느라 반복을 막지 않는다
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
NAV_NO_ROUTE = "no_route"   # 갈 수 없는 목적지 (Pinky 목적지 표에 없음·Pinky가 거부) — 움직이지 않았다
NAV_BUSY = "busy"           # 로봇이 다른 작업 중 (Pinky 409) — 움직이지 않았다

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
    """주행기 — 보내고(start) 반복마다 확인(poll)한다. 기다리느라 실행기 반복을 막지 않는다 (2026-10-22)."""

    def start(self, place: dict[str, Any]) -> Any:
        """EMR 장소(id·name·map_x_m·map_y_m·map_yaw_rad)로 주행을 보낸다. [출력] 핸들 (poll·cancel에 넘김)"""

    def poll(self, handle: Any) -> str | None:
        """[출력] None = 아직 가는 중 / 'succeeded' | 'aborted' | 'canceled' | 'rejected' | 'unavailable' | 'no_route' | 'busy'"""

    def cancel(self, handle: Any) -> None:
        """그 주행을 멈춘다 (제한 시간을 넘겼을 때)."""

    def robot_map(self, wait_s: float) -> dict[str, Any] | None:
        """로봇 /map 정보 {width, height, resolution, origin{x,y,yaw}} (없으면 None)"""

    # 선택: not_ready_reason() -> str | None — 있으면 claim 전에 불러, 이유가 있으면 배송을 맡지 않는다 (Pinky API)
    # 실행기 종료 때 main이 cancel_current()로 진행 중 주행을 멈춘다


class MarkerSource(Protocol):
    def wait_marker(self, timeout_s: float) -> int | None:
        """카메라가 읽은 마커 번호 하나를 기다린다 (없으면 None)"""

    def clear(self) -> None:
        """쌓인 번호를 버린다 (도착 전 것을 쓰지 않게)"""


class NoMarkers:
    """마커를 읽지 않는다 (2026-10-22, 사용자 결정: 마커는 일단 끔). 수령은 간호사·환자의 "받았습니다" → /robot/me 확인."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    def wait_marker(self, timeout_s: float) -> int | None:
        self.sleep(max(0.0, timeout_s))
        return None

    def clear(self) -> None:
        return None


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
    navigation_timeout_s: float | None = None   # 주행 한 번의 제한 시간. None = 없음(로봇 작업이 끝날 때까지, 2026-10-22 사용자 결정)
    navigation_poll_s: float = 1.0    # 주행 중 확인 주기 (Pinky: GET /jobs/{id})
    map_wait_s: float = 10.0
    receipt_debounce_s: float = 3.0
    receipt_poll_s: float = 2.0       # 수령 대기 중 /robot/me를 확인하는 주기 — "받았습니다" 버튼 수령을 알아차림 (2026-10-22)
    check_map: bool = True            # 로봇 /map과 EMR 맵 비교 (Pinky API는 맵 정보가 없어 False)
    retry_after_error_s: float = 5.0


@dataclass
class PendingNavigation:
    """보내 놓고 아직 끝나지 않은 주행 하나."""
    purpose: str                      # destination | home
    place: dict[str, Any]
    handle: Any
    started_at: float
    delivery_id: int | None = None


@dataclass
class WorkerState:
    """밖에서 볼 수 있는 상태 (로그·테스트용)."""
    phase: str = "starting"               # starting | idle | navigating | waiting_receipt | returning | halted | stopped
    home: dict[str, Any] | None = None
    map_ok: bool = False
    halted_reason: str | None = None
    navigation: PendingNavigation | None = None   # 가는 중인 주행 (비동기 — 반복마다 poll)
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
        self._last_not_ready: str | None = None   # 같은 '못 맡는 이유'를 3초마다 로그에 찍지 않으려고

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
        """한 번: (처음이면 준비·복구) → 가는 중인 주행이 있으면 확인만 → 없으면 claim → 배송 처리.
        맡을 것이 없으면 claim 주기만큼, 가는 중이면 navigation_poll_s만큼 쉰다.
        """
        if self.state.phase == "starting":
            if not self._prepare():
                self.sleep(self.settings.claim_period_s)
                return
            if self.state.phase == "starting":   # 이어서 처리한 배송이 멈춤(halted)을 남겼으면 덮어쓰지 않는다
                self.state.phase = "idle"
            return
        if self.state.navigation is not None:
            self._poll_navigation()
            return
        reason = self._not_ready_reason()
        if reason is not None:
            self.sleep(self.settings.claim_period_s)
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
        if not self.settings.check_map and not self.state.map_ok:
            self.state.map_ok = True
            self.log.info("준비 완료: 복귀 장소 %s (맵 비교 안 함 — check_map: false)", home["name"])
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
        """dispatched면 주행을 보내고(끝은 _poll_navigation에서), arrived면 수령 대기부터.
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
            self._start_navigation("destination", destination, delivery_id)
        elif delivery["status"] == "arrived":
            self._handle_arrived(delivery)

    def _start_navigation(self, purpose: str, place: dict[str, Any], delivery_id: int | None = None) -> None:
        """주행을 보내고 바로 돌아온다 — 끝났는지는 다음 반복부터 _poll_navigation이 본다.
        [입력] purpose: destination | home / place: EMR 장소 / delivery_id
        """
        self.state.phase = "navigating" if purpose == "destination" else "returning"
        handle = self.navigator.start(place)
        self.state.navigation = PendingNavigation(purpose, place, handle, self.clock(), delivery_id)

    def _poll_navigation(self) -> None:
        """가는 중인 주행을 한 번 확인. 끝났으면 다음 단계(도착 보고·복귀 결과)로, 아니면 navigation_poll_s 쉼.
        제한 시간(navigation_timeout_s)이 있고 넘었으면 멈추고 timeout으로 본다.
        """
        navigation = self.state.navigation
        result = self.navigator.poll(navigation.handle)
        if result is None:
            limit = self.settings.navigation_timeout_s
            if limit is None or self.clock() - navigation.started_at < limit:
                self.sleep(self.settings.navigation_poll_s)
                return
            self.log.warning("%s 주행 시간 초과 %.0f초 — 멈춤", navigation.place["name"], limit)
            self.navigator.cancel(navigation.handle)
            result = "timeout"
        self.state.navigation = None
        if navigation.purpose == "destination":
            self._on_destination_result(navigation, result)
        else:
            self._on_home_result(result)

    def _on_destination_result(self, navigation: PendingNavigation, result: str) -> None:
        """목적지 주행 결과 → 도착 보고 + 수령 대기, 또는 실패 보고 + 복귀."""
        delivery_id = navigation.delivery_id
        if result in (NAV_NO_ROUTE, NAV_BUSY):
            # 움직이지 않았으니 복귀도 없다. 갈 수 없는 곳은 금지 장소와 같은 사유로
            self.log.warning("배송 %s: %s(으)로 출발하지 못했습니다(%s)", delivery_id, navigation.place["name"], result)
            self._report_failed(delivery_id, "destination_blocked" if result == NAV_NO_ROUTE else "robot_error")
            self.state.phase = "idle"
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
        self._handle_arrived(response.body)

    def _handle_arrived(self, delivery: dict[str, Any]) -> None:
        """도착한 배송: 수령을 기다리고(받았습니다·마커·마감) 복귀를 보낸다."""
        delivery_id = delivery["id"]
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
        receipt_poll_s마다 /robot/me도 확인한다 — 맡은 배송이 없어졌으면 EMR에서 수령된 것(병상 배송의 "받았습니다" 버튼, 2026-10-22).
        [출력] bool: 수령되면 True
        """
        self.state.phase = "waiting_receipt"
        deadline = _parse_time(deadline_iso) if deadline_iso else self.clock() + 300.0
        last_sent: dict[int, float] = {}
        next_poll = self.clock() + self.settings.receipt_poll_s
        self.log.info("배송 %s: 수령을 기다립니다 (마감까지 %.0f초)", delivery_id, max(0.0, deadline - self.clock()))
        while not self.stop_event.is_set():
            remaining = deadline - self.clock()
            if remaining <= 0:
                self.log.info("배송 %s: 수령 시간이 지났습니다", delivery_id)
                return False
            if self.clock() >= next_poll:
                next_poll = self.clock() + self.settings.receipt_poll_s
                if self._received_elsewhere(delivery_id):
                    return True
            marker = self.markers.wait_marker(min(1.0, remaining, max(0.0, next_poll - self.clock())))
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

    def _received_elsewhere(self, delivery_id: int) -> bool:
        """EMR에서 이 배송이 이미 끝났는지 (/robot/me의 맡은 배송이 없거나 다른 배송). EMR이 안 되면 False로 계속 기다린다.
        [입력] delivery_id
        [출력] bool
        """
        try:
            response = self.emr.me()
        except EmrUnavailable as error:
            self.log.warning("배송 %s: 수령 확인용 /robot/me 실패 (%s) — 계속 기다립니다", delivery_id, error)
            return False
        if response.status != 200:
            return False
        active = (response.body or {}).get("active_delivery")
        if active is None or active.get("id") != delivery_id:
            self.log.info("배송 %s: EMR에서 수령됨 (받았습니다 버튼)", delivery_id)
            return True
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
        """복귀 장소로 주행을 보낸다 (결과는 _on_home_result)."""
        home = self.state.home
        if home is None:
            self._halt("복귀 장소를 모릅니다")
            return
        self._start_navigation("home", home)

    def _on_home_result(self, result: str) -> None:
        """복귀 결과. 실패하면 멈춘다(사람 확인 필요 — 다음 배송을 맡지 않는다)."""
        if result != NAV_SUCCEEDED:
            self._halt(f"복귀 주행 실패({result}) — 로봇 위치를 확인하고 실행기를 다시 시작하세요")
            return
        self.state.phase = "idle"
        self.log.info("복귀 완료: %s", self.state.home["name"])

    def _not_ready_reason(self) -> str | None:
        """주행기가 지금 배송을 맡으면 안 되는 이유 (Pinky API: 위치 모름·Nav2 안 됨·다른 작업 중). 같은 이유는 한 번만 로그.
        [출력] str | None
        """
        check = getattr(self.navigator, "not_ready_reason", None)
        reason = check() if check is not None else None
        if reason != self._last_not_ready:
            if reason is not None:
                self.log.warning("배송을 맡지 않고 기다립니다: %s", reason)
            else:
                self.log.info("로봇 준비됨 — 배송을 다시 맡습니다")
            self._last_not_ready = reason
        return reason

    def _halt(self, reason: str) -> None:
        self.state.phase = "halted"
        self.state.halted_reason = reason
        self.log.error("멈춤: %s", reason)
