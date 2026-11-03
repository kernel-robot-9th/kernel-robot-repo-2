#!/usr/bin/env python3
"""Top-down pick & place (and two-arm carry) for OMX-F arms through MoveIt move_group.

Arm targets come from the closed-form IK in omx_ik.py and are sent to move_group
(/move_action) as joint-space goals, so MoveIt still does collision checking and
trajectory execution. One node drives one arm (single setup, unprefixed names) or
several (`arm_names: [left, right]`, joints `left_joint1`, groups `left_arm`, ...).

Goals are given in `input_frame` (link0 for one arm, world for two) with heights above
the work surface; each arm converts them to its own base frame through TF.
"""
import math
import os
import threading
import time

import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

from builtin_interfaces.msg import Duration as DurationMsg
from control_msgs.action import FollowJointTrajectory, GripperCommand
from moveit_msgs.action import ExecuteTrajectory, MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint, MoveItErrorCodes, RobotTrajectory
from sensor_msgs.msg import Image, JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from vla_interfaces.action import CarryTogether, PickPlace

from vla_executor.grasp_check import blob_centre, centering_step, draw_check, grasp_fill
from vla_executor.omx_ik import fk_tool, top_down_ik
from vla_perception.table_geometry import DEFAULT_HSV, image_to_numpy

JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
# per-arm defaults; '' = the single-arm setup with ROBOTIS' unprefixed names
ARM_DEFAULTS = {
    '': dict(joint_prefix='', group='arm', gripper_action='/gripper_controller/gripper_cmd',
             base_frame='link0', wrist_topic='/wrist_camera/image_raw'),
}


def arm_default(name, key):
    if name in ARM_DEFAULTS:
        return ARM_DEFAULTS[name][key]
    return dict(joint_prefix=f'{name}_', group=f'{name}_arm',
                gripper_action=f'/{name}_gripper_controller/gripper_cmd',
                base_frame=f'{name}_link0', wrist_topic=f'/{name}/wrist_camera/image_raw')[key]


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


class GraspError(RuntimeError):
    """The object is not in the gripper after lifting."""


class Arm:
    """One OMX-F arm: names, clients, wrist camera and its pose in the input frame."""

    def __init__(self, node, name, cfg, cb):
        self.name = name
        self.prefix = cfg['joint_prefix']
        self.group = cfg['group']
        self.base_frame = cfg['base_frame']
        self.joints = [self.prefix + j for j in JOINTS]
        self.gripper = ActionClient(node, GripperCommand, cfg['gripper_action'], callback_group=cb)
        # direct backend (real follower): arm and gripper joints share one JointTrajectoryController
        self.trajectory = ActionClient(node, FollowJointTrajectory, cfg['trajectory_action'], callback_group=cb)
        self.gripper_joint = self.prefix + 'gripper_joint_1'
        self.wrist_msg = None
        self.wrist_stamp = 0.0
        node.create_subscription(Image, cfg['wrist_topic'], self._on_wrist, 1, callback_group=cb)
        self.base = None   # (x, y, z, yaw) of base_frame in the input frame

    def _on_wrist(self, msg):
        self.wrist_msg = msg
        self.wrist_stamp = time.monotonic()

    def label(self, text):
        return f'{self.name} {text}' if self.name else text

    def to_base(self, x, y, z, yaw):
        bx, by, bz, byaw = self.base
        c, s = math.cos(byaw), math.sin(byaw)
        dx, dy = x - bx, y - by
        return c * dx + s * dy, -s * dx + c * dy, z - bz, wrap(yaw - byaw)

    def reach(self, x, y):
        """Horizontal distance from this arm's base to an input-frame point."""
        return math.hypot(x - self.base[0], y - self.base[1])


