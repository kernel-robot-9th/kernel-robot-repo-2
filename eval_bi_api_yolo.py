"""eval_bi_api.py와 같은 API. command가 오면 모방학습 대신 YOLO + click pick으로 왼팔이 거즈를 집습니다.

실행:
  conda activate main_project
  python eval_bi_api_yolo.py --host 0.0.0.0 --port 8000 \
      --callback-url http://RECEIVER_IP:9000/robot/result
  (--auto: MOVE / PICK / DROP 확인 입력 없이 바로 움직임. 기본은 서버 터미널에서 직접 입력)
  (--step: 팔/그리퍼 단계마다 이 터미널에서 SPACE를 눌러야 다음 단계로, q = 그 자리에서 중단)
  (--dry-run: 모터 없이 시험. YOLO와 click pick 계획은 실제로 돌고, 팔 이동은 로그만)
  시험 송신기: python api_sender_yolo.py flow --command "pick and place green gauze"
  EMR(관제 서버)로 결과 보내기: --callback-url 대신 --emr-api http://192.168.129.135:8000/api/v1
     성공하면 GET <emr-api>/robot/<request_id>/end-point (200이면 전달 완료, 3번까지 재시도).
     실패 결과는 보내지 않습니다 (EMR이 성공만 받음). /status에는 남습니다.

엔드포인트와 콜백은 eval_bi_api.py와 같습니다 (/command, /end-point, /status 등).
추가: GET /detection -> 마지막 YOLO 결과. pinky 양팔 시퀀스는 기본으로 꺼져 있습니다 (--pinky로 켜기).

POST /command {"command": "pick and place blue gauze", "request_id": "cycle-001"}
v5 순서 (모방학습 자리를 click pick이 대신):
  시작: 왼팔이 home(시작 자세)에 있다고 보고 바로 YOLO를 찍습니다.
     (--home-first: 먼저 현재 위치 -> 복귀 경유(OV) -> home으로 이동, 이미 home이면 그대로)
  0. YOLO (팔이 home에 있을 때): 탑 카메라를 학습 때와 같은 640x480(노출 90)으로 찍어
     command 색 거즈(blue_gauze / green_gauze, 색이 없으면 아무 거즈)를 찾습니다. 라벨마다 확률 최고 하나.
     잡을 점 = green_gauze는 x가 작은 두 꼭짓점의 가운데(왼쪽 변), blue_gauze는 x가 큰 두 점(오른쪽 변).
     잡을 점이 --roi(640x480 기준 x 0~0.4, y 0.5~1; 가운데 검은 상자 제외) 안이어야 하고,
     1920x1080로 바꾼 점(u*2.25+240, v*2.25)이 click pick 작업 영역(regions_uv) 안이어야 합니다.
     click pick에는 1920x1080 좌표(grasp_uv)를 넘깁니다.
     못 찾으면 home에서 토크 끄고 실패 (state=failed, 콜백 {"end_point": false}).
  1. click pick: click_pick_yolo.py --uv <grasp_uv> --live --skip LIFT DROP_RETREAT
     (= omx_click_pick.py run --live 와 같은 계획·동작, 클릭만 YOLO 점으로 대체)
     home -> HIGH -> OPEN -> APPROACH -> HOVER -> PICK -> CLOSE -> RETREAT -> CARRY_HIGH
     -> DROP_RELEASE -> RELEASE -> RETURN_HIGH
     취소나 오류면 그 자리에서 토크 유지하고 실패로 끝냅니다 (자동 복귀하지 않음).
  2. RETURN_HIGH -> home(DEFAULT_START_POSE) 바로, 도착 후 왼팔 토크 OFF.
  3. 콜백 {"end_point": true}.
  예전 v5 경유 자세는 옵션으로 남아 있습니다: --outbound-ov (home -> OV -> HIGH),
  --return-ov (RETURN_HIGH -> OV -> home), --click-skip (빼는 click pick 단계, 기본 LIFT DROP_RETREAT;
  값 없이 주면 하나도 안 뺌).
/status의 phase: detect -> pick -> drop -> to_home -> done
  (click_stage에 click pick의 현재 단계 이름: HIGH ... PICK ... CARRY_HIGH ... RETURN_HIGH).
YOLO 결과는 라벨마다 확률이 가장 높은 것 하나만 남깁니다 (/status yolo, GET /detection).

YOLO는 vision_project 환경의 python으로 별도 프로세스(yolo_worker.py)에서 돌립니다
(로봇 환경에 ultralytics를 넣으면 OpenCV 버전이 바뀜). 서버를 켤 때 모델을 먼저 로드합니다.
eval_bi_api.py와 같은 잠금 파일을 써서 둘을 동시에 켤 수 없습니다.
click pick은 left_arm_only.py로 /dev/omx_follower_left 하나만 씁니다 (두 팔이 다 연결돼 있어도 됨).
--pinky: home 복귀 후 양팔 pinky 시퀀스 (오른팔 /dev/omx_follower 필요). --emr-api일 때 pinky_done은 EMR로 안 보냅니다.
"""
import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import eval_bi_api as base

