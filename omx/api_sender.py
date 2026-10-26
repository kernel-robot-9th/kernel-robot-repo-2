"""Test sender for eval_bi_api.py: plays the outside side (command sender + Pinky + result receiver).

It only sends HTTP requests and listens for callbacks; it never opens robot ports.

Start the API server first, with the callback pointing at this script's receiver, e.g.
  python eval_bi_api.py --return-on time --episode-time 30 --policy-path <model> \
      --callback-url http://127.0.0.1:9000/robot/result

Full flow (command -> end_point -> arms grab and lift -> pinky_arrive -> release -> pinky_done -> end_point):
  python api_sender.py flow --command "pick and place blue gauze"
Without a model (server started without --policy-path), use /return instead of /command:
  python api_sender.py flow --no-model
Single requests:
  python api_sender.py command "pick and place blue gauze"
  python api_sender.py return            # {"gripper_open": true}
  python api_sender.py pinky [true|false]
  python api_sender.py next              # move the running model to its next stage sentence
During "flow", pressing SPACE in this terminal does the same while the model runs.
  python api_sender.py status
Stage sentences: put them in one command separated by "|":
  python api_sender.py flow --command "search for the green gauze|grasp the green gauze|put the gauze in the box"
  python api_sender.py listen            # only print callbacks
"""
import argparse
import json
import select
import sys
import termios
import threading
import tty
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

import httpx


def stamp():
    return time.strftime("%H:%M:%S")


