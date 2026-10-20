"""Motor-free tests: python -m unittest discover -s tests -p 'test_eval_bi_return.py'."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import eval_bi as ev


class ReturnMotionTests(unittest.TestCase):
    def test_cli_defaults_match_measured_left_poses(self):
        import json
        from pathlib import Path
        args = ev.parse_args(["--policy-path", "unused"])
        for name, filename in (("return_via", "left_return_via_measured.json"),
                               ("start_pose", "left_start_pose_measured.json")):
            measured = json.loads((Path(ev.__file__).parent / filename).read_text())
            self.assertEqual(getattr(args, name), measured["values"])
        disabled = ev.parse_args(["--policy-path", "unused", "--no-return"])
        self.assertIsNone(ev.validate_return_args(disabled))

    def test_policy_right_commands_are_discarded(self):
        robot = SimpleNamespace(left_arm=Mock(), right_arm=Mock())
        robot.left_arm.send_action.side_effect = lambda command: command
        result = ev.LeftOnlyBiOmxFollower.send_action(
            robot, {"left_gripper.pos": 50, "right_gripper.pos": 90})
        robot.left_arm.send_action.assert_called_once_with({"gripper.pos": 50})
        robot.right_arm.send_action.assert_not_called()
        self.assertEqual(result, {"left_gripper.pos": 50})

    def test_right_connect_and_disconnect_do_not_configure_or_change_torque(self):
        robot = SimpleNamespace(left_arm=Mock(), right_arm=Mock(), cameras={})
        ev.LeftOnlyBiOmxFollower.connect(robot)
        robot.right_arm.connect.assert_not_called()
        robot.right_arm.bus.connect.assert_called_once_with()
        ev.LeftOnlyBiOmxFollower.disconnect(robot)
        robot.right_arm.bus.disconnect.assert_called_once_with(disable_torque=False)
        robot.left_arm.bus.disconnect.assert_called_once_with(disable_torque=True)

    def setUp(self):
        self.args = SimpleNamespace(
            return_via=[10.] * 6, start_pose=[20.] * 6,
            return_via_time=.1, return_home_time=.1, return_tolerance=.01,
            return_settle_time=.2, fps=30, episode_time=1, task="test",
        )
        self.now = 0.
        self.state = dict.fromkeys(ev.POSE_KEYS, 0.)
        self.commands = []
        self.robot = Mock()
        self.robot.send_action.side_effect = self.send
        self.clock = patch.object(ev.time, "perf_counter", side_effect=lambda: self.now)
        self.sleep = patch.object(ev, "precise_sleep", side_effect=self.advance)
        self.feedback = patch.object(ev, "read_joint_positions", side_effect=lambda _: self.state.copy())
        for context in (self.clock, self.sleep, self.feedback):
            context.start()
            self.addCleanup(context.stop)

    def advance(self, seconds):
        self.now += max(seconds, .001)

    def send(self, action):
        self.commands.append(action.copy())
        self.state.update(action)

    def test_reaches_waypoint_before_home(self):
        result = ev.return_to_start(self.robot, self.args)
        via = ev.pose_action(self.args.return_via)
        home = ev.pose_action(self.args.start_pose)
        self.assertEqual(result, home)
        index = self.commands.index(via)
        self.assertEqual(self.commands[-1], home)
        self.assertTrue(all(max(cmd.values()) <= 10 for cmd in self.commands[:index + 1]))
        self.assertGreaterEqual(self.now, .2)

    def test_stuck_waypoint_never_starts_home(self):
        self.robot.send_action.side_effect = lambda command: self.commands.append(command.copy())
        with self.assertRaises(TimeoutError):
            ev.return_to_start(self.robot, self.args)
        self.assertTrue(all(max(cmd.values()) <= 10 for cmd in self.commands))

    def test_invalid_pose_fails_before_write(self):
        for bad in (float("nan"), float("inf"), 101, -101):
            self.args.start_pose[0] = bad
            with self.assertRaises(ValueError):
                ev.return_to_start(self.robot, self.args)
        self.robot.send_action.assert_not_called()

    def test_both_poses_required(self):
        self.args.start_pose = None
        with self.assertRaises(ValueError):
            ev.return_to_start(self.robot, self.args)
        self.robot.send_action.assert_not_called()

    def test_dry_run_does_not_read_or_write_hardware(self):
        with patch.object(ev, "read_joint_positions") as read:
            ev.return_to_start(self.robot, self.args, dry_run=True)
        read.assert_not_called()
        self.robot.send_action.assert_not_called()

    def test_interrupt_does_not_continue_to_home(self):
        self.robot.send_action.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            ev.return_to_start(self.robot, self.args)
        self.assertEqual(self.robot.send_action.call_count, 1)

    def test_request_during_inference_discards_policy_action(self):
        policy = Mock()
        policy.config.device = "cpu"
        requested = [False]
        def inference(**kwargs):
            requested[0] = True
            return "unused prediction"
        with patch.object(ev, "get_safe_torch_device"), \
             patch.object(ev, "build_dataset_frame"), \
             patch.object(ev, "predict_action", side_effect=inference), \
             patch.object(ev, "return_to_start", return_value={"home": 1}) as go_home, \
             patch.object(ev, "make_robot_action") as unpack:
            result = ev.run_episode(
                self.robot, policy, Mock(), Mock(), {}, self.args,
                should_return=lambda obs: requested[0],
            )
        self.assertEqual(result, (0, {"home": 1}))
        self.robot.send_action.assert_not_called()
        unpack.assert_not_called()
        go_home.assert_called_once()

    def test_timeout_returns_when_configured_and_legacy_skips_return(self):
        # Shorten the episode so one policy step reaches the end.
        self.args.episode_time = .01
        for enabled in (True, False):
            self.now = 0
            if not enabled:
                self.args.return_via = self.args.start_pose = None
            with patch.object(ev, "get_safe_torch_device"), \
                 patch.object(ev, "build_dataset_frame"), \
                 patch.object(ev, "predict_action"), \
                 patch.object(ev, "make_robot_action", return_value={"policy": 1}), \
                 patch.object(ev, "return_to_start", return_value={"home": 1}) as go_home:
                result = ev.run_episode(self.robot, Mock(), Mock(), Mock(), {}, self.args)
            self.assertEqual(result, (1, {"home": 1} if enabled else {"policy": 1}))
            self.assertEqual(go_home.call_count, int(enabled))


if __name__ == "__main__":
    unittest.main()