HERE = Path(__file__).resolve().parent
YOLO_DIR = Path.home() / "main_project" / "yolo"
OMX = Path.home() / "main_project" / "omxtest-main"
DEFAULT_WEIGHTS = YOLO_DIR / "runs/obb/gauze_obb_v1/weights/best.pt"
DEFAULT_PYTHON = Path.home() / "anaconda3/envs/vision_project/bin/python"
CLICK_CONFIG = OMX / "config/omx_click_pick.json"
CALIBRATION = OMX / "config/single/omx_xy_calibration.json"
LEFT_PORT = "/dev/omx_follower_left"
COLORS = ("blue", "green")
SKIP_STAGES = ["LIFT", "DROP_RETREAT"]  # --click-skip: click-pick stages left out
JOINT_OFFSET = []  # --joint-offset: e.g. ["12:-30"], pulses added to motor IDs in OFFSET_STAGES
OFFSET_STAGES = ["APPROACH"]  # --offset-stages
CLOSE_EXTRA = 0  # --close-extra: CLOSE goes this many pulses past close_pulse
OPEN_SCALE = 1.0  # --open-scale: OPEN width as a fraction of click pick's open_pulse (1 = full)
STEP = False  # --step: wait for SPACE in this terminal before every arm / gripper step


def step(name):
    if STEP:
        from step_key import wait_space
        wait_space(name)


def target_label(command):
    """'pick and place blue gauze' -> ('blue', 'blue_gauze'); no colour word -> (None, None)."""
    text = command.lower()
    found = [c for c in COLORS if c in text]
    if len(found) > 1:
        raise RuntimeError(f"command names more than one colour: {found}")
    return (found[0], f"{found[0]}_gauze") if found else (None, None)


def via_for(colour):
    """v5 outbound waypoint (OV) for the colour; green's when the command has no colour."""
    data = json.loads(base.TASK_START_POSES.read_text())
    tasks = data["versions"]["v5"]["tasks"]
    entry = tasks.get(colour or "green") or next(iter(tasks.values()))
    if entry.get("placeholder", True) or entry.get("via") is None:
        raise RuntimeError(f"v5 via pose for {colour!r} is not measured ({base.TASK_START_POSES})")
    return list(entry["via"]), float(entry.get("time", 4.0))