class Receiver:
    """Tiny callback receiver: records every JSON body POSTed by the API server."""
    def __init__(self, host, port):
        self.bodies = []
        self.cond = threading.Condition()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                print(f"{stamp()} <- callback {body}  (X-Request-ID {self.headers.get('X-Request-ID')})",
                      flush=True)
                with receiver.cond:
                    receiver.bodies.append(body)
                    receiver.cond.notify_all()
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer((host, port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        print(f"{stamp()} receiving callbacks on http://{host}:{port}/ (any path)", flush=True)

    def wait_for(self, key, value, start, timeout):
        """Wait for a callback {key: value} received after index `start`; return its index."""
        deadline = time.time() + timeout
        with self.cond:
            while True:
                for i in range(start, len(self.bodies)):
                    if self.bodies[i].get(key) == value:
                        return i
                    if key in self.bodies[i] and self.bodies[i][key] != value:
                        raise RuntimeError(f"got {self.bodies[i]} instead of {{{key!r}: {value}}}")
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"no {{{key!r}: {value}}} callback within {timeout}s")
                self.cond.wait(left)


def post(client, path, body):
    response = client.post(path, json=body)
    print(f"{stamp()} -> POST {path} {body}  => {response.status_code} {response.text[:200]}", flush=True)
    return response


def wait_status(client, pred, label, timeout):
    """Poll /status as well, so a missed callback (receiver restarted, network) never stalls the flow."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = client.get("/status").json()
        if pred(status):
            return status
        if status.get("state") == "failed" or status.get("pinky") in ("failed", "return_failed"):
            raise RuntimeError(f"server reported failure: {json.dumps(status, ensure_ascii=False)}")
        key = (status.get("state"), status.get("pinky"), status.get("stage_text"))
        if key != last:
            stage = f", stage={key[2]!r}" if key[2] else ""
            print(f"{stamp()} waiting for {label} (state={key[0]}, pinky={key[1]}{stage})", flush=True)
            last = key
        time.sleep(1)
    raise TimeoutError(f"no {label} within {timeout}s")


class SpaceToNextStage:
    """While the model runs: each space-bar press in this terminal sends POST /next-stage."""
    def __init__(self, client):
        self.client, self.stop = client, threading.Event()
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        if self.fd is None:
            print(f"{stamp()} stdin is not a terminal: space bar -> next stage is off", flush=True)
            return
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        print(f"{stamp()} press SPACE here to move the model to the next stage", flush=True)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0] and sys.stdin.read(1) == " ":
                try:
                    post(self.client, "/next-stage", {})
                except Exception as exc:
                    print(f"{stamp()} next-stage failed: {exc}", flush=True)

    def close(self):
        self.stop.set()
        if self.fd is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def flow(client, receiver, args):
    rid = args.request_id or f"test-{uuid4().hex[:8]}"
    if args.no_model:
        post(client, "/return", {"gripper_open": True, "request_id": rid})
    else:
        response = post(client, "/command", {"command": args.command, "request_id": rid})
        if response.status_code >= 400:
            raise SystemExit("command refused; was the server started with --policy-path?")
    if args.pinky_early:
        # Pinky arrives while the model is still running; the server waits for end_point.
        post(client, "/pinky", {"pinky_arrive": True})
    keys = None if args.no_model else SpaceToNextStage(client)
    try:
        # First run can take minutes: base-model download + model load + episode time.
        wait_status(client, lambda s: s["state"] == "completed" and (s["end_point"] or s["pinky"] is not None),
                    "end_point true", args.timeout)
    finally:
        if keys is not None:
            keys.close()
    print(f"{stamp()} end_point true received; arms now grab and lift on their own", flush=True)
    if args.pinky_delay:
        print(f"{stamp()} Pinky arrives in {args.pinky_delay}s", flush=True)
        time.sleep(args.pinky_delay)
    # Like a real Pinky: keep reporting arrival until the server starts releasing.
    while True:
        post(client, "/pinky", {"pinky_arrive": True})
        status = client.get("/status").json()
        if status.get("pinky") in ("releasing", "returning", "completed"):
            break
        if status.get("pinky") in ("grab_failed", "release_failed", "return_failed"):
            raise RuntimeError(f"server reported failure: {json.dumps(status, ensure_ascii=False)}")
        time.sleep(args.pinky_interval)
    status = wait_status(client, lambda s: s["pinky"] == "completed" and s["end_point"]
                         and s["delivery"] not in ("pending", "retrying"), "pinky done + return", args.timeout)
    print(f"{stamp()} FLOW DONE: {json.dumps(status, ensure_ascii=False)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9000)
    sub = parser.add_subparsers(dest="action", required=True)
    f = sub.add_parser("flow", help="whole cycle with callbacks")
    f.add_argument("--command", default="pick and place blue gauze")
    f.add_argument("--no-model", action="store_true", help="start with POST /return instead of /command")
    f.add_argument("--pinky-early", action="store_true", help="also send pinky_arrive right after the command")
    f.add_argument("--pinky-interval", type=float, default=1.0)
    f.add_argument("--pinky-delay", type=float, default=0, help="seconds after end_point before Pinky reports arrival")
    f.add_argument("--request-id", default=None)
    f.add_argument("--timeout", type=float, default=900, help="seconds to wait for each stage")
    c = sub.add_parser("command")
    c.add_argument("text")
    sub.add_parser("return")
    p = sub.add_parser("pinky")
    p.add_argument("value", nargs="?", default="true", choices=["true", "false"])
    sub.add_parser("next")
    sub.add_parser("status")
    sub.add_parser("listen")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.server, timeout=5, trust_env=False)
    if args.action == "command":
        post(client, "/command", {"command": args.text})
    elif args.action == "return":
        post(client, "/return", {"gripper_open": True})
    elif args.action == "pinky":
        post(client, "/pinky", {"pinky_arrive": args.value == "true"})
    elif args.action == "next":
        post(client, "/next-stage", {})
    elif args.action == "status":
        print(json.dumps(client.get("/status").json(), ensure_ascii=False, indent=2))
    elif args.action == "listen":
        Receiver(args.listen_host, args.listen_port)
        threading.Event().wait()
    else:
        receiver = Receiver(args.listen_host, args.listen_port)
        flow(client, receiver, args)


if __name__ == "__main__":
    main()
