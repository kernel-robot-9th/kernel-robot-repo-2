import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

import eval_bi_api as api
import pinky_move as pm

KEYS = [f"{side}_{j}" for side in pm.SIDES for j in pm.JOINT_NAMES]


class FakeArms:
    """Joints follow commands instantly; grippers stall at `stall` (object in hand)."""
    def __init__(self, stall=None):
        self.pos = {k: (50.0 if k.endswith("_gripper") else 0.0) for k in KEYS}
        self.stall = stall
        self.log = []

    def read(self):
        return dict(self.pos)

    def write(self, command):
        self.log.append(dict(command))
        for key, value in command.items():
            if key.endswith("_gripper") and self.stall is not None:
                value = max(value, self.stall)
            self.pos[key] = value


def run_fast(arms, steps, **kw):
    clock = iter(range(10**7))
    return pm.run_sequence(arms.read, arms.write, steps, sleep=lambda s: None,
                           clock=lambda: next(clock) / 100, **kw)


class SequenceTests(unittest.TestCase):
    def load(self):
        pick, home, _ = pm.load_sequence(pm.DEFAULT_SEQUENCE)
        return pick, home

    def test_order_both_arms_and_final_pose(self):
        pick, home = self.load()
        self.assertEqual([s["name"] for s in pick],
                         ["approach_high", "above_target", "close_gripper", "lift", "release_gripper"])
        self.assertEqual([s["name"] for s in home], ["return_via", "return_start"])
        arms = FakeArms(stall=48.0)
        blocked = run_fast(arms, pick[:4])  # up to lift: object held
        self.assertEqual(blocked, {"left_gripper", "right_gripper"})
        self.assertAlmostEqual(arms.pos["left_gripper"], 48.0)
        # Lift never re-commands the grippers open.
        self.assertTrue(all("left_gripper" not in c for c in arms.log[-5:]))
        blocked = run_fast(arms, pick[4:], gripper_blocked=blocked)  # release
        self.assertEqual(blocked, set())
        for key, value in pick[4]["target"].items():
            self.assertAlmostEqual(arms.pos[key], value)
        for key, value in pick[3]["target"].items():
            self.assertAlmostEqual(arms.pos[key], value)
        self.assertTrue(any(k.startswith("right_") for k in pick[0]["target"]))
        # Return ends at both start poses with the grippers closed to their rest value.
        self.assertIn("left_gripper", home[-1]["target"])
        self.assertNotIn("left_gripper", home[0]["target"])
        arms.stall = None
        run_fast(arms, home, gripper_blocked=blocked)
        for key, value in home[-1]["target"].items():
            self.assertAlmostEqual(arms.pos[key], value)
        # Approach opens less than the full release.
        self.assertLess(pick[0]["target"]["left_gripper"], pick[4]["target"]["left_gripper"])

    def test_grippers_open_while_approaching(self):
        pick, _ = self.load()
        arms = FakeArms()
        run_fast(arms, pick[:1])  # grippers open while moving above the target
        self.assertIn("left_gripper", pick[0]["target"])
        for key, value in pick[0]["target"].items():
            self.assertAlmostEqual(arms.pos[key], value)

    def test_arm_that_never_arrives_raises(self):
        arms = FakeArms()
        arms.write = lambda c: None
        with self.assertRaises(RuntimeError):
            run_fast(arms, self.load()[0])

    def test_placeholder_never_moves(self):
        data = json.loads(pm.DEFAULT_SEQUENCE.read_text())
        data["placeholder"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
        self.addCleanup(Path(f.name).unlink)
        with self.assertRaises(RuntimeError):
            pm.pick(f.name)
        with self.assertRaises(RuntimeError):
            pm.return_home(f.name)

    def test_bad_values_rejected(self):
        data = json.loads(pm.DEFAULT_SEQUENCE.read_text())
        data["steps"][0]["right"] = [0, 0, 0, 0, 150]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
        self.addCleanup(Path(f.name).unlink)
        with self.assertRaises(ValueError):
            pm.load_sequence(f.name)


class PinkyApiTests(unittest.TestCase):
    def client(self, pinky=None, home=None, sender=None, runner=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pinky, self.home = pinky or Mock(), home or Mock()
        self.sender = sender or Mock()
        app = api.create_app("http://receiver.example/result", Mock(), self.sender,
                             lock_path=Path(folder.name) / "api.lock",
                             policy_runner=runner or Mock(), pinky_motion=self.pinky,
                             home_motion=self.home)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def wait_done(self, client):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with client.app.state.controller.lock:
                busy = client.app.state.controller.busy
            if not busy:
                return client.get("/status").json()
            time.sleep(.005)
        self.fail("worker did not finish")

    def payloads(self):
        return [c.args[1] for c in self.sender.call_args_list]

    def test_pinky_alone_waits_and_does_not_move(self):
        client = self.client()
        response = client.post("/pinky", json={"pinky_arrive": True})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["accepted"])
        self.assertTrue(response.json()["waiting"])
        self.pinky.assert_not_called()

    def test_end_point_then_pinky_runs_pick_then_return(self):
        client = self.client()
        client.post("/command", json={"command": "pick", "request_id": "c1"})
        self.assertTrue(self.wait_done(client)["end_point"])
        self.pinky.assert_not_called()  # end_point alone is not enough
        self.assertFalse(client.post("/pinky", json={"pinky_arrive": False}).json()["accepted"])
        self.assertTrue(client.post("/pinky", json={"pinky_arrive": True}).json()["accepted"])
        result = self.wait_done(client)
        self.assertEqual(result["pinky"], "completed")
        self.assertTrue(result["end_point"])
        self.pinky.assert_called_once()
        self.home.assert_called_once()
        self.assertEqual(self.payloads(), [{"end_point": True}, {"pinky_done": True}, {"end_point": True}])
        # The sender keeps sending true: no second pick for the same cycle.
        self.assertFalse(client.post("/pinky", json={"pinky_arrive": True}).json()["accepted"])
        self.wait_done(client)
        self.pinky.assert_called_once()
        self.assertEqual(client.post("/pinky", json={"pinky_arrive": "true"}).status_code, 422)

    def test_pinky_during_imitation_starts_after_end_point(self):
        entered, release = threading.Event(), threading.Event()
        def runner(command, event):
            entered.set()
            release.wait(2)
        client = self.client(runner=runner)
        try:
            client.post("/command", json={"command": "pick", "request_id": "c1"})
            self.assertTrue(entered.wait(1))
            self.assertFalse(client.post("/pinky", json={"pinky_arrive": True}).json()["accepted"])
            self.pinky.assert_not_called()
        finally:
            release.set()
        deadline = time.monotonic() + 3
        while self.home.call_count == 0 and time.monotonic() < deadline:
            time.sleep(.005)
        result = self.wait_done(client)
        self.assertEqual(result["pinky"], "completed")
        self.pinky.assert_called_once()

    def test_pinky_false_cancels_waiting(self):
        entered, release = threading.Event(), threading.Event()
        def runner(command, event):
            entered.set()
            release.wait(2)
        client = self.client(runner=runner)
        try:
            client.post("/command", json={"command": "pick", "request_id": "c1"})
            self.assertTrue(entered.wait(1))
            client.post("/pinky", json={"pinky_arrive": True})
            client.post("/pinky", json={"pinky_arrive": False})
        finally:
            release.set()
        self.wait_done(client)
        time.sleep(.05)
        self.pinky.assert_not_called()

    def test_failed_imitation_blocks_pinky(self):
        client = self.client(runner=Mock(side_effect=TimeoutError("no return")))
        client.post("/command", json={"command": "pick", "request_id": "c1"})
        self.assertFalse(self.wait_done(client)["end_point"])
        self.assertFalse(client.post("/pinky", json={"pinky_arrive": True}).json()["accepted"])
        self.pinky.assert_not_called()

    def test_pick_failure_reports_false_and_skips_return(self):
        client = self.client(pinky=Mock(side_effect=RuntimeError("tracking")))
        client.post("/command", json={"command": "pick", "request_id": "c1"})
        self.wait_done(client)
        client.post("/pinky", json={"pinky_arrive": True})
        result = self.wait_done(client)
        self.assertEqual(result["pinky"], "failed")
        self.assertFalse(result["end_point"])
        self.home.assert_not_called()
        self.assertEqual(self.payloads()[-1], {"pinky_done": False})

    def test_return_failure_reports_end_point_false(self):
        client = self.client(home=Mock(side_effect=TimeoutError("via")))
        client.post("/command", json={"command": "pick", "request_id": "c1"})
        self.wait_done(client)
        client.post("/pinky", json={"pinky_arrive": True})
        result = self.wait_done(client)
        self.assertEqual(result["pinky"], "return_failed")
        self.assertEqual(self.payloads()[-2:], [{"pinky_done": True}, {"end_point": False}])


if __name__ == "__main__":
    unittest.main()