def move_left(segments, disable_torque_at_end, fps=30, skip_if_at_end=False):
    """Left arm only (no cameras/policy), through [(label, pose6, seconds), ...].

    Same checks and trajectory as test_left_return_once.py / eval_bi.return_to_start.
    Torque stays on afterwards unless disable_torque_at_end.
    skip_if_at_end: when the arm is already within 2.0 of the last pose, do not move at all.
    """
    from types import SimpleNamespace
    from eval_bi import JOINT_NAMES, return_to_start
    from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig

    occupied = subprocess.run(["fuser", LEFT_PORT], capture_output=True, text=True)
    if occupied.returncode != 1:
        raise RuntimeError(f"left port busy or ownership check failed: {occupied.stdout} {occupied.stderr}")
    arm = OmxFollower(OmxFollowerConfig(id="omx_bi_follower_left", port=LEFT_PORT, cameras={}))
    bus = arm.bus
    enabled = False
    finished = False
    try:
        bus.connect()
        if not bus.is_calibrated:
            raise RuntimeError("left calibration mismatch; no motion performed")
        modes = bus.sync_read("Operating_Mode", normalize=False)
        for name, mode in modes.items():
            if mode not in ((3, 5) if name == "gripper" else (3, 4)):
                raise RuntimeError(f"unexpected operating mode for {name}: {mode}")
        errors = bus.sync_read("Hardware_Error_Status", normalize=False)
        if any(errors.values()):
            raise RuntimeError(f"motor hardware errors: {errors}")
        bus.sync_write("Goal_Position", bus.sync_read("Present_Position"))  # no stale goal
        enabled = True
        bus.enable_torque()

        def send_left(action):
            errs = bus.sync_read("Hardware_Error_Status", normalize=False)
            if any(errs.values()):
                raise RuntimeError(f"motor hardware errors during move: {errs}")
            target = {name: action[f"left_{name}.pos"] for name in JOINT_NAMES}
            actual = bus.sync_read("Present_Position")
            if max(abs(target[n] - actual[n]) for n in JOINT_NAMES) > 15:
                raise RuntimeError("excessive tracking error; move aborted")
            bus.sync_write("Goal_Position", target)
            return action

        robot = SimpleNamespace(left_arm=arm, send_action=send_left)
        if skip_if_at_end and segments:
            now = bus.sync_read("Present_Position")
            label, pose, _ = segments[-1]
            if max(abs(now[n] - v) for n, v in zip(JOINT_NAMES, pose)) <= 2.0:
                print(f"[ARM] {label} (already there)", flush=True)
                segments = []
        for label, pose, seconds in segments:
            step(label)
            print(f"[ARM] {label}", flush=True)
            # return_to_start always runs two segments; the second one just settles on the same pose.
            return_to_start(robot, SimpleNamespace(
                return_via=list(pose), start_pose=list(pose), return_via_time=seconds, return_home_time=0.3,
                return_tolerance=2.0, return_settle_time=4.0, fps=fps))
        finished = True
    finally:
        if bus.is_connected:
            # On failure keep torque on so the arm does not drop mid-air.
            bus.disconnect(disable_torque=enabled and finished and disable_torque_at_end)


