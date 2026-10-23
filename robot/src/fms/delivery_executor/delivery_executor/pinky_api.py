# =============================================================================
# 파일   : delivery_executor/pinky_api.py
# 역할   : 팀원 Pinky API(로봇 :8080, Flask)로 주행하는 Navigator — ROS 없이 HTTP만 (2026-10-22)
# 작성일 : 2026-10-22 (팀원 API 이름 변경 반영: /stops → /dests, goto {"stop"} → {"dest"} — 같은 날)
# 구성   :
#   - PinkyApiClient      GET /status · POST /goto · GET /jobs/{id} · POST /cancel (표준 라이브러리, 인증 없음)
#   - PinkyApiNavigator   EMR 장소의 robot_dest(EMR이 알려 줌, 0011) 또는 설정 dests 표 → Pinky 목적지 이름 → start(): goto만 보냄 → poll(): /jobs/{id} 한 번
#                         (비동기 — 실행기 반복이 주행을 기다리느라 막히지 않는다, 2026-10-22)
# 인증: Pinky API에 아직 없다 — 지금은 인증 없이 진행(사용자 결정 2026-10-22). 운영 전에 토큰 헤더를 넣는다
# 좌표: Pinky API는 그림 cm라 EMR 좌표(map m)를 넘기지 않고 목적지 이름만 쓴다
# 분석·제안: dev_ws/docs/pinky_fms_api_review_2026-10-22.md · 계약: dev_ws/docs/api_contract_delivery_2026-10-20.md 4장
# =============================================================================
from __future__ import annotations

import json
import logging
import urllib.parse
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from delivery_executor.logic import NAV_BUSY, NAV_NO_ROUTE, NAV_SUCCEEDED

HTTP_TIMEOUT_S = 5.0
log = logging.getLogger("delivery_executor")

# 작업(job) 끝 상태 → Navigator 결과
JOB_RESULTS = {"succeeded": NAV_SUCCEEDED, "failed": "aborted", "canceled": "canceled"}


class PinkyUnavailable(Exception):
    """Pinky API에 닿지 않음(네트워크·5xx 아닌 연결 실패)."""


@dataclass
class PinkyResponse:
    status: int
    body: Any

    @property
    def error(self) -> str:
        """오류 응답의 error 문장 ({"error": "..."}). [출력] str"""
        return self.body.get("error", "") if isinstance(self.body, dict) else ""


