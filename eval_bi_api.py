"""command 수신 -> 모델 실행 -> 왼쪽 복귀 -> 완료 통신.

실행 (상대 주소를 실제 수신 URL로 변경):
  conda activate main_project
  python eval_bi_api.py --host 0.0.0.0 --port 8000 \
      --callback-url http://RECEIVER_IP:9000/robot/result

외부 -> 이 서버:
  POST /command {"command": "pick and place blue gauze", "request_id": "cycle-001"}
  POST /return  {"gripper_open": true, "request_id": "cycle-001"}
  GET /end-point -> {"end_point": false 또는 true}
  GET /status    -> 이동 상태와 전송 결과

이 서버 -> callback-url:
  이동/도착 확인 성공: POST {"end_point": true}
  이동 실패:          POST {"end_point": false}
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
모델은 첫 요청에서 로드 후 재사용합니다. 실행 중 POST /return은 같은 제어 루프에
복귀 이벤트를 전달합니다. request_id를 생략하거나 현재 작업 ID와 맞춰 보내세요.
평가 시간 종료 시에도 복귀합니다. --no-return/--dry-run/복수 episodes는 API에서 금지합니다.
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


class PolicyRunner:
    """One worker owns the policy, cameras and motor ports for the whole cycle."""
    def __init__(self, args):
        self.args = args
        self.loaded = None

    def __call__(self, command, return_event):
        import eval_bi as ev
        args = copy.copy(self.args)
        args.task = command  # Plain string data; never shell interpolation.
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
            ev.run_episode(
                robot, policy, preprocessor, postprocessor, features, args,
                should_return=lambda obs: return_event.is_set(),
            )
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


def send_result(url, payload, request_id):
    """Bounded timeout; only an HTTP 2xx response counts as delivery."""
    with httpx.Client(timeout=3.0, trust_env=False) as client:
        response = client.post(url, json=payload, headers={"X-Request-ID": request_id})
        response.raise_for_status()


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gripper_open: StrictBool
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
    def __init__(self, callback_url=None, motion=move_left_once, sender=send_result, policy_runner=None):
        if callback_url:
            url = httpx.URL(callback_url)
            if url.scheme not in ("http", "https") or not url.host:
                raise ValueError("callback-url must be an absolute http(s) URL")
        self.callback_url = callback_url
        self.motion = motion
        self.sender = sender
        self.policy_runner = policy_runner
        self.return_event = threading.Event()
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="left-return")
        self.busy = False
        self.closing = False
        self.requests = {}
        self.current = {
            "request_id": None, "end_point": False, "state": "idle",
            "error": None, "delivery": "not_sent", "delivery_error": None,
        }

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
            command = request.command if is_command else None
            self.current = {
                "request_id": request.request_id, "end_point": False, "state": "running",
                "error": None, "delivery": "pending" if self.callback_url else "disabled",
                "delivery_error": None,
                "command": command,
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
                self.current.update(state="completed", end_point=True)

        # Movement outcome is independent of network success. Never repeat motion
        # because a notification failed.
        try:
            if self.callback_url:
                payload = {"end_point": self.snapshot()["end_point"]}
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
        finally:
            with self.lock:
                self.busy = False

    def close(self):
        with self.lock:
            self.closing = True
        self.executor.shutdown(wait=True)


def create_app(callback_url=None, motion=move_left_once, sender=send_result, lock_path=None,
               policy_runner=None):
    controller = ReturnController(callback_url, motion, sender, policy_runner)

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
    options, evaluation_argv = parser.parse_known_args(argv)
    runner = None
    if evaluation_argv:
        import eval_bi as ev
        args = ev.parse_args(evaluation_argv)
        if args.dry_run or args.no_return or args.episodes != 1:
            parser.error("API commands require real return motion: no dry-run/no-return, episodes=1")
        runner = PolicyRunner(args)
    return options, runner


if __name__ == "__main__":
    import uvicorn
    options, runner = parse_server_args()
    logging.basicConfig(level=logging.INFO)
    # Reuse the module app's controller only when configuration matches.
    app.state.controller.close()
    app = create_app(options.callback_url, policy_runner=runner)
    uvicorn.run(app, host=options.host, port=options.port, workers=1)