class YoloWorker:
    """vision_project python running yolo_worker.py; one JSON line per request."""
    def __init__(self, python, weights, cam_top, region, conf, exposure, device,
                 roi="0,0.5,0.4,1.0", to_calib="2.25,2.25,240,0", width=640, height=480):
        self.cmd = [str(python), str(HERE / "yolo_worker.py"), "--weights", str(weights),
                    "--cam-top", cam_top, "--region", json.dumps(region), "--conf", str(conf),
                    "--exposure", str(exposure), "--device", str(device), "--roi", roi,
                    "--to-calib", to_calib, "--width", str(width), "--height", str(height)]
        self.proc = None
        self.lines = queue.Queue()
        self.lock = threading.Lock()

    def start(self, timeout=120):
        logging.info("starting YOLO worker: %s", " ".join(self.cmd))
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=None, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc, self.lines), daemon=True).start()
        ready = self._next(timeout)
        if not ready.get("ready"):
            raise RuntimeError(f"YOLO worker did not start: {ready}")
        return ready

    @staticmethod
    def _read(proc, lines):
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)  # process ended

    def _next(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("YOLO worker timed out") from None
        if line is None:
            raise RuntimeError(f"YOLO worker exited (code {self.proc.poll()})")
        return json.loads(line)

    def request(self, payload, timeout=60):
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self.start()
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
            reply = self._next(timeout)
        if not reply.get("ok"):
            raise RuntimeError(f"YOLO failed: {reply.get('error')}")
        return reply

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# click pick stage -> /status phase (v5: home -> OV -> pick -> drop -> OV -> home)
STAGE_PHASE = {"HIGH": "pick", "OPEN": "pick", "APPROACH": "pick", "HOVER": "pick", "PICK": "pick",
               "CLOSE": "pick", "LIFT": "pick", "RETREAT": "pick",
               "CARRY_HIGH": "drop", "DROP_RELEASE": "drop", "RELEASE": "drop",
               "RETURN_HIGH": "drop", "DROP_RETREAT": "drop"}


def run_click_pick(uv, auto, log_path, on_stage=lambda name: None):
    """click_pick_yolo.py in a child process. Its output is echoed to this terminal and
    its MOVE / PICK / DROP prompts (without --auto) are answered in this terminal."""
    cmd = [sys.executable, "-u", str(HERE / "click_pick_yolo.py"), "--uv", f"{uv[0]:.1f}", f"{uv[1]:.1f}",
           "--live", "--output", str(log_path)] + (["--auto"] if auto else []) + (["--step"] if STEP else []) \
        + (["--skip", *SKIP_STAGES] if SKIP_STAGES else []) + ["--open-scale", f"{OPEN_SCALE:.4f}", "--close-extra", str(CLOSE_EXTRA)] \
        + (["--joint-offset", *JOINT_OFFSET, "--offset-stages", *OFFSET_STAGES] if JOINT_OFFSET else [])
    logging.info("click pick: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=str(HERE), stdout=subprocess.PIPE, text=True, bufsize=1)
    for line in proc.stdout:
        if line.startswith("STAGE "):  # machine line for /status; [ARM]/[GRIPPER] lines show the stage
            on_stage(line.split()[1])
        else:
            print(line, end="", flush=True)
    code = proc.wait()
    if code == 3:
        raise RuntimeError("click pick cancelled at a confirmation; arm held where it stopped (torque on)")
    if code != 0:
        raise RuntimeError(f"click pick failed (exit {code}); arm held where it stopped, see {log_path}")


def dry_move_left(segments, disable_torque_at_end, skip_if_at_end=False):
    """--dry-run: log the left-arm segments, no motor port."""
    for label, pose, seconds in segments:
        step(label)
        print(f"[ARM] {label}  [dry-run] {[round(v, 2) for v in pose]} ({seconds:.1f}s)", flush=True)
        time.sleep(min(seconds, 1.0))
    if disable_torque_at_end:
        print("[TORQUE] left arm off  [dry-run]", flush=True)


def dry_click_pick(uv, auto, log_path, on_stage=lambda name: None):
    """--dry-run: real click-pick plan for this point (no motor port), then step through its stages."""
    cmd = [sys.executable, str(HERE / "click_pick_yolo.py"), "--uv", f"{uv[0]:.1f}", f"{uv[1]:.1f}"] \
        + (["--skip", *SKIP_STAGES] if SKIP_STAGES else []) + ["--open-scale", f"{OPEN_SCALE:.4f}", "--close-extra", str(CLOSE_EXTRA)] \
        + (["--joint-offset", *JOINT_OFFSET, "--offset-stages", *OFFSET_STAGES] if JOINT_OFFSET else [])
    out = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"click pick plan failed: {out.stderr.strip() or out.stdout.strip()}")
    plan = json.loads(out.stdout.strip().splitlines()[-2])
    prompts = {"PICK": "HOVER 도착. 실제 정렬·바닥 간섭 확인 후 PICK 입력 (그 외: 중단·토크 유지): PICK",
               "CARRY_HIGH": "봉투 파지·주변 여유 확인 후 DROP 입력 (그 외: 중단·토크 유지): DROP"}
    print(f"[DRY_RUN] click pick plan for {uv}; no motor port", flush=True)
    step("MOVE (torque on, start click pick)")
    for name, kind in zip(plan["stages"], plan["kinds"]):
        step(name)
        if name in prompts and not STEP:
            print(prompts[name] + "  [dry-run]", flush=True)
        print(f"[{'GRIPPER' if kind == 'gripper' else 'JOINT' if kind == 'joint' else 'ARM'}] {name}", flush=True)
        on_stage(name)
        time.sleep(0.5)


class YoloRunner:
    """Takes PolicyRunner's place: YOLO -> home -> OV -> click pick -> OV -> home."""
    def __init__(self, worker, frames=5, save_dir=None, auto=False, via_time=None,
                 return_via_time=4.0, return_home_time=4.0, motions=None, home_first=False,
                 outbound_ov=False, return_ov=False):
        self.home_first = home_first
        self.outbound_ov = outbound_ov
        self.return_ov = return_ov
        self.worker = worker
        self.frames = frames
        self.save_dir = Path(save_dir) if save_dir else None
        self.auto = auto
        self.via_time = via_time
        self.return_via_time = return_via_time
        self.return_home_time = return_home_time
        # Injected in tests: {"move_left": fn(segments, disable_torque), "click_pick": fn(uv, auto, log)}
        motions = motions or {}
        self.move_left = motions.get("move_left", move_left)
        self.click_pick = motions.get("click_pick", run_click_pick)
        self.last_end_reason = None
        self.last_result = None
        self.next_stage = None   # set by ReturnController; unused (no stages)
        self.on_stage = None
        self.on_update = None    # set after create_app: dict -> /status, returns request_id

    def preload(self):
        ready = self.worker.start()
        logging.info("YOLO ready, classes %s; waiting for POST /command", ready.get("classes"))

    def _update(self, **fields):
        return self.on_update(fields) if self.on_update is not None else None

    def __call__(self, command, return_event):
        from eval_bi import DEFAULT_RETURN_VIA, DEFAULT_START_POSE
        colour, target = target_label(command)
        via, via_time = via_for(colour)  # checked before anything moves
        request_id = self._update(phase="go_home", click_stage=None) or "latest"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.home_first:
            # --home-first: current -> OV (return via) -> HOME so the arm does not hide the gauze,
            # unless the arm is already at home.
            self.move_left([("OV", DEFAULT_RETURN_VIA, self.return_via_time),
                            ("HOME", DEFAULT_START_POSE, self.return_home_time)], False, skip_if_at_end=True)
        self._update(phase="detect")
        save = str(self.save_dir / f"{stamp}_{request_id}.jpg") if self.save_dir else None

        reply = self.worker.request({"target": target, "frames": self.frames, "save": save})
        det = reply["detection"]
        objects = [{k: d[k] for k in ("label", "conf", "grasp_uv", "grasp_uv_cam", "in_area", "in_roi", "in_region")}
                   for d in reply["all"]]
        self.last_result = {"command": command, "target": target, "detection": det,
                            "objects": objects, "frame_mean": reply["frame_mean"], "image": save}
        self._update(detection=det, yolo={k: v for k, v in self.last_result.items() if k != "detection"})
        logging.info("YOLO %s -> %s", target or "any gauze", det)
        for o in objects:
            mark = "  <- target" if det and o["label"] == det["label"] else ""
            print(f"[YOLO] {o['label']} conf {o['conf']:.2f}  grasp 640x480 {o['grasp_uv_cam']} -> 1920x1080 "
                  f"{o['grasp_uv']}  {'in area' if o['in_area'] else 'outside area'}{mark}", flush=True)
        if not objects:
            print("[YOLO] nothing detected", flush=True)
        if det is None:
            self.move_left([], True)  # stay at home, torque off as after a normal cycle
            dark = " (camera image is dark, lights off?)" if reply["frame_mean"] < 20 else ""
            raise RuntimeError(f"no {target or 'gauze'} found in the work area{dark}; arm left at home")

        if self.outbound_ov:  # --outbound-ov: home -> OV before click pick (default: straight to HIGH)
            self._update(phase="home_to_ov")
            self.move_left([("OV", via, self.via_time or via_time)], False)

        self._update(phase="pick")
        log_dir = YOLO_DIR / "outputs/api"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.click_pick(det["grasp_uv"], self.auto, log_dir / f"{stamp}_{request_id}_click_pick.jsonl",
                        lambda name: self._update(phase=STAGE_PHASE.get(name, "pick"), click_stage=name))

        self._update(phase="to_home")
        back = [("OV", DEFAULT_RETURN_VIA, self.return_via_time)] if self.return_ov else []
        self.move_left(back + [("HOME", DEFAULT_START_POSE, self.return_home_time)], True)
        self._update(phase="done")
        self.last_end_reason = "click_pick_done"


def emr_sender(base_url, payload, request_id):
    """--emr-api: EMR takes success only, as GET {base}/robot/{request_id}/end-point (200 = received).

    Same as the EMR team's notify_emr_end_point(): 3 tries, 2 s timeout, 1 s apart.
    Other results (end_point false, pinky_done) are not sent; GET /status keeps them.
    """
    import httpx
    if payload.get("end_point") is not True:
        logging.info("EMR: %s not sent (EMR only takes a successful end_point)", payload)
        return
    url = f"{base_url.rstrip('/')}/robot/{request_id}/end-point"
    error = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                response = client.get(url)
            if response.status_code == 200:
                print(f"[EMR] end-point sent: GET {url} -> 200", flush=True)
                return
            error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            error = str(exc)
        time.sleep(1)
    print(f"[EMR] end-point FAILED: GET {url} ({error})", flush=True)
    raise RuntimeError(f"EMR end-point not received: {error}")


def parse_server_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--callback-url", default=os.environ.get("END_POINT_CALLBACK_URL") or None)
    p.add_argument("--emr-api", default=None,
                   help="EMR base URL, e.g. http://192.168.129.135:8000/api/v1: on success send "
                        "GET <emr-api>/robot/<request_id>/end-point instead of the POST callback")
    p.add_argument("--auto", action="store_true", help="no typed MOVE / PICK / DROP confirmations")
    p.add_argument("--step", action="store_true",
                   help="wait for SPACE in this terminal before every arm / gripper step (q = stop there)")
    p.add_argument("--outbound-ov", action="store_true", help="home -> OV before click pick (default: off)")
    p.add_argument("--return-ov", action="store_true", help="click pick -> OV -> home (default: straight home)")
    p.add_argument("--click-skip", nargs="*", default=["LIFT", "DROP_RETREAT"], metavar="STAGE",
                   help="click-pick stages to leave out (default: LIFT DROP_RETREAT); give it empty to keep all")
    p.add_argument("--joint-offset", nargs="*", default=[], metavar="ID:PULSES",
                   help="add pulses per motor ID in --offset-stages, e.g. --joint-offset 12:-30 (log shows the new height)")
    p.add_argument("--offset-stages", nargs="+", default=["APPROACH"], metavar="STAGE",
                   help="click-pick stages that get --joint-offset (default: APPROACH)")
    p.add_argument("--close-extra", type=int, default=0,
                   help="click-pick CLOSE: go this many pulses past close_pulse (e.g. 80) to squeeze thin bags")
    p.add_argument("--open-scale", type=float, default=1.0,
                   help="OPEN gripper opening as a fraction of click pick's close->open (default 1 = full; e.g. 0.667)")
    p.add_argument("--home-first", action="store_true",
                   help="before YOLO, move the arm current -> OV -> home (default: assume it starts at home)")
    p.add_argument("--dry-run", action="store_true",
                   help="no motors: YOLO and the click-pick plan run for real, arm moves are only logged")
    p.add_argument("--pinky", action="store_true", help="keep the both-arm pinky sequence after end_point")
    p.add_argument("--pinky-sequence", default=None, help="pose file for the pinky pick (with --pinky)")
    p.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    p.add_argument("--yolo-python", default=str(DEFAULT_PYTHON), help="python of the env with ultralytics")
    p.add_argument("--cam-top", default="/dev/cam_top")
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--roi", default="0,0.5,0.4,1.0",
                   help="YOLO work area, x1,y1,x2,y2 fractions of the 640x480 frame (leaves out the black box)")
    p.add_argument("--to-calib", default="2.25,2.25,240,0",
                   help="sx,sy,tx,ty: 640x480 pixel -> 1920x1080 calibration pixel (yolo/fov_check.py)")
    p.add_argument("--frames", type=int, default=5, help="frames per command; best detection wins")
    p.add_argument("--top-exposure", type=int, default=90, help="-1 = auto exposure")
    p.add_argument("--device", default="0", help="YOLO device: 0 = GPU, cpu")
    p.add_argument("--via-time", type=float, default=None, help="home -> OV seconds (default: v5 file time)")
    p.add_argument("--return-via-time", type=float, default=4.0)
    p.add_argument("--return-home-time", type=float, default=4.0)
    p.add_argument("--save-dir", default=str(YOLO_DIR / "outputs/api"), help="annotated image per command; '' = off")
    return p.parse_args(argv)


