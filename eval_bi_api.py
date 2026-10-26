"""command 수신 -> 모델 실행 -> 왼쪽 복귀 -> 완료 통신.

실행 (상대 주소를 실제 수신 URL로 변경):
  conda activate main_project
  python eval_bi_api.py --host 0.0.0.0 --port 8000 \
      --callback-url http://RECEIVER_IP:9000/robot/result

외부 -> 이 서버:
  POST /command {"command": "pick and place blue gauze", "request_id": "cycle-001"}
  POST /return  {"gripper_open": true, "request_id": "cycle-001"}
  POST /pinky   {"pinky_arrive": true 또는 false}  (계속 보내도 됨)
  GET /end-point -> {"end_point": false 또는 true}
  GET /status    -> 이동 상태와 전송 결과

이 서버 -> callback-url:
  이동/도착 확인 성공: POST {"end_point": true}
  이동 실패:          POST {"end_point": false}
  pinky 집기 결과:     POST {"pinky_done": true 또는 false}
  pinky 후 양팔 복귀:  POST {"end_point": true 또는 false}
  헤더 X-Request-ID에 요청 ID 포함. 재전송 시 수신 측에서 같은 ID를 중복 처리하지 마세요.

request_id는 작업마다 새 값, HTTP 재시도에는 같은 값을 사용합니다.
중복 ID는 이 서버 실행 동안 다시 이동하지 않습니다. 재시작하면 기록은 초기화됩니다.
진행 중 다른 요청은 409. gripper_open=false는 이동시키지 않으며 정지 명령도 아닙니다.
end_point는 '최근 작업에서 시작 위치 도착을 확인했다'는 결과이며, 토크 해제 후
손으로 옮겼을 때의 현재 위치를 실시간으로 나타내지는 않습니다.

기존 test_left_return_once.py의 검증된 동작을 재사용합니다:
왼쪽만 현재 -> 경유(6초) -> 시작(6초), 완료 후 토크 OFF.
평가/텔레옵과 동시에 실행하지 마세요. 포트 점유 시 이동을 거부합니다.
서버 시작 자체로는 로봇을 움직이지 않습니다. callback-url 없이도 조회/동작은
가능하지만 외부 전송은 disabled로 표시됩니다.
단일 프로세스로 실행하세요 (workers=1, reload 사용 금지).
서버 종료 시 진행 중 작업과 결과 전송이 끝날 때까지 기다립니다.
실제 개방 감지는 호출 측 담당이며 0.4초 반응 시간을 보장하는 서버가 아닙니다.

모델 서버 실행:
  python eval_bi_api.py --policy-path ~/main_project/outputs/train/smolvla_bi_gauze_v2/checkpoints/last/pretrained_model \
      --task "pick and place blue gauze" --episode-time 30 --top-exposure 90 --host 0.0.0.0
eval_bi.py의 옵션을 그대로 받습니다. --task는 호환용이며 수신 command가 항상 우선합니다.
POST /command가 오기 전에는 모델/로봇을 실행하지 않습니다.
모델과 가중치는 서버를 켤 때 먼저 로드하고, command가 오면 바로 실행합니다. 실행 중 POST /return은 같은 제어 루프에
복귀 이벤트를 전달합니다. request_id를 생략하거나 현재 작업 ID와 맞춰 보내세요.
--start-version v5이고 command에 task_start_poses.json의 키워드(예: "green")가 있으면
모델 실행 전에 왼팔을 현재 -> 그 task의 경유 -> 시작 자세로 먼저 옮긴 뒤 모델을 돌립니다.
--start-version v4(기본)는 이동 없이 원래 시작 자세에서 바로 모델을 돌립니다.
command에 "|"가 있으면 stage 문장 목록으로 보고 첫 문장부터 실행합니다. 예:
  {"command": "search for the green gauze|grasp the green gauze|put the gauze in the box"}
다음 stage로 넘어가는 조건 (--stage-switch, 기본 space; gripper/both로 그리퍼 조건 사용):
  왼쪽 그리퍼 명령이 열리면 search -> grasp, 다시 닫히면 grasp -> carry (학습 라벨과 같은 규칙),
  서버 터미널에서 스페이스, 또는 POST /next-stage. /status의 stage, stage_text로 현재 단계 확인.
마지막 stage에서 스페이스 / POST /next-stage를 한 번 더 하면 모델을 끝내고 복귀합니다
(return_reason = "next_stage").
마지막 stage에서 그리퍼가 다시 열리면(박스에 놓음) 0.5초 뒤 모델을 끝내고 복귀합니다
(--no-end-on-release로 끄기). /status return_reason = "released".
평가 시간 종료 시에도 복귀합니다. --return-on time이면 개방 신호는 받지 않고
--episode-time이 끝날 때만 경유 -> 시작 자세로 복귀합니다 (테스트용). /status의
return_reason에 "gripper_open" 또는 "time"으로 복귀 이유가 남습니다. --no-return/--dry-run/복수 episodes는 API에서 금지합니다.

POST /pinky {"pinky_arrive": true/false}: 최신 값을 기억합니다 (계속 보내도 됩니다).
흐름 (pinky_sequence.json, 양팔 동시):
  모델 종료 -> 왼팔 경유 -> 시작 자세 -> 콜백 {"end_point": true}
  -> 바로 양팔 위로 접근 -> above_target(그리퍼 열면서) -> 닫기 -> lift 후 들고 대기
  -> pinky_arrive=true가 오면 그리퍼 열기 -> 콜백 {"pinky_done": true}
  -> 양팔 경유 -> 시작 자세(그리퍼 닫으면서) -> 콜백 {"end_point": true}
pinky_arrive=true가 lift 전에 와도 기억했다가 lift가 끝나면 바로 엽니다. false가 오면 지웁니다.
/status의 pinky: grabbing -> holding(대기) -> releasing -> returning -> completed.
들고 대기하는 동안 토크는 켜져 있고 시간 제한은 없습니다.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import fcntl
import logging
import os
import subprocess
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


TASK_START_POSES = Path(__file__).with_name("task_start_poses.json")
START_VERSION = "v4"  # --start-version: v4 = model runs from the normal start pose, v5 = colour pre-move


def task_start_poses(command, path=TASK_START_POSES, version=None):
    """(key, via, start, time) for the first key word found in the command, else None."""
    import json
    if not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text())
    version = version or START_VERSION
    versions = data.get("versions", {"v5": {"tasks": data.get("tasks", {})}})
    if version not in versions:
        raise RuntimeError(f"start version {version!r} not in {path} ({', '.join(versions)})")
    tasks = versions[version].get("tasks", {})
    for key, entry in tasks.items():
        if key.lower() in command.lower():
            if entry.get("placeholder", True) or entry.get("via") is None or entry.get("start") is None:
                raise RuntimeError(f"'{key}' start pose is not measured yet ({path}); no motion performed")
            return key, list(entry["via"]), list(entry["start"]), float(entry.get("time", 4.0))
    return None


TASK_PRESETS = Path(__file__).with_name("task_presets.json")


def load_presets(path=TASK_PRESETS):
    import json
    return json.loads(Path(path).read_text()).get("presets", {}) if Path(path).exists() else {}


class PolicyRunner:
    """One worker owns the policy, cameras and motor ports for the whole cycle."""
    def __init__(self, args):
        self.args = args
        self.loaded = None
        self.last_end_reason = None  # "time", "released" (gripper opened in the last stage), "gripper_open"
        self.next_stage = None  # set by the controller: () -> number of API next-stage requests
        self.on_stage = None    # set by the controller: (index, sentence) -> None

    def preload(self):
        """Load the policy and weights once at server start, so a command runs right away."""
        import eval_bi as ev
        if self.loaded is None:
            started = time.perf_counter()
            logging.info("loading policy %s ...", self.args.policy_path)
            self.loaded = ev.load_policy(self.args.policy_path, self.args.device)
            logging.info("policy ready in %.1fs; waiting for POST /command", time.perf_counter() - started)

    def __call__(self, command, return_event):
        import eval_bi as ev
        args = copy.copy(self.args)
        preset = load_presets().get(command.strip())
        if preset is not None:
            # A preset name as the command, e.g. "v4_stage3" -> its stage sentences.
            if Path(preset["policy_path"]).expanduser().resolve() not in (
                    Path(args.policy_path).resolve(), Path(args.policy_path).resolve().parent):
                logging.warning("preset %s was made for %s but the loaded model is %s",
                                command, preset["policy_path"], args.policy_path)
            command = "|".join(preset["stages"])
        # "a|b|c" in the command = stage sentences in order (models trained on *_stages data).
        if "|" in command:
            args.stages, args.task = command, command.split("|")[0].strip()
        else:
            args.task = command  # Plain string data; never shell interpolation.
        pre_move = task_start_poses(command)  # checked before loading anything
        if self.loaded is None:
            self.loaded = ev.load_policy(args.policy_path, args.device)
        policy, preprocessor, postprocessor = self.loaded
        for port in (args.left_port, args.right_port):
            result = subprocess.run(["fuser", port], capture_output=True, text=True)
            if result.returncode != 1:
                raise RuntimeError(f"Robot port busy or ownership check failed: {port}")
            if not Path(port).exists():
                raise RuntimeError(f"Robot port not found: {port}")
        robot = ev.make_robot(args, policy.config.type)
        features = ev.combine_feature_dicts(
            ev.hw_to_dataset_features(robot.action_features, ev.ACTION),
            ev.hw_to_dataset_features(robot.observation_features, ev.OBS_STR),
        )
        exposure_process = None
        try:
            if not args.no_preflight:
                ev.preflight(args)
            exposure_process = ev.setup_top_exposure(args)
            robot.connect()
            if pre_move is not None:
                # e.g. "green" in the command: left arm -> via -> that task's start pose, then the model.
                key, via, start, duration = pre_move
                logging.info("task '%s': moving left arm to its start pose before the model", key)
                pre = copy.copy(args)
                pre.return_via, pre.start_pose = via, start
                pre.return_via_time = pre.return_home_time = duration
                ev.return_to_start(robot, pre)
            ev.run_episode(
                robot, policy, preprocessor, postprocessor, features, args,
                should_return=lambda obs: return_event.is_set(),
                next_stage=self.next_stage, on_stage=self.on_stage,
            )
            self.last_end_reason = getattr(args, "end_reason", None)
        finally:
            try:
                # The left-only implementation also handles partially connected resources.
                robot.disconnect()
            except Exception:
                ev.torque_off(args)
                raise
            finally:
                if exposure_process is not None:
                    if exposure_process.poll() is None:
                        exposure_process.terminate()
                    exposure_process.wait(timeout=5)


def move_left_once():
    # Lazy import: status queries and API-only tests never open robot ports/import torch.
    from test_left_return_once import main as run_verified_motion
    run_verified_motion()


RETURN_ON = ("both", "time")
PINKY_SEQUENCE = None  # --pinky-sequence; None = pinky_sequence.json next to pinky_move.py


def grab_both():
    from pinky_move import DEFAULT_SEQUENCE, grab
    grab(PINKY_SEQUENCE or DEFAULT_SEQUENCE)


def release_both():
    from pinky_move import DEFAULT_SEQUENCE, release
    release(PINKY_SEQUENCE or DEFAULT_SEQUENCE)


def return_both_home():
    from pinky_move import DEFAULT_SEQUENCE, return_home
    return_home(PINKY_SEQUENCE or DEFAULT_SEQUENCE)


def send_result(url, payload, request_id):
    """Bounded timeout; only an HTTP 2xx response counts as delivery."""
    with httpx.Client(timeout=3.0, trust_env=False) as client:
        response = client.post(url, json=payload, headers={"X-Request-ID": request_id})
        response.raise_for_status()


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gripper_open: StrictBool
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class PinkyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pinky_arrive: StrictBool
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)

    @field_validator("command")
    @classmethod
    def nonempty_command(cls, value):
        if not value.strip():
            raise ValueError("command cannot be blank")
        return value


class ReturnController:
    def __init__(self, callback_url=None, motion=move_left_once, sender=send_result, policy_runner=None,
                 pinky_motion=grab_both, home_motion=return_both_home, return_on="both",
                 release_motion=release_both):
        if return_on not in RETURN_ON:
            raise ValueError(f"return_on must be one of {RETURN_ON}")
        self.return_on = return_on
        if callback_url:
            url = httpx.URL(callback_url)
            if url.scheme not in ("http", "https") or not url.host:
                raise ValueError("callback-url must be an absolute http(s) URL")
        self.callback_url = callback_url
        self.motion = motion
        self.sender = sender
        self.policy_runner = policy_runner
        self.pinky_motion = pinky_motion  # grab: approach -> close -> lift, then hold
        self.release_motion = release_motion
        self.home_motion = home_motion
        self.pinky_arrive = False  # latest pinky_arrive value received
        self.stage_requests = 0    # POST /next-stage count for the running command
        if policy_runner is not None and hasattr(policy_runner, "next_stage"):
            policy_runner.next_stage = lambda: self.stage_requests
            policy_runner.on_stage = self._on_stage
        self.return_event = threading.Event()
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="left-return")
        self.busy = False
        self.closing = False
        self.requests = {}
        self.current = {
            "request_id": None, "end_point": False, "state": "idle",
            "error": None, "delivery": "not_sent", "delivery_error": None,
            "pinky": None, "pinky_error": None, "return_reason": None,
        }

    def _on_stage(self, index, text):
        with self.lock:
            self.current.update(stage=index, stage_text=text)

    def next_stage(self):
        with self.lock:
            if not (self.busy and self.current.get("command") is not None and self.current["state"] == "running"):
                raise HTTPException(409, "No model is running")
            self.stage_requests += 1
            return {**self.current, "next_stage_requested": self.stage_requests}

    def snapshot(self):
        with self.lock:
            return dict(self.current)

    def start(self, request):
        with self.lock:
            if self.closing:
                raise HTTPException(503, "Server is shutting down")
            is_command = isinstance(request, CommandRequest)
            if not is_command:
                if not request.gripper_open:
                    return {**self.current, "accepted": False}
                if self.busy and self.current.get("command") is not None:
                    if self.current["state"] != "running":
                        raise HTTPException(409, "Motion has ended; result delivery is in progress")
                    if request.request_id is not None and request.request_id != self.current["request_id"]:
                        raise HTTPException(409, "request_id does not match the active command")
                    if self.return_on == "time":
                        raise HTTPException(409, "Server runs with --return-on time: the model runs "
                                                 "until --episode-time ends, then returns")
                    self.return_event.set()
                    return {**self.current, "return_requested": True}
                if request.request_id is None:
                    request = request.model_copy(update={"request_id": str(uuid4())})
            elif self.policy_runner is None:
                raise HTTPException(503, "Start this server with --policy-path to accept commands")
            if request.request_id in self.requests:
                previous = self.requests[request.request_id]
                command = request.command if is_command else None
                if previous.get("command") != command:
                    raise HTTPException(409, "request_id was already used for a different operation")
                return {**self.requests[request.request_id], "duplicate": True}
            if self.busy:
                raise HTTPException(409, "A return or result delivery is already in progress")
            self.busy = True
            self.return_event.clear()
            self.stage_requests = 0
            command = request.command if is_command else None
            self.current = {
                "request_id": request.request_id, "end_point": False, "state": "running",
                "error": None, "delivery": "pending" if self.callback_url else "disabled",
                "delivery_error": None,
                "command": command, "pinky": None, "pinky_error": None, "return_reason": None,
                "stage": None, "stage_text": None,
            }
            self.requests[request.request_id] = self.current
            response = {**self.current, "accepted": True}
            self.executor.submit(self._run, request.request_id, command)
            return response

    def _run(self, request_id, command=None):
        try:
            if command is None:
                self.motion()
            else:
                self.policy_runner(command, self.return_event)
        except Exception as exc:
            logging.exception("Left return failed")
            with self.lock:
                self.current.update(state="failed", end_point=False, error=str(exc))
        else:
            with self.lock:
                # Why the model stopped: the gripper-open signal, or --episode-time ran out.
                if command is None:
                    reason = None
                elif self.return_event.is_set():
                    reason = "gripper_open"
                else:
                    reason = getattr(self.policy_runner, "last_end_reason", None)
                    reason = reason if isinstance(reason, str) else "time"
                self.current.update(state="completed", end_point=True, return_reason=reason)

        # Movement outcome is independent of network success. Never repeat motion
        # because a notification failed.
        try:
            self._deliver({"end_point": self.snapshot()["end_point"]}, request_id)
            if self.snapshot()["end_point"]:
                self._grab()
        finally:
            with self.lock:
                self.busy = False
                self._maybe_start_pinky()

    def _grab(self):
        """Right after end_point: approach, close and lift without waiting for Pinky."""
        with self.lock:
            # The arms leave the start pose, so end_point no longer holds.
            self.current.update(end_point=False, pinky="grabbing", pinky_error=None)
        try:
            self.pinky_motion()
        except Exception as exc:
            logging.exception("Grab failed")
            with self.lock:
                self.current.update(pinky="grab_failed", pinky_error=str(exc))
            self._deliver({"pinky_done": False}, self.current["request_id"])
        else:
            with self.lock:
                self.current["pinky"] = "holding"  # lifted; waiting for pinky_arrive

    def _deliver(self, payload, request_id):
        if self.callback_url:
            for attempt in range(3):
                try:
                    self.sender(self.callback_url, payload, request_id)
                except Exception as exc:
                    with self.lock:
                        self.current.update(delivery="retrying", delivery_error=str(exc))
                    if attempt < 2:
                        time.sleep(0.2)
                else:
                    with self.lock:
                        self.current.update(delivery="sent", delivery_error=None)
                    break
            else:
                with self.lock:
                    self.current["delivery"] = "failed"
                logging.error("Result delivery failed; GET /status retains the motion result")

    def start_pinky(self, request):
        with self.lock:
            if self.closing:
                raise HTTPException(503, "Server is shutting down")
            self.pinky_arrive = request.pinky_arrive
            if self._maybe_start_pinky():
                return {**self.current, "accepted": True}
            return {**self.current, "accepted": False, "waiting": self.pinky_arrive}

    def _maybe_start_pinky(self):
        """Call with the lock held. Release only when the object is held up and pinky_arrive is true."""
        ready = (self.pinky_arrive and not self.busy and not self.closing
                 and self.current["pinky"] == "holding")
        if not ready:
            return False
        self.busy = True
        self.pinky_arrive = False  # consumed; a continuing sender will set it again
        self.current.update(pinky="releasing", pinky_error=None)
        self.executor.submit(self._run_pinky, self.current["request_id"])
        return True

    def _run_pinky(self, request_id):
        try:
            try:
                self.release_motion()
            except Exception as exc:
                logging.exception("Release failed")
                with self.lock:
                    self.current.update(pinky="release_failed", pinky_error=str(exc))
                self._deliver({"pinky_done": False}, request_id)
                return
            with self.lock:
                self.current["pinky"] = "returning"
            self._deliver({"pinky_done": True}, request_id)
            try:
                self.home_motion()
            except Exception as exc:
                logging.exception("Return after pinky failed")
                with self.lock:
                    self.current.update(pinky="return_failed", pinky_error=str(exc))
            else:
                with self.lock:
                    self.current.update(pinky="completed", end_point=True)
            self._deliver({"end_point": self.snapshot()["end_point"]}, request_id)
        finally:
            with self.lock:
                self.busy = False

    def close(self):
        with self.lock:
            self.closing = True
        self.executor.shutdown(wait=True)


def create_app(callback_url=None, motion=move_left_once, sender=send_result, lock_path=None,
               policy_runner=None, pinky_motion=grab_both, home_motion=return_both_home, release_motion=release_both,
               return_on="both"):
    controller = ReturnController(callback_url, motion, sender, policy_runner, pinky_motion, home_motion,
                                  return_on, release_motion)

    @asynccontextmanager
    async def lifespan(app):
        # Prevent two API processes/workers from operating this left arm.
        path = Path(lock_path) if lock_path else Path(__file__).with_suffix(".lock")
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                controller.close()
                raise RuntimeError("Another eval_bi_api process is running; use one worker") from exc
            try:
                yield
            finally:
                controller.close()
                fcntl.flock(handle, fcntl.LOCK_UN)

    app = FastAPI(title="Left follower return API", lifespan=lifespan)
    app.state.controller = controller

    @app.post("/command", status_code=202)
    def request_command(request: CommandRequest):
        """command 문자열을 task에 넣고 모델을 실행. 완료 후 시작 자세로 복귀."""
        return controller.start(request)

    @app.post("/return", status_code=202)
    def request_return(request: ReturnRequest):
        """개방 신호를 받아 복귀 시작. 본문 bool은 JSON true/false로 전달."""
        return controller.start(request)

    @app.post("/pinky", status_code=202)
    def request_pinky(request: PinkyRequest):
        """pinky_arrive 최신 값 저장. end_point도 true이면 양팔 집기 -> 놓기 -> 복귀 시작."""
        return controller.start_pinky(request)

    @app.post("/next-stage", status_code=202)
    def request_next_stage():
        """다음 stage 문장으로 넘기기 (스페이스 키와 같은 역할). 모델 실행 중에만."""
        return controller.next_stage()

    @app.get("/end-point")
    def get_end_point():
        return {"end_point": controller.snapshot()["end_point"]}

    @app.get("/status")
    def get_status():
        return controller.snapshot()

    return app


app = create_app(os.environ.get("END_POINT_CALLBACK_URL") or None)


def parse_server_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--callback-url", default=os.environ.get("END_POINT_CALLBACK_URL") or None)
    parser.add_argument("--return-on", choices=RETURN_ON, default="both",
                        help="when the model stops and the left arm returns via -> start: "
                             "both = gripper_open signal or --episode-time end (default), "
                             "time = only when --episode-time ends (POST /return is refused while running)")
    parser.add_argument("--preset", default=None,
                        help="task_presets.json name (e.g. v4_stage3): fills --policy-path and --start-version "
                             "when not given; send the same name as the command to use its stage sentences")
    parser.add_argument("--start-version", default=None,
                        help="task_start_poses.json version: v4 = no pre-move, model starts from the normal "
                             "start pose (default); v5 = left arm goes waypoint -> green/blue start pose first")
    parser.add_argument("--pinky-sequence", default=None,
                        help="pose file for the pinky pick (default: pinky_sequence.json)")
    options, evaluation_argv = parser.parse_known_args(argv)
    if options.preset:
        presets = load_presets()
        if options.preset not in presets:
            parser.error(f"unknown --preset {options.preset!r}; known: {', '.join(presets)}")
        preset = presets[options.preset]
        if not any(a == "--policy-path" or a.startswith("--policy-path=") for a in evaluation_argv):
            evaluation_argv = [*evaluation_argv, "--policy-path", preset["policy_path"]]
        options.start_version = options.start_version or preset.get("start_version")
    options.start_version = options.start_version or "v4"
    runner = None
    if evaluation_argv:
        import eval_bi as ev
        args = ev.parse_args(evaluation_argv)
        # Accept a checkpoint folder too: .../checkpoints/011000 -> .../011000/pretrained_model
        nested = Path(args.policy_path).expanduser() / "pretrained_model"
        if (nested / "config.json").exists():
            args.policy_path = str(nested)
        if args.dry_run or args.no_return or args.episodes != 1:
            parser.error("API commands require real return motion: no dry-run/no-return, episodes=1")
        runner = PolicyRunner(args)
    return options, runner


if __name__ == "__main__":
    import uvicorn
    options, runner = parse_server_args()
    # Importing lerobot already installed a root handler at WARNING, so force INFO here;
    # otherwise stage switches and the gripper progress lines never reach the terminal.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    START_VERSION = options.start_version
    task_start_poses("", version=START_VERSION)  # fail fast on an unknown version
    logging.info("start version %s", START_VERSION)
    if runner is not None:
        runner.preload()  # before the server accepts requests
    if options.pinky_sequence:
        from pinky_move import load_sequence
        load_sequence(options.pinky_sequence)  # fail fast on a bad file
        PINKY_SEQUENCE = options.pinky_sequence
    # Reuse the module app's controller only when configuration matches.
    app.state.controller.close()
    app = create_app(options.callback_url, policy_runner=runner, return_on=options.return_on)
    uvicorn.run(app, host=options.host, port=options.port, workers=1)
