import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

import eval_bi_api as api


class ApiTests(unittest.TestCase):
    def client(self, motion=None, sender=None, callback="http://receiver.example/result", runner=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        app = api.create_app(
            callback, motion or Mock(), sender or Mock(),
            lock_path=Path(folder.name) / "api.lock",
            policy_runner=runner,
        )
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_command_is_passed_verbatim_and_duplicate_not_reexecuted(self):
        runner = Mock()
        client = self.client(runner=runner)
        payload = {"command": "pick and place blue gauze", "request_id": "pick-1"}
        response = client.post("/command", json=payload)
        self.assertEqual(response.status_code, 202)
        self.wait_done(client)
        self.assertEqual(runner.call_args.args[0], payload["command"])
        self.assertTrue(client.post("/command", json=payload).json()["duplicate"])
        runner.assert_called_once()
        self.assertEqual(client.post("/command", json={**payload, "command": "other"}).status_code, 409)
        self.assertEqual(client.post("/command", json={"command": "  "}).status_code, 422)

    def test_command_requires_model_configuration(self):
        client = self.client()
        self.assertEqual(client.post("/command", json={"command": "pick"}).status_code, 503)

    def test_return_signal_reaches_active_policy_without_second_motion(self):
        entered = threading.Event()
        motion = Mock()
        def runner(command, event):
            entered.set()
            if not event.wait(2):
                raise TimeoutError("No return signal")
        client = self.client(motion=motion, runner=runner)
        client.post("/command", json={"command": "pick", "request_id": "pick-1"})
        self.assertTrue(entered.wait(1))
        self.assertEqual(client.post("/command", json={"command": "other"}).status_code, 409)
        self.assertEqual(client.post("/return", json={
            "gripper_open": True, "request_id": "wrong"}).status_code, 409)
        response = client.post("/return", json={"gripper_open": True, "request_id": "pick-1"})
        self.assertTrue(response.json()["return_requested"])
        self.assertTrue(self.wait_done(client)["end_point"])
        motion.assert_not_called()

    def test_policy_runner_sets_task_and_cleans_up_without_real_robot(self):
        fake_ev = Mock()
        policy, pre, post = Mock(), Mock(), Mock()
        fake_ev.load_policy.return_value = (policy, pre, post)
        fake_ev.setup_top_exposure.return_value = None
        robot = fake_ev.make_robot.return_value
        args = SimpleNamespace(task="old", policy_path="model", device=None,
                               left_port="/left", right_port="/right", no_preflight=True)
        runner = api.PolicyRunner(args)
        event = threading.Event()
        with patch.dict("sys.modules", {"eval_bi": fake_ev}), \
             patch.object(api.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
             patch.object(api.Path, "exists", return_value=True):
            runner("pick and place blue gauze", event)
            called_args = fake_ev.run_episode.call_args.args[5]
            self.assertEqual(called_args.task, "pick and place blue gauze")
            self.assertEqual(args.task, "old")
            event.set()
            self.assertTrue(fake_ev.run_episode.call_args.kwargs["should_return"]({}))
            runner("second task", event)
        fake_ev.load_policy.assert_called_once()
        self.assertEqual(robot.disconnect.call_count, 2)

    def wait_done(self, client):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with client.app.state.controller.lock:
                busy = client.app.state.controller.busy
            if not busy:
                return client.get("/status").json()
            time.sleep(.005)
        self.fail("Worker failed to finish")

    def test_success_posts_exact_payload_and_duplicate_does_not_move(self):
        motion, sender = Mock(), Mock()
        client = self.client(motion, sender)
        response = client.post("/return", json={"gripper_open": True, "request_id": "one"})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["end_point"])
        result = self.wait_done(client)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["delivery"], "sent")
        self.assertEqual(client.get("/end-point").json(), {"end_point": True})
        sender.assert_called_once_with("http://receiver.example/result", {"end_point": True}, "one")
        response = client.post("/return", json={"gripper_open": True, "request_id": "one"})
        self.assertTrue(response.json()["duplicate"])
        motion.assert_called_once()

    def test_false_and_invalid_bool_do_not_move(self):
        motion = Mock()
        client = self.client(motion)
        self.assertFalse(client.post("/return", json={"gripper_open": False}).json()["accepted"])
        self.assertEqual(client.post("/return", json={"gripper_open": "true"}).status_code, 422)
        motion.assert_not_called()

    def test_concurrent_request_rejected_and_running_stays_false(self):
        entered, release = threading.Event(), threading.Event()
        def motion():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Test worker not released")
        client = self.client(motion)
        try:
            client.post("/return", json={"gripper_open": True, "request_id": "one"})
            self.assertTrue(entered.wait(1))
            self.assertEqual(client.get("/end-point").json(), {"end_point": False})
            response = client.post("/return", json={"gripper_open": True, "request_id": "two"})
            self.assertEqual(response.status_code, 409)
        finally:
            release.set()
        self.wait_done(client)

    def test_failed_motion_reports_false(self):
        sender = Mock()
        client = self.client(Mock(side_effect=TimeoutError("waypoint not reached")), sender)
        client.post("/return", json={"gripper_open": True, "request_id": "fail"})
        result = self.wait_done(client)
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["end_point"])
        sender.assert_called_once_with("http://receiver.example/result", {"end_point": False}, "fail")

    def test_delivery_failure_never_repeats_motion(self):
        motion, sender = Mock(), Mock(side_effect=OSError("offline"))
        client = self.client(motion, sender)
        client.post("/return", json={"gripper_open": True})
        result = self.wait_done(client)
        self.assertTrue(result["end_point"])
        self.assertEqual(result["delivery"], "failed")
        self.assertEqual(sender.call_count, 3)
        motion.assert_called_once()

    def test_without_callback_can_poll(self):
        client = self.client(callback=None)
        client.post("/return", json={"gripper_open": True})
        result = self.wait_done(client)
        self.assertEqual(result["delivery"], "disabled")
        self.assertTrue(result["end_point"])

    def test_http_sender_serializes_body_and_rejects_server_error(self):
        bodies = []
        def handler(request):
            bodies.append(json.loads(request.content))
            self.assertEqual(request.headers["X-Request-ID"], "test")
            return httpx.Response(503, request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(api.httpx, "Client", return_value=client):
            with self.assertRaises(httpx.HTTPStatusError):
                api.send_result("http://receiver/result", {"end_point": True}, "test")
        self.assertEqual(bodies, [{"end_point": True}])


if __name__ == "__main__":
    unittest.main()