def work_area():
    """Click-pick work region (pixels) and calibration image size."""
    cfg = json.loads(CLICK_CONFIG.read_text())
    cal = json.loads(CALIBRATION.read_text())
    regions = cfg.get("regions_uv") or cal.get("regions_uv")
    if not regions:
        raise RuntimeError(f"no regions_uv in {CLICK_CONFIG}")
    return regions[0], int(cal["width"]), int(cal["height"])


def build_app(options, runner, **create_kwargs):
    """create_kwargs go to eval_bi_api.create_app (tests pass fakes here)."""
    app = base.create_app(options.callback_url, policy_runner=runner, **create_kwargs)
    controller = app.state.controller
    if not options.pinky:
        controller._grab = lambda: None  # end_point stays true; /pinky never starts a release

    def on_update(fields):
        with controller.lock:
            controller.current.update(fields)
            return controller.current.get("request_id")

    runner.on_update = on_update

    @app.get("/detection")
    def get_detection():
        return runner.last_result or {"detection": None}

    return app


if __name__ == "__main__":
    import uvicorn
    options = parse_server_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    if not Path(options.weights).exists():
        sys.exit(f"weights not found: {options.weights}")
    via_for(None)  # fail fast if v5 poses are missing
    if options.pinky_sequence:
        from pinky_move import load_sequence
        load_sequence(options.pinky_sequence)
        base.PINKY_SEQUENCE = options.pinky_sequence
    region, width, height = work_area()
    if (width, height) != (1920, 1080):
        sys.exit(f"click-pick calibration is {width}x{height}; --to-calib was measured for 1920x1080")
    worker = YoloWorker(options.yolo_python, options.weights, options.cam_top, region,
                        options.conf, options.top_exposure, options.device, options.roi, options.to_calib)
    STEP = options.step
    SKIP_STAGES = list(options.click_skip)
    OPEN_SCALE = options.open_scale
    CLOSE_EXTRA = options.close_extra
    JOINT_OFFSET = list(options.joint_offset)
    OFFSET_STAGES = list(options.offset_stages)
    if options.step and options.auto:
        sys.exit("--step and --auto cannot be used together")
    motions = {"move_left": dry_move_left, "click_pick": dry_click_pick} if options.dry_run else None
    runner = YoloRunner(worker, options.frames, options.save_dir or None, options.auto,
                        options.via_time, options.return_via_time, options.return_home_time, motions,
                        options.home_first, options.outbound_ov, options.return_ov)
    runner.preload()  # before the server accepts requests
    if options.dry_run:
        logging.warning("DRY RUN: no motor port is opened; arm moves are only logged")
    logging.info("confirmations: %s; pinky: %s",
                 "SPACE before every step" if options.step else "auto" if options.auto else "typed in this terminal",
                 "on" if options.pinky else "off")
    base.app.state.controller.close()
    extra = {}
    if options.emr_api:
        if options.callback_url:
            sys.exit("use either --callback-url or --emr-api")
        options.callback_url = options.emr_api
        extra["sender"] = emr_sender
        logging.info("EMR: success -> GET %s/robot/<request_id>/end-point", options.emr_api.rstrip("/"))
    if options.dry_run:  # pinky sequence too: log only, no motors
        for key in ("pinky_motion", "release_motion", "home_motion"):
            extra[key] = (lambda name: lambda: print(f"[PINKY] {name}  [dry-run]", flush=True))(key)
    app = build_app(options, runner, **extra)
    try:
        uvicorn.run(app, host=options.host, port=options.port, workers=1)
    finally:
        worker.close()
