"""Test sender for eval_bi_api_yolo.py: plays the outside side (command sender + result receiver).

It only sends HTTP requests and listens for callbacks; it never opens robot ports.

Start the API server first, with the callback pointing at this script's receiver:
  python eval_bi_api_yolo.py --callback-url http://127.0.0.1:9000/robot/result            # real arm
  python eval_bi_api_yolo.py --callback-url http://127.0.0.1:9000/robot/result --dry-run  # no motors

Full flow (v5): command -> YOLO -> home -> OV -> pick -> drop -> OV -> home -> callback end_point true
  python api_sender_yolo.py flow --command "pick and place green gauze"   # green_gauze, left edge
  python api_sender_yolo.py flow --command "pick and place blue gauze"    # blue_gauze, right edge
If the server sends results to EMR (--emr-api), add --no-callback:
  python api_sender_yolo.py flow --no-callback --command "pick and place blue gauze"
If the server runs with --pinky, add --pinky to also play Pinky (pinky_arrive -> pinky_done -> end_point).
Single requests:
  python api_sender_yolo.py command "pick and place green gauze"
  python api_sender_yolo.py status
  python api_sender_yolo.py detection      # last YOLO result (one object per label)
  python api_sender_yolo.py pinky [true|false]
  python api_sender_yolo.py listen         # only print callbacks
Without --auto on the server, type MOVE / PICK / DROP in the SERVER terminal when it asks.
"""
import argparse
import json
import threading
import time
from uuid import uuid4

import httpx

from api_sender import Receiver, post, stamp

PHASE_TEXT = {
    "go_home": "arm -> home (so it does not hide the gauze)",
    "detect": "YOLO: finding the gauze (arm at home)",
    "home_to_ov": "home -> OV",
    "pick": "pick",
    "drop": "drop",
    "ov_to_home": "OV -> home",
    "to_home": "RETURN_HIGH -> home",
    "done": "back home",
}


def show_detection(result):
    det = result.get("detection")
    for obj in result.get("yolo", result).get("objects", []):
        mark = "  <- target" if det and obj["label"] == det["label"] else ""
        area = "in area" if obj["in_area"] else "outside area"
        cam = f" (640x480 {obj['grasp_uv_cam']})" if obj.get("grasp_uv_cam") else ""
        print(f"{stamp()}    {obj['label']:12s} conf {obj['conf']:.2f}  grasp {obj['grasp_uv']}{cam}  {area}{mark}",
              flush=True)


def wait_flow(client, timeout):
    """Print each phase change until the command ends; return the final status."""
    deadline = time.time() + timeout
    last = None
    shown = False
    while time.time() < deadline:
        s = client.get("/status").json()
        key = (s.get("state"), s.get("phase"), s.get("click_stage"))
        if key != last:
            stage = f" [{key[2]}]" if key[2] and key[1] in ("pick", "drop") else ""
            print(f"{stamp()} state={key[0]} phase={PHASE_TEXT.get(key[1], key[1])}{stage}", flush=True)
            last = key
        if not shown and s.get("yolo"):
            show_detection(s)
            shown = True
        if s.get("state") == "failed":
            raise RuntimeError(f"server reported failure: {s.get('error')}")
        if s.get("state") == "completed" and s.get("delivery") not in ("pending", "retrying"):
            return s
        time.sleep(0.5)
    raise TimeoutError(f"command not finished within {timeout}s")


def flow(client, receiver, args):
    rid = args.request_id or f"yolo-{uuid4().hex[:8]}"
    start = len(receiver.bodies) if receiver else 0
    response = post(client, "/command", {"command": args.command, "request_id": rid})
    if response.status_code >= 400:
        raise SystemExit("command refused")
    status = wait_flow(client, args.timeout)
    if args.no_callback:  # server sends the result to EMR (--emr-api), not to this script
        print(f"{stamp()} end_point {status.get('end_point')} (delivery to EMR: {status.get('delivery')})", flush=True)
    else:
        receiver.wait_for("end_point", True, start, 10)
        print(f"{stamp()} end_point true received (arm back home)", flush=True)
    if args.pinky:
        if args.pinky_delay:
            time.sleep(args.pinky_delay)
        while True:  # like a real Pinky: keep reporting arrival until the server starts releasing
            post(client, "/pinky", {"pinky_arrive": True})
            p = client.get("/status").json().get("pinky")
            if p in ("releasing", "returning", "completed"):
                break
            if p in ("grab_failed", "release_failed", "return_failed"):
                raise RuntimeError(f"pinky failed: {p}")
            time.sleep(1)
        if receiver is not None:
            start = len(receiver.bodies)
            receiver.wait_for("pinky_done", True, 0, args.timeout)
            receiver.wait_for("end_point", True, start, args.timeout)
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            status = client.get("/status").json()
            if status.get("pinky") == "completed" or "failed" in str(status.get("pinky")):
                break
            time.sleep(1)
        print(f"{stamp()} pinky {status.get('pinky')}", flush=True)
    summary = {k: status.get(k) for k in ("request_id", "state", "phase", "end_point", "return_reason", "delivery")}
    print(f"{stamp()} FLOW DONE: {json.dumps(summary, ensure_ascii=False)}", flush=True)
    if status.get("yolo", {}).get("image"):
        print(f"{stamp()} YOLO image: {status['yolo']['image']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9000)
    sub = parser.add_subparsers(dest="action", required=True)
    f = sub.add_parser("flow", help="whole v5 cycle with callbacks")
    f.add_argument("--command", default="pick and place green gauze")
    f.add_argument("--pinky", action="store_true", help="server runs with --pinky: also play Pinky")
    f.add_argument("--no-callback", action="store_true",
                   help="server runs with --emr-api: do not wait for a callback here, read /status instead")
    f.add_argument("--pinky-delay", type=float, default=0)
    f.add_argument("--request-id", default=None)
    f.add_argument("--timeout", type=float, default=600, help="seconds to wait for the command")
    c = sub.add_parser("command")
    c.add_argument("text")
    p = sub.add_parser("pinky")
    p.add_argument("value", nargs="?", default="true", choices=["true", "false"])
    sub.add_parser("status")
    sub.add_parser("detection")
    sub.add_parser("listen")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.server, timeout=5, trust_env=False)
    if args.action == "command":
        post(client, "/command", {"command": args.text})
    elif args.action == "pinky":
        post(client, "/pinky", {"pinky_arrive": args.value == "true"})
    elif args.action == "status":
        print(json.dumps(client.get("/status").json(), ensure_ascii=False, indent=2))
    elif args.action == "detection":
        print(json.dumps(client.get("/detection").json(), ensure_ascii=False, indent=2))
    elif args.action == "listen":
        Receiver(args.listen_host, args.listen_port)
        threading.Event().wait()
    else:
        receiver = None if args.no_callback else Receiver(args.listen_host, args.listen_port)
        flow(client, receiver, args)


if __name__ == "__main__":
    main()