class PinkyApiClient:
    """로봇 한 대의 Pinky API. 4xx·5xx도 PinkyResponse로 돌려주고, 연결 실패만 PinkyUnavailable."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> PinkyResponse:
        """[입력] method / path / body [출력] PinkyResponse"""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                return PinkyResponse(response.status, _json_or_text(response.read()))
        except urllib.error.HTTPError as error:
            return PinkyResponse(error.code, _json_or_text(error.read()))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise PinkyUnavailable(f"{method} {self.base_url}{path}: {error}") from error

    def status(self) -> PinkyResponse:
        return self.request("GET", "/status")

    def goto(self, target: dict[str, Any]) -> PinkyResponse:
        """⚠️ 로봇이 움직인다. [입력] target: {"dest": 이름, "dock": bool} [출력] 202 {job, plan}"""
        return self.request("POST", "/goto", target)

    def plan(self, target: dict[str, Any]) -> PinkyResponse:
        """경로만 계산 (움직이지 않음). [입력] target: {"dest", "dock"} [출력] 200 Plan | 400 못 감"""
        query = urllib.parse.urlencode({"dest": target["dest"], **({"dock": "true"} if target.get("dock") else {})})
        return self.request("GET", f"/plan?{query}")

    def job(self, job_id: str) -> PinkyResponse:
        return self.request("GET", f"/jobs/{job_id}")

    def cancel(self) -> PinkyResponse:
        return self.request("POST", "/cancel")


def _json_or_text(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return {"error": text[:200]}


def parse_dests(raw: dict[Any, Any] | None) -> dict[int, dict[str, Any]]:
    """설정 dests 표 → {EMR 장소 id: {"dest": 이름, "dock": bool}}. 값은 이름 문자열 또는 {dest, dock}.
    [입력] raw: executor.yaml의 dests [출력] dict
    """
    dests: dict[int, dict[str, Any]] = {}
    for location_id, value in (raw or {}).items():
        if isinstance(value, str):
            dests[int(location_id)] = {"dest": value, "dock": False}
        else:
            dests[int(location_id)] = {"dest": str(value["dest"]), "dock": bool(value.get("dock", False))}
    return dests


@dataclass
class PinkyJob:
    """보낸 주행 하나 (PinkyApiNavigator 핸들)."""
    place: dict[str, Any]
    target: dict[str, Any] | None
    busy_until: float
    job_id: str | None = None         # goto가 받아들여지면
    result: str | None = None         # 끝났으면
    segment: int | None = None        # 로그용 — 구간이 바뀔 때만 찍는다


class PinkyApiNavigator:
    """EMR 장소를 Pinky 목적지 이름으로 바꿔 주행한다 — 비동기: start()는 goto만 보내고, poll()이 /jobs/{id}를 한 번 본다.
    실행기가 시작한 작업(job)만 추적·취소한다.
    """

    def __init__(self, client: PinkyApiClient, dests: dict[int, dict[str, Any]], busy_wait_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic, name: str = "-") -> None:
        self.log = logging.LoggerAdapter(log, {"robot": name})
        self.client = client
        self.dests = dests
        self.busy_wait_s = busy_wait_s
        self.clock = clock
        self._current: PinkyJob | None = None
        self._lock = threading.Lock()

    # ---- Navigator ------------------------------------------------------------

    def start(self, place: dict[str, Any]) -> PinkyJob:
        """EMR 장소로 goto를 보낸다(기다리지 않음). [입력] place: EMR 장소 JSON(id·name) [출력] PinkyJob"""
        handle = PinkyJob(place, self._target(place), self.clock() + self.busy_wait_s)
        if handle.target is None:
            self.log.warning("장소 %s(%s)에 Pinky 목적지가 없습니다 (EMR 장소의 로봇 목적지·설정 dests 둘 다 없음)", place["id"], place.get("name"))
            handle.result = NAV_NO_ROUTE   # 움직이지 않는다
            return handle
        if self._already_there(handle):
            return handle
        with self._lock:
            self._current = handle
        self._try_goto(handle)
        return handle

    def poll(self, handle: PinkyJob) -> str | None:
        """한 번 확인. [출력] None = 가는 중(또는 다른 작업이 끝나길 기다리는 중) / succeeded | aborted | canceled | no_route | busy | unavailable"""
        if handle.result is None and handle.job_id is None:
            self._try_goto(handle)          # 409(다른 작업 중)였으면 다시 보낸다
        elif handle.result is None:
            self._check_job(handle)
        if handle.result is not None:
            with self._lock:
                if self._current is handle:
                    self._current = None
        return handle.result

    def cancel(self, handle: PinkyJob) -> None:
        """그 작업이 진행 중이면 POST /cancel (제한 시간 초과·실행기 종료)."""
        if handle.job_id is None or handle.result is not None:
            handle.result = handle.result or "canceled"
            return
        self.log.info("Pinky 작업 %s를 취소합니다", handle.job_id)
        try:
            self.client.cancel()
        except PinkyUnavailable as error:
            self.log.error("Pinky 작업 취소 실패: %s", error)
        handle.result = "canceled"

    def cancel_current(self) -> None:
        """실행기가 시작한 작업이 진행 중이면 멈춘다 (실행기 종료 때 로봇을 세운다)."""
        with self._lock:
            handle = self._current
        if handle is not None:
            self.cancel(handle)

    def robot_map(self, wait_s: float) -> dict[str, Any] | None:
        """Pinky API에는 맵 정보가 없다 — 실행기 설정 check_map: false로 맵 비교를 건너뛴다."""
        return None

    def not_ready_reason(self) -> str | None:
        """배송을 맡기 전 확인: 위치 추정·Nav2·다른 작업. [출력] 맡으면 안 되는 이유 (괜찮으면 None)"""
        try:
            response = self.client.status()
        except PinkyUnavailable as error:
            return f"Pinky API 연결 실패: {error}"
        if response.status != 200:
            return f"Pinky /status HTTP {response.status} {response.error}"
        status = response.body
        if not status.get("localized"):
            return "로봇 위치 모름 — Pinky /set_pose로 시작 위치를 넣으세요"
        if not status.get("nav2_ready"):
            return "Pinky Nav2 준비 안 됨"
        if status.get("state") != "idle":
            job = status.get("job") or {}
            return f"Pinky가 다른 작업 중 ({job.get('id', '?')})"
        return None

    # ---- 내부 -----------------------------------------------------------------

    def _target(self, place: dict[str, Any]) -> dict[str, Any] | None:
        """목적지: 설정 dests 표(정밀 주차 등 덮어쓰기)가 먼저, 없으면 EMR 장소의 robot_dest (2026-10-22).
        [입력] place [출력] {"dest", "dock"} | None
        """
        configured = self.dests.get(int(place["id"]))
        if configured is not None:
            return configured
        if place.get("robot_dest"):
            return {"dest": place["robot_dest"], "dock": False}
        return None

    def _already_there(self, handle: PinkyJob) -> bool:
        """GET /plan으로 갈 거리가 없으면(구간 0개) goto 없이 도착으로 본다 — 이미 복귀 장소에 있을 때 등.
        /plan이 안 되면(연결·404) 판단하지 않고 goto로 넘긴다. [출력] bool: 이미 도착
        """
        try:
            response = self.client.plan(handle.target)
        except PinkyUnavailable:
            return False
        if response.status == 200 and not (response.body or {}).get("segments"):
            self.log.info("이미 %s(%s)에 있습니다 — 주행 없이 도착", handle.target["dest"], handle.place.get("name"))
            handle.result = NAV_SUCCEEDED
            return True
        return False

    def _try_goto(self, handle: PinkyJob) -> None:
        """goto를 보낸다. 202면 job id, 400이면 no_route, 409면 busy_until까지 다음 poll에서 다시, 그 밖은 unavailable."""
        target, place = handle.target, handle.place
        try:
            response = self.client.goto(target)
        except PinkyUnavailable as error:
            self.log.error("Pinky goto 실패: %s", error)
            handle.result = "unavailable"
            return
        if response.status in (200, 202):
            job = (response.body or {}).get("job")
            handle.job_id = str(job["id"] if isinstance(job, dict) else job)   # 202 {job: Job, plan}
            self.log.info("Pinky 주행 시작: %s → %s (작업 %s)", place.get("name"), target["dest"], handle.job_id)
        elif response.status == 400:
            self.log.warning("Pinky가 %s(%s)로 갈 수 없다고 합니다: %s", target["dest"], place.get("name"), response.error)
            handle.result = NAV_NO_ROUTE
        elif response.status == 409 and self.clock() < handle.busy_until:
            self.log.info("Pinky가 다른 작업 중 — 끝나면 보냅니다: %s", response.error)
        elif response.status == 409:
            handle.result = NAV_BUSY
        else:
            self.log.error("Pinky goto 거부 HTTP %s %s", response.status, response.error)
            handle.result = "unavailable"

    def _check_job(self, handle: PinkyJob) -> None:
        """GET /jobs/{id} 한 번. 끝났으면 handle.result를 채운다. 연결이 잠깐 끊기면 다음 poll에서 다시."""
        try:
            response = self.client.job(handle.job_id)
        except PinkyUnavailable as error:
            self.log.warning("Pinky 작업 %s 확인 실패 (다음에 다시): %s", handle.job_id, error)
            return
        if response.status == 404:
            self.log.error("Pinky 작업 %s가 없어졌습니다 (로봇 API 재시작?)", handle.job_id)
            handle.result = "aborted"
            return
        if response.status != 200:
            return
        job = response.body or {}
        state = job.get("state")
        if state == "running":
            if job.get("segment") != handle.segment:
                handle.segment = job.get("segment")
                self.log.info("Pinky 작업 %s 구간 %s/%s", handle.job_id, handle.segment, job.get("segments_total"))
            return
        if state in JOB_RESULTS:
            if state == "succeeded":
                error = job.get("dock_error") or f"{job.get('end_error_cm')} cm"   # 정밀 주차면 dock_error {fwd_mm, left_mm, heading_deg}
                self.log.info("Pinky 작업 %s 도착 (오차 %s, %s초)", handle.job_id, error, job.get("time_s"))
            else:
                why = [result.get("why") for result in job.get("results") or [] if result.get("status") != "ok"]
                self.log.warning("Pinky 작업 %s %s: %s %s", handle.job_id, state, job.get("error") or "", "; ".join(filter(None, why)))
            handle.result = JOB_RESULTS[state]