class PickPlaceExecutor(Node):

    def __init__(self, node_name='vla_executor', serve=True, **kwargs):
        """serve=False: motion helpers only (no action servers, no observe on start),
        for tools such as the calibration scripts."""
        super().__init__(node_name, **kwargs)
        p = self.declare_parameter
        p('arm_names', [''])          # [''] = one unprefixed arm; [left, right] = two arms
        p('input_frame', 'link0')     # frame of goal coordinates; z = 0 is the work surface
        p('grasp_z', 0.014)          # end_effector_link height above the surface when grasping a block
        p('place_z', 0.014)          # end_effector_link height above the surface when releasing
        p('stack_clearance', 0.004)  # extra release height when stacking
        p('approach_height', 0.06)   # pre-grasp / retreat height above grasp_z
        p('block_height', 0.025)
        p('gripper_open', 1.0)
        p('gripper_closed', 0.05)   # below finger contact (~0.18 on a 25 mm block) for a firm grip
        p('gripper_release', 0.35)   # open only this far when releasing: a full-speed open
                                     # from a deep squeeze flings the block (and the stack)
        p('gripper_effort', 5.0)
        p('velocity_scaling', 0.3)
        p('acceleration_scaling', 0.3)
        p('planning_time', 5.0)
        p('min_reach', 0.09)
        p('max_reach', 0.25)
        # folded pose that keeps the arm out of the top camera's view
        p('observe_joints', [0.0, -1.57, 1.57, 1.57, 0.0])
        p('planning_pipeline', 'pilz_industrial_motion_planner')
        p('planner_id', 'PTP')
        p('observe_on_start', True)  # fold the arms out of the camera view once move_group is up
        p('settle_velocity', 0.02)   # rad/s; wait for the arm to stop before the next plan
        p('settle_timeout', 3.0)
        # wrist-camera grasp check after lifting
        p('wrist_check', True)
        p('wrist_required', True)     # no wrist image -> fail (False: warn and continue)
        p('wrist_image_topic', '/wrist_camera/image_raw')   # single-arm setup
        p('wrist_roi', [0.40, 0.40, 0.65, 0.58])   # x0, y0, x1, y1 (fractions): just below the fingertips
        p('wrist_min_fill', 0.6)      # fraction of the ROI that must show the block color
        p('wrist_timeout', 2.0)
        # real arm (2026-10-22): no MoveIt; joint goals go straight to the follower's JointTrajectoryController
        p('motion_backend', 'moveit')      # 'moveit' (sim) | 'direct' (real follower, ROBOTIS omx_f_follower_ai)
        p('trajectory_action', '/arm_controller/follow_joint_trajectory')
        p('direct_speed_deg_s', 15.0)      # slowest joint sets the move time
        p('direct_min_time', 2.0)
        p('surface_plane', [0.0, 0.0, 0.0])   # tool height at the work surface in the base frame: a + b x + c y
        p('safe_z_min', -1.0)              # direct: refuse joint paths whose tool dips below this (base frame)
        # wrist-camera centering before the grasp (real arm: top-view calibration error ~2-3 cm)
        p('wrist_center', False)
        p('wrist_center_height', 0.04)     # above the grasp height
        p('wrist_center_ref', [295.0, 190.0])   # block centre in the wrist image when a grasp there succeeds
        p('wrist_center_probe', 0.01)      # probe moves [m] that measure the image Jacobian
        p('wrist_center_tol', 20.0)        # px
        p('wrist_center_iters', 2)
        p('wrist_center_max_shift', 0.04)  # m
        p('close_at_observe', False)       # close the gripper before folding (real arm: comes back closed)
        p('min_approach_height', -1.0)     # < approach_height: lower the approach (1 cm steps) where it is out of reach
        p('wrist_center_shift_place', False)   # move the place point by the top-camera error the wrist found
        p('fold_on_error', False)          # any other failure: fold the arm(s) too (the gripper is not opened)
        p('wrist_center_offset', [0.0, 0.0])   # m, added to the centred grasp point (hand tuning on the real arm)
        p('wrist_center_look_ahead', 0.0)  # m, first look this far beyond the block (away from the base): the
                                           # block then sits mid-image even when the top camera is a few cm off
        p('wrist_debug_dir', '')           # save every centring view here (one folder per pick); '' = off
        # two-arm carry
        p('tray_handle', 0.025)       # handle size at each tray end
        p('tray_grasp_z', 0.022)      # end_effector_link height above the surface at a tray handle
        p('tray_color', 'purple')
        p('carry_lift', 0.04)         # how high the tray is lifted while carried
        p('carry_step', 0.01)         # waypoint spacing [m]
        p('carry_speed', 0.03)        # tray speed [m/s]
        p('carry_joint_speed', 0.5)   # cap on any joint's speed while carrying [rad/s]
        p('carry_release', 1.0)       # open fully when letting go of the tray: a half-open gripper
                                      # can stay hooked on a handle and lift the tray on the retreat
        # block colors (shared with perception; calibration writes these)
        p('colors', list(DEFAULT_HSV))
        for c, rng in DEFAULT_HSV.items():
            p(f'hsv.{c}', rng)
        for name in self.prm('arm_names'):
            if name:
                for k in ('joint_prefix', 'group', 'gripper_action', 'base_frame', 'wrist_topic'):
                    p(f'arms.{name}.{k}', arm_default(name, k))

        cb = ReentrantCallbackGroup()
        self.arms = {n: Arm(self, n, self._arm_config(n), cb) for n in self.prm('arm_names')}
        self._move = ActionClient(self, MoveGroup, 'move_action', callback_group=cb)
        self._exec = ActionClient(self, ExecuteTrajectory, 'execute_trajectory', callback_group=cb)
        self._busy = threading.Lock()
        self._joint_vel = {}
        self._joint_pos = {}
        self.create_subscription(JointState, '/joint_states', self._on_joints, 10, callback_group=cb)
        self._wrist_dbg = self.create_publisher(Image, '/vla/wrist_debug', 1)
        self._wrist_dir, self._wrist_n = '', 0   # centring views on disk (wrist_debug_dir)
        self._tf = Buffer()
        self._tf_listener = TransformListener(self._tf, self)
        if not serve:
            return
        self._server = ActionServer(
            self, PickPlace, 'pick_place', self._execute,
            goal_callback=self._on_goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb)
        if len(self.arms) > 1:
            self._carry_server = ActionServer(
                self, CarryTogether, 'carry_together', self._execute_carry,
                goal_callback=self._on_goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                callback_group=cb)
        self.get_logger().info(f'arms {list(self.arms)} ready on /pick_place'
                               + (' and /carry_together' if len(self.arms) > 1 else ''))
        if self.prm('observe_on_start'):
            threading.Thread(target=self._observe_on_start, daemon=True).start()

    def _arm_config(self, name):
        keys = ('joint_prefix', 'group', 'gripper_action', 'base_frame', 'wrist_topic')
        if not name:
            cfg = {k: arm_default('', k) for k in keys}
            cfg['wrist_topic'] = self.prm('wrist_image_topic')
        else:
            cfg = {k: self.prm(f'arms.{name}.{k}') for k in keys}
        cfg['trajectory_action'] = self.prm('trajectory_action')
        return cfg

    def _observe_on_start(self):
        for _ in range(10):
            try:
                with self._busy:
                    for arm in self.arms.values():
                        self.go_observe(arm)
                return
            except RuntimeError as e:
                self.get_logger().warn(f'observe on start failed ({e}), retrying')
                time.sleep(3.0)

    def prm(self, name):
        return self.get_parameter(name).value

    def arm(self, name=None):
        """Arm by name; None = the first (only) arm."""
        if name is None:
            return next(iter(self.arms.values()))
        if name not in self.arms:
            raise RuntimeError(f'unknown arm "{name}" (have {list(self.arms)})')
        return self.arms[name]

    def _on_joints(self, msg):
        self._joint_pos.update(zip(msg.name, msg.position))
        if msg.velocity:
            self._joint_vel.update(zip(msg.name, msg.velocity))

    def hsv_ranges(self):
        return {c: list(self.prm(f'hsv.{c}')) for c in self.prm('colors')
                if self.has_parameter(f'hsv.{c}')}

    # ------------------------------------------------------------------ frames
    def arm_base(self, arm):
        """Base pose of `arm` in the input frame (static, cached)."""
        if arm.base is None:
            src = self.prm('input_frame')
            if src == arm.base_frame:
                arm.base = (0.0, 0.0, 0.0, 0.0)
            else:
                deadline = time.monotonic() + 5.0
                while True:
                    try:
                        t = self._tf.lookup_transform(src, arm.base_frame, Time())
                        break
                    except Exception as e:  # noqa: BLE001
                        if time.monotonic() > deadline:
                            raise RuntimeError(f'no TF {src} -> {arm.base_frame}: {e}')
                        time.sleep(0.1)
                tr, q = t.transform.translation, t.transform.rotation
                yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
                arm.base = (tr.x, tr.y, tr.z, yaw)
        return arm.base

    # ------------------------------------------------------------------ wrist camera
    def latest_wrist_image(self, after=None, timeout=2.0, arm=None):
        """BGR wrist frame received after time.monotonic() value `after` (default: now)."""
        a = self.arm(arm) if not isinstance(arm, Arm) else arm
        t0 = time.monotonic() if after is None else after
        deadline = time.monotonic() + timeout
        while a.wrist_stamp <= t0 and time.monotonic() < deadline:
            time.sleep(0.02)
        return None if a.wrist_stamp <= t0 else image_to_numpy(a.wrist_msg)

    def check_grasp(self, color, arm=None):
        """Wrist-camera check that a block of `color` is between the fingers.

        Returns (ok, fill, seen_color); ok is None when no image is available.
        """
        a = self.arm(arm) if not isinstance(arm, Arm) else arm
        bgr = self.latest_wrist_image(timeout=self.prm('wrist_timeout'), arm=a)
        if bgr is None:
            return None, 0.0, ''
        roi = list(self.prm('wrist_roi'))
        fill, seen = grasp_fill(bgr, self.hsv_ranges(), color, roi)
        ok = fill >= self.prm('wrist_min_fill')
        dbg = draw_check(bgr, roi, fill, seen, ok)
        out = Image()
        out.header = a.wrist_msg.header
        out.height, out.width = dbg.shape[:2]
        out.encoding = 'bgr8'
        out.step = out.width * 3
        out.data = dbg.tobytes()
        self._wrist_dbg.publish(out)
        return ok, fill, seen

    def verify_grasp(self, arm, color, stage):
        if not self.prm('wrist_check'):
            return
        stage(arm.label('verify grasp'))
        ok, fill, seen = self.check_grasp(color, arm)
        if ok is None:
            msg = f'no wrist image for arm "{arm.name}"'
            if self.prm('wrist_required'):
                raise GraspError(f'grasp check failed: {msg}')
            self.get_logger().warn(f'grasp check skipped: {msg}')
        elif not ok:
            raise GraspError(
                f'{arm.label("grasp check failed")}: wrist camera sees {fill * 100:.0f}% '
                f'{color or "block color"} between the fingers '
                f'(need {self.prm("wrist_min_fill") * 100:.0f}%)')
        else:
            self.get_logger().info(f'{arm.label("grasp verified")}: {fill * 100:.0f}% {seen}')

    # ------------------------------------------------------------------ motion
    def wait_settled(self, joints=None):
        """Controllers report success before the arm stops; MoveIt then rejects the next
        trajectory because its start deviates from the current state."""
        joints = joints or [j for a in self.arms.values() for j in a.joints]
        deadline = time.monotonic() + self.prm('settle_timeout')
        limit = self.prm('settle_velocity')
        still_since = None
        while time.monotonic() < deadline:
            v = max((abs(self._joint_vel.get(j, 0.0)) for j in joints), default=0.0)
            if v < limit:
                still_since = still_since or time.monotonic()
                if time.monotonic() - still_since > 0.2:
                    return
            else:
                still_since = None
            time.sleep(0.02)
        self.get_logger().warn('arm did not settle before timeout')

    def _wait_result(self, goal_future, timeout):
        """Block (from an action-server thread) until a sub-action finishes."""
        evt = threading.Event()
        goal_future.add_done_callback(lambda _: evt.set())
        if not evt.wait(timeout):
            return None
        handle = goal_future.result()
        if handle is None or not handle.accepted:
            return None
        res_future = handle.get_result_async()
        evt2 = threading.Event()
        res_future.add_done_callback(lambda _: evt2.set())
        if not evt2.wait(timeout):
            return None
        return res_future.result().result

    def direct(self):
        return self.prm('motion_backend') == 'direct'

    def _send_trajectory(self, a, names, positions, seconds, label):
        if not a.trajectory.wait_for_server(timeout_sec=10.0):
            raise RuntimeError(f'{a.label(label)}: {self.prm("trajectory_action")} not available')
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(names)
        sec = int(seconds)
        goal.trajectory.points = [JointTrajectoryPoint(
            positions=[float(v) for v in positions],
            time_from_start=DurationMsg(sec=sec, nanosec=int((seconds - sec) * 1e9)))]
        result = self._wait_result(a.trajectory.send_goal_async(goal), seconds + 30.0)
        if result is None or result.error_code != 0:
            raise RuntimeError(f'{a.label(label)}: trajectory failed '
                               f'(error_code={None if result is None else result.error_code})')

    def _move_direct(self, q, label, a):
        now = [self._joint_pos.get(j) for j in a.joints]
        if None in now:
            raise RuntimeError(f'{a.label(label)}: no /joint_states for {a.joints}')
        steps = 40      # the controller interpolates in joint space: check the whole path, not just the end
        low = min(fk_tool([c + (t - c) * k / steps for c, t in zip(now, q)])[2] for k in range(steps + 1))
        if low < self.prm('safe_z_min') - 0.002:
            raise RuntimeError(f'{a.label(label)}: joint path dips to tool z {low:+.3f} '
                               f'(safe_z_min {self.prm("safe_z_min"):+.3f})')
        seconds = max(self.prm('direct_min_time'),
                      max(abs(math.degrees(t - c)) for c, t in zip(now, q)) / self.prm('direct_speed_deg_s'))
        self.get_logger().info(f'[{a.label(label)}] -> {[round(v, 3) for v in q]} ({seconds:.1f} s)')
        self._send_trajectory(a, a.joints, q, seconds, label)
        self.wait_settled(a.joints)

    def move_joints(self, q, label, arm=None):
        a = self.arm(arm) if not isinstance(arm, Arm) else arm
        if self.direct():
            return self._move_direct(q, label, a)
        if not self._move.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('move_group action server not available')
        goal = MoveGroup.Goal()
        req = goal.request
        req.group_name = a.group
        req.num_planning_attempts = 3
        req.allowed_planning_time = float(self.prm('planning_time'))
        req.max_velocity_scaling_factor = float(self.prm('velocity_scaling'))
        req.max_acceleration_scaling_factor = float(self.prm('acceleration_scaling'))
        req.pipeline_id = self.prm('planning_pipeline')
        req.planner_id = self.prm('planner_id')
        c = Constraints()
        for name, val in zip(a.joints, q):
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = float(val)
            jc.tolerance_above = jc.tolerance_below = 0.005
            jc.weight = 1.0
            c.joint_constraints.append(jc)
        req.goal_constraints.append(c)
        goal.planning_options.plan_only = False
        goal.planning_options.replan = True
        goal.planning_options.replan_attempts = 2

        self.get_logger().info(f'[{a.label(label)}] -> {[round(v, 3) for v in q]}')
        result = self._wait_result(self._move.send_goal_async(goal), 60.0)
        if result is None or result.error_code.val != MoveItErrorCodes.SUCCESS:
            code = None if result is None else result.error_code.val
            raise RuntimeError(f'{a.label(label)}: move_group failed (error_code={code})')
        self.wait_settled(a.joints)

    def gripper(self, position, label, arm=None):
        a = self.arm(arm) if not isinstance(arm, Arm) else arm
        if self.direct():   # current-limited position mode: closing on a block stops at the block
            self.get_logger().info(f'[{a.label(label)}] gripper -> {position}')
            self._send_trajectory(a, [a.gripper_joint], [position], 2.0, label)
            time.sleep(0.3)
            return self._joint_pos.get(a.gripper_joint)
        if not a.gripper.wait_for_server(timeout_sec=10.0):
            raise RuntimeError(f'{a.label("gripper")} action server not available')
        goal = GripperCommand.Goal()
        goal.command.position = float(position)
        goal.command.max_effort = float(self.prm('gripper_effort'))
        self.get_logger().info(f'[{a.label(label)}] gripper -> {position}')
        result = self._wait_result(a.gripper.send_goal_async(goal), 15.0)
        if result is None:
            raise RuntimeError(f'{a.label(label)}: gripper command failed')
        return result

    def ik_or_fail(self, x, y, z, yaw, label, arm=None):
        """IK for an input-frame target (z above the work surface)."""
        a = self.arm(arm) if not isinstance(arm, Arm) else arm
        self.arm_base(a)
        bx, by, bz, byaw = a.to_base(x, y, z, yaw)
        sa, sb, sc = self.prm('surface_plane')
        bz += sa + sb * bx + sc * by        # z is above the work surface; the real surface is a tilted plane
        r = math.hypot(bx, by)
        if not self.prm('min_reach') <= r <= self.prm('max_reach'):
            raise RuntimeError(f'{a.label(label)}: ({x:.3f}, {y:.3f}) out of reach (r={r:.3f} m)')
        q = top_down_ik(bx, by, bz, byaw)
        if q is None:
            raise RuntimeError(f'{a.label(label)}: no IK solution for ({x:.3f}, {y:.3f}, {z:.3f})')
        return q

    def go_observe(self, arm=None):
        if self.prm('close_at_observe'):
            self.gripper(self.prm('gripper_closed'), 'close', arm)
        self.move_joints(self.prm('observe_joints'), 'observe', arm)

    def recover(self, arm=None):
        """Open the gripper(s) and fold the arm(s) out of the camera view."""
        arms = list(self.arms.values()) if arm is None else [self.arm(arm) if not isinstance(arm, Arm) else arm]
        for a in arms:
            self.gripper(self.prm('gripper_open'), 'open', a)
            self.go_observe(a)

    # ------------------------------------------------------------------ pick & place
    def plan_pick_place(self, g, arm):
        """All joint targets for one arm, or raise if it cannot do the job."""
        pick_z = self.prm('grasp_z') + g.pick_z_offset
        place_z = self.place_z(g)
        return {
            'pre': self.approach_ik(g.pick_x, g.pick_y, pick_z, g.pick_yaw, 'pre-grasp', arm),
            'grasp': self.ik_or_fail(g.pick_x, g.pick_y, pick_z, g.pick_yaw, 'grasp', arm),
            'pre_place': self.approach_ik(g.place_x, g.place_y, place_z, g.place_yaw, 'pre-place', arm),
            'place': self.ik_or_fail(g.place_x, g.place_y, place_z, g.place_yaw, 'place', arm),
        }

    def place_z(self, g):
        # on a block: release a few mm above it; pressing block-on-block makes the
        # contact interpenetrate and kicks the lower block away
        z = self.prm('place_z') + g.place_z_offset
        return z + self.prm('stack_clearance') if g.place_z_offset > 0.0 else z

    def approach_ik(self, x, y, z, yaw, label, arm):
        """IK approach_height above z; near the edge of reach, down to min_approach_height in 1 cm steps."""
        up, low = self.prm('approach_height'), self.prm('min_approach_height')
        while True:
            try:
                return self.ik_or_fail(x, y, z + up, yaw, label, arm)
            except RuntimeError:
                if up - 0.01 < low - 1e-9:
                    raise
                up -= 0.01

    def choose_arm(self, g):
        """The requested arm, or the nearest one that reaches both pick and place."""
        names = [g.arm] if getattr(g, 'arm', '') else list(self.arms)
        plans, errors = {}, []
        for n in names:
            a = self.arm(n)
            try:
                plans[n] = self.plan_pick_place(g, a)
            except RuntimeError as e:
                errors.append(str(e))
        if not plans:
            what = f'arm "{g.arm}" cannot reach' if getattr(g, 'arm', '') else 'no arm reaches both'
            raise RuntimeError(f'{what} pick ({g.pick_x:.3f}, {g.pick_y:.3f}) and place '
                               f'({g.place_x:.3f}, {g.place_y:.3f}): ' + '; '.join(errors))
        best = min(plans, key=lambda n: self.arm(n).reach(g.pick_x, g.pick_y))
        return self.arm(best), plans[best]

    def run_pick_place(self, g, stage=lambda _: None):
        """Full pick & place for a PickPlace goal-like object; raises on failure.

        GraspError means the wrist camera did not see the block after lifting.
        Returns the arm that did it.
        """
        arm, q = self.choose_arm(g)
        stage(arm.label('open gripper'))
        self.gripper(self.prm('gripper_open'), 'open', arm)
        stage(arm.label('pre-grasp'))
        self.move_joints(q['pre'], 'pre-grasp', arm)
        if self.prm('wrist_center'):
            stage(arm.label('center on block (wrist camera)'))
            q = self.center_on_block(g, arm, q)
        stage(arm.label('grasp'))
        self.move_joints(q['grasp'], 'grasp', arm)
        stage(arm.label('close gripper'))
        self.gripper(self.prm('gripper_closed'), 'close', arm)
        stage(arm.label('lift'))
        self.move_joints(q['pre'], 'lift', arm)
        self.verify_grasp(arm, g.pick_color, stage)
        stage(arm.label('pre-place'))
        self.move_joints(q['pre_place'], 'pre-place', arm)
        stage(arm.label('place'))
        self.move_joints(q['place'], 'place', arm)
        stage(arm.label('release'))
        self.gripper(self.prm('gripper_release'), 'release', arm)
        stage(arm.label('retreat'))
        self.move_joints(q['pre_place'], 'retreat', arm)
        stage(arm.label('observe'))
        self.go_observe(arm)
        return arm

    def _wrist_block(self, arm, color, near, label=''):
        bgr = self.latest_wrist_image(after=time.monotonic() + 0.3, timeout=self.prm('wrist_timeout') + 0.3, arm=arm)
        if bgr is None:
            return None
        ranges = self.hsv_ranges().get(color)
        c = None if ranges is None else blob_centre(bgr, ranges, near)
        if self._wrist_dir:
            import cv2
            img = bgr.copy()
            cv2.drawMarker(img, tuple(int(v) for v in near), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
            if c is not None:
                cv2.circle(img, tuple(int(v) for v in c), 8, (0, 255, 255), 2)
            cv2.putText(img, f'{label} {color}: {"none" if c is None else f"({c[0]:.0f}, {c[1]:.0f})"}', (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            self._wrist_n += 1
            cv2.imwrite(os.path.join(self._wrist_dir, f'{self._wrist_n:02d}_{label.replace(": ", "_").replace(" ", "_")}.jpg'), img)
        return c

    def center_on_block(self, g, arm, q):
        """Move above the block until the wrist camera sees it where a grasp succeeds; re-plan the grasp there.

        Two 1 cm probe moves measure the image Jacobian on the spot. Returns the updated joint plan
        (the input plan when the block is not visible: the grasp then goes by the top camera alone)."""
        pick_z = self.prm('grasp_z') + g.pick_z_offset
        hz, ref = pick_z + self.prm('wrist_center_height'), list(self.prm('wrist_center_ref'))
        probe = self.prm('wrist_center_probe')
        self._wrist_dir, self._wrist_n = '', 0
        if self.prm('wrist_debug_dir'):
            self._wrist_dir = os.path.join(os.path.expanduser(self.prm('wrist_debug_dir')),
                                           time.strftime('%Y%m%d-%H%M%S'))
            os.makedirs(self._wrist_dir, exist_ok=True)
            self.get_logger().info(f'{arm.label("center")}: views -> {self._wrist_dir}')

        def view(x, y, label):
            self.move_joints(self.ik_or_fail(x, y, hz, g.pick_yaw, label, arm), label, arm)
            return self._wrist_block(arm, g.pick_color, ref, label)

        x, y = x_top, y_top = g.pick_x, g.pick_y
        ahead = self.prm('wrist_center_look_ahead')
        base = self.arm_base(arm)
        r = math.hypot(x - base[0], y - base[1])
        if ahead and r > 1e-6:
            xa, ya = x + ahead * (x - base[0]) / r, y + ahead * (y - base[1]) / r
            try:                     # out of reach there: look from the top-camera position instead
                self.ik_or_fail(xa, ya, hz, g.pick_yaw, 'center: look', arm)
                x, y = xa, ya
            except RuntimeError:
                pass
        c0 = view(x, y, 'center: look')
        self.last_centred = False
        if c0 is None:
            self.get_logger().warn(f'{arm.label("center")}: {g.pick_color} block not in the wrist image, skipped')
            return q
        def probe_view(dx, dy, label):
            """Block pixel after a probe move; where that is out of reach, probe the other way and mirror it."""
            try:
                return view(x + dx, y + dy, label)
            except RuntimeError:
                c = view(x - dx, y - dy, label + ' (reversed)')
                return None if c is None else (2 * c0[0] - c[0], 2 * c0[1] - c[1])

        c_dx, c_dy = probe_view(probe, 0.0, 'center: probe x'), probe_view(0.0, probe, 'center: probe y')
        if c_dx is None or c_dy is None:
            self.get_logger().warn(f'{arm.label("center")}: block lost during the probe moves, skipped')
            return q
        J, c, centred = None, c0, False
        for k in range(self.prm('wrist_center_iters')):
            err = math.hypot(c[0] - ref[0], c[1] - ref[1])
            self.get_logger().info(f'{arm.label("center")}: block at ({c[0]:.0f}, {c[1]:.0f}) px, '
                                   f'{err:.0f} px from the grasp point')
            if err <= self.prm('wrist_center_tol'):
                centred = True
                break
            if J is None:
                d, J = centering_step(c0, c_dx, c_dy, probe, ref, self.prm('wrist_center_max_shift'))
            else:   # reuse the measured Jacobian
                d, _ = centering_step(c, c + J[:, 0] * probe, c + J[:, 1] * probe, probe, ref,
                                      self.prm('wrist_center_max_shift'))
            if d is None:
                self.get_logger().warn(f'{arm.label("center")}: probes too small to invert, skipped')
                break
            x, y = x + d[0], y + d[1]
            self.get_logger().info(f'{arm.label("center")}: shift ({d[0] * 1000:+.0f}, {d[1] * 1000:+.0f}) mm')
            c = view(x, y, 'center: shifted')
            if c is None:
                self.get_logger().warn(f'{arm.label("center")}: block lost after the shift')
                break
        off = list(self.prm('wrist_center_offset'))
        if any(off):
            x, y = x + off[0], y + off[1]
            self.get_logger().info(f'{arm.label("center")}: offset ({off[0] * 1000:+.0f}, {off[1] * 1000:+.0f}) mm')
        g.pick_x, g.pick_y = x, y
        self.last_centred = centred          # the calibration tool keeps only converged points
        q = dict(q)
        q['pre'] = self.approach_ik(x, y, pick_z, g.pick_yaw, 'pre-grasp', arm)
        q['grasp'] = self.ik_or_fail(x, y, pick_z, g.pick_yaw, 'grasp', arm)
        if centred and self.prm('wrist_center_shift_place'):
            # the top camera's error here is local: the place point (often the block next to it) shares it
            dx, dy = x - off[0] - x_top, y - off[1] - y_top
            n = math.hypot(dx, dy)
            if n > self.prm('wrist_center_max_shift'):
                dx, dy = dx * self.prm('wrist_center_max_shift') / n, dy * self.prm('wrist_center_max_shift') / n
            px, py = g.place_x + dx, g.place_y + dy
            self.get_logger().info(f'{arm.label("center")}: top camera off by ({dx * 1000:+.0f}, {dy * 1000:+.0f}) mm'
                                   f' here; place ({g.place_x:.3f}, {g.place_y:.3f}) -> ({px:.3f}, {py:.3f})')
            try:
                pz = self.place_z(g)
                q['pre_place'] = self.approach_ik(px, py, pz, g.place_yaw, 'pre-place', arm)
                q['place'] = self.ik_or_fail(px, py, pz, g.place_yaw, 'place', arm)
                g.place_x, g.place_y = px, py
            except RuntimeError as e:
                self.get_logger().warn(f'{arm.label("center")}: shifted place out of reach ({e}); keeping the top-camera place')
        return q

    # ------------------------------------------------------------------ two-arm carry
    def tray_handles(self, x, y, yaw, length):
        d = length / 2.0 - self.prm('tray_handle') / 2.0
        return (x + d * math.cos(yaw), y + d * math.sin(yaw)), (x - d * math.cos(yaw), y - d * math.sin(yaw))

    def assign_handles(self, handles):
        """Map the two handles to the two arms with the smaller total reach."""
        (na, a), (nb, b) = list(self.arms.items())[:2]
        for arm in (a, b):
            self.arm_base(arm)
        h1, h2 = handles
        straight = a.reach(*h1) + b.reach(*h2)
        crossed = a.reach(*h2) + b.reach(*h1)
        return {na: h1, nb: h2} if straight <= crossed else {na: h2, nb: h1}

    def carry_path(self, g):
        """Tray poses (x, y, z, yaw) from grasp, up, across, down; z above the surface."""
        z0 = self.prm('tray_grasp_z')
        z1 = z0 + self.prm('carry_lift')
        # carry the shorter way round: the tray is symmetric end to end
        dyaw = wrap(g.place_yaw - g.tray_yaw)
        if abs(dyaw) > math.pi / 2:
            dyaw -= math.copysign(math.pi, dyaw)
        corners = [(g.tray_x, g.tray_y, z0, g.tray_yaw), (g.tray_x, g.tray_y, z1, g.tray_yaw),
                   (g.place_x, g.place_y, z1, g.tray_yaw + dyaw), (g.place_x, g.place_y, z0, g.tray_yaw + dyaw)]
        step = self.prm('carry_step')
        path = [corners[0]]
        for p0, p1 in zip(corners, corners[1:]):
            dist = math.dist(p0[:3], p1[:3]) + abs(p1[3] - p0[3]) * g.tray_length / 2
            n = max(1, int(math.ceil(dist / step)))
            path += [tuple(p0[k] + (p1[k] - p0[k]) * i / n for k in range(4)) for i in range(1, n + 1)]
        return path

    def carry_joint_path(self, g, handle_of):
        """Joint waypoints for both arms along the carry path (each handle keeps its arm)."""
        path = self.carry_path(g)
        d = g.tray_length / 2.0 - self.prm('tray_handle') / 2.0
        h1, _ = self.tray_handles(g.tray_x, g.tray_y, g.tray_yaw, g.tray_length)
        sign = {n: (1.0 if h == h1 else -1.0) for n, h in handle_of.items()}
        rows, prev = [], {}
        for x, y, z, yaw in path:
            row = {}
            for n, s in sign.items():
                hx, hy = x + s * d * math.cos(yaw), y + s * d * math.sin(yaw)
                q = self.ik_or_fail(hx, hy, z, yaw, 'carry', n)
                if n in prev:   # keep the wrist roll continuous (IK folds it to a 90-deg window)
                    q[4] = prev[n] + ((q[4] - prev[n] + math.pi / 4) % (math.pi / 2) - math.pi / 4)
                prev[n] = q[4]
                row[n] = q
            rows.append(row)
        return path, rows

    def execute_joint_rows(self, arms, rows, label):
        """Time-parameterize joint rows for several arms and run them as one trajectory."""
        names = [j for a in arms for j in a.joints]
        traj = JointTrajectory()
        traj.joint_names = names
        now = [self._joint_pos.get(j, 0.0) for j in names]
        t = 0.0
        step_t = self.prm('carry_step') / self.prm('carry_speed')
        for row in rows:
            q = [v for a in arms for v in row[a.name]]
            t += max(step_t, max(abs(x - y) for x, y in zip(q, now)) / self.prm('carry_joint_speed'))
            now = q
            pt = JointTrajectoryPoint()
            pt.positions = [float(v) for v in q]
            pt.time_from_start = DurationMsg(sec=int(t), nanosec=int((t % 1) * 1e9))
            traj.points.append(pt)
        if not self._exec.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('execute_trajectory action server not available')
        goal = ExecuteTrajectory.Goal()
        goal.trajectory = RobotTrajectory(joint_trajectory=traj)
        self.get_logger().info(f'[{label}] {len(rows)} waypoints, {t:.1f} s')
        result = self._wait_result(self._exec.send_goal_async(goal), t + 30.0)
        if result is None or result.error_code.val != MoveItErrorCodes.SUCCESS:
            code = None if result is None else result.error_code.val
            raise RuntimeError(f'{label}: trajectory execution failed (error_code={code})')
        self.wait_settled([j for a in arms for j in a.joints])

    def run_carry(self, g, stage=lambda _: None):
        if len(self.arms) < 2:
            raise RuntimeError('two-arm carry needs two arms')
        handles = self.tray_handles(g.tray_x, g.tray_y, g.tray_yaw, g.tray_length)
        handle_of = self.assign_handles(handles)
        arms = [self.arm(n) for n in handle_of]
        z0, up = self.prm('tray_grasp_z'), self.prm('approach_height')
        grasp_yaw = g.tray_yaw

        # everything is checked before the first motion
        q_pre = {a.name: self.ik_or_fail(*handle_of[a.name], z0 + up, grasp_yaw, 'pre-grasp', a) for a in arms}
        q_grasp = {a.name: self.ik_or_fail(*handle_of[a.name], z0, grasp_yaw, 'grasp', a) for a in arms}
        path, rows = self.carry_joint_path(g, handle_of)
        end = path[-1]
        d = g.tray_length / 2.0 - self.prm('tray_handle') / 2.0
        h1, _ = handles
        q_retreat = {}
        for a in arms:
            s = 1.0 if handle_of[a.name] == h1 else -1.0
            q_retreat[a.name] = self.ik_or_fail(end[0] + s * d * math.cos(end[3]), end[1] + s * d * math.sin(end[3]),
                                                z0 + up, end[3], 'retreat', a)
            # same wrist roll as at the end of the carry, so the retreat is a straight lift
            q_retreat[a.name][4] = rows[-1][a.name][4]

        for a in arms:
            stage(a.label('open gripper'))
            self.gripper(self.prm('gripper_open'), 'open', a)
        for a in arms:
            stage(a.label('pre-grasp'))
            self.move_joints(q_pre[a.name], 'pre-grasp', a)
            stage(a.label('grasp'))
            self.move_joints(q_grasp[a.name], 'grasp', a)
        for a in arms:
            stage(a.label('close gripper'))
            self.gripper(self.prm('gripper_closed'), 'close', a)
        for a in arms:
            self.verify_grasp(a, self.prm('tray_color'), stage)
        stage('carry')
        self.execute_joint_rows(arms, rows, 'carry')
        for a in arms:
            stage(a.label('release'))
            self.gripper(self.prm('carry_release'), 'release', a)
        for a in arms:
            stage(a.label('retreat'))
            self.move_joints(q_retreat[a.name], 'retreat', a)
            stage(a.label('observe'))
            self.go_observe(a)

    # ------------------------------------------------------------------ action plumbing
    def _on_goal(self, _):
        return GoalResponse.REJECT if self._busy.locked() else GoalResponse.ACCEPT

    def _run_action(self, gh, result, feedback, fn):
        def stage(name):
            feedback.stage = name
            gh.publish_feedback(feedback)
            if gh.is_cancel_requested:
                raise InterruptedError('canceled')

        with self._busy:
            try:
                out = fn(gh.request, stage)
                result.success = True
                result.message = f'done by {out.name}' if isinstance(out, Arm) and out.name else 'done'
                gh.succeed()
            except InterruptedError:
                result.message = 'canceled'
                gh.canceled()
            except GraspError as e:
                # nothing (useful) in the hand: open, get out of the camera view, report
                self.get_logger().error(str(e))
                result.message = str(e)
                try:
                    self.recover()
                except Exception as e2:  # noqa: BLE001
                    result.message += f' (recovery failed: {e2})'
                gh.abort()
            except Exception as e:  # noqa: BLE001 - report every failure to the client
                self.get_logger().error(str(e))
                result.message = str(e)
                if self.prm('fold_on_error'):
                    try:
                        for a in self.arms.values():
                            self.go_observe(a)
                    except Exception as e2:  # noqa: BLE001
                        result.message += f' (folding failed: {e2})'
                gh.abort()
        return result

    def _execute(self, gh):
        return self._run_action(gh, PickPlace.Result(), PickPlace.Feedback(), self.run_pick_place)

    def _execute_carry(self, gh):
        return self._run_action(gh, CarryTogether.Result(), CarryTogether.Feedback(), self.run_carry)


def main():
    rclpy.init()
    node = PickPlaceExecutor()
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
